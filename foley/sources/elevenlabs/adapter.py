"""ElevenLabs Sound Effects generate adapter — hosted Text-to-SFX v2 over HTTP.

Turns a natural-language prompt into a :class:`~foley.sources.base.GeneratedClip`
via the ElevenLabs ``POST /v1/sound-generation`` endpoint (report 02 §ElevenLabs).
The response is raw audio bytes (default MP3 44.1 kHz), stored **by-value** (the
generation flywheel) once the :func:`foley.sources.generate.generate` façade routes
it through :func:`~foley.index.ingest.ingest_one`.

Two ElevenLabs-specific quirks the adapter handles:

* **``output_format`` is a URL query parameter**, not a JSON body field; everything
  else (``text`` / ``model_id`` / ``prompt_influence`` / ``loop`` /
  ``duration_seconds``) is the JSON body.
* **No seed / negative-prompt / step control** — generation is non-deterministic, so
  ``generation_seed`` stays ``None`` and those unified affordances warn-and-drop.

HTTP is dependency-injected (a :class:`~foley.sources.http.Transport`), so the
adapter is fully testable with no network and ``import foley`` stays dol-only; the
real ``requests`` lives only behind
:func:`~foley.sources.http.requests_transport` (the ``foley[elevenlabs]`` extra).
The adapter performs NO storage/library access — it builds the audio + a generated
:class:`~foley.base.LicenseRecord` and returns; the façade converges it on the
shared ingest pipeline.
"""

from __future__ import annotations

import io
import os
import wave
from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    generated_license,
    native_adherence,
    resolve_source_key,
)
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

#: Unified affordances with no ElevenLabs SFX equivalent (warn-and-drop).
_UNSUPPORTED = ("negative_prompt", "steps", "seed")


#: Leading bytes of containers / encodings that must never be wrapped as raw PCM.
_CONTAINER_MAGIC = (b"RIFF", b"fLaC", b"OggS", b"ID3", b"\x1f\x8b", b"\xef\xbb\xbf")


#: MPEG audio Layer III tables (ISO 11172-3 / 13818-3): kbit/s by bitrate index, Hz by
#: sample-rate index, keyed by the version bits (3: MPEG-1, 2: MPEG-2, 0: MPEG-2.5).
_MP3_KBPS = {
    3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_MP3_KBPS[0] = _MP3_KBPS[2]
_MP3_HZ = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
_LAYER_III = 1


def _mp3_frame(header: bytes):
    """``(version, sample_rate, frame_length)`` of an MPEG Layer III frame header at the
    start of ``header``, or ``None`` if it is not one."""
    if len(header) < 4 or header[0] != 0xFF or header[1] & 0xE0 != 0xE0:
        return None
    version, layer = (header[1] >> 3) & 3, (header[1] >> 1) & 3
    bitrate_index, rate_index = header[2] >> 4, (header[2] >> 2) & 3
    if version not in _MP3_HZ or layer != _LAYER_III:
        return None
    if bitrate_index in (0, 15) or rate_index == 3:  # free format, bad, reserved
        return None
    sample_rate = _MP3_HZ[version][rate_index]
    coefficient = 144 if version == 3 else 72  # samples per frame / 8
    padding = (header[2] >> 1) & 1
    length = coefficient * _MP3_KBPS[version][bitrate_index] * 1000 // sample_rate
    return version, sample_rate, length + padding


def _is_mp3(audio: bytes) -> bool:
    """An untagged MP3: a Layer III frame header, confirmed by the next frame's header
    when the body is long enough to hold one.

    A lone header check (``0xFF`` then three set bits) also matches PCM whose first
    samples are -1 and 0 (``FF FF 00 00``), which then went out without its WAV header.
    """
    first = _mp3_frame(audio[:4])
    if first is None:
        return False
    version, sample_rate, length = first
    if len(audio) < length + 4:
        return True  # a single frame (or a cut one): the header is all there is
    second = _mp3_frame(audio[length : length + 4])
    return second is not None and second[:2] == (version, sample_rate)


def _is_text(head: bytes) -> bool:
    """Printable UTF-8 (an HTML/JSON error page, in any language)."""
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        try:  # the cut may fall inside a multi-byte character
            text = head[:-3].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return bool(text) and all(c.isprintable() or c in "\t\n\r" for c in text)


def _looks_like_raw_pcm(audio: bytes) -> bool:
    """False for a known container, an untagged MP3, or a text body (an error page).

    Wrapping any of them as PCM would turn it into a "valid" WAV of noise and hide
    the problem from ingest's decode check.
    """
    head = audio[:64]
    if not head or head.startswith(_CONTAINER_MAGIC) or _is_mp3(audio):
        return False
    return not _is_text(head)


class _HTTPStatusError(RuntimeError):
    """A non-200 from ElevenLabs (still a ``RuntimeError``); carries ``status_code``."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _safe_detail(resp) -> str:
    """Best-effort extract of an ElevenLabs error ``detail`` (never raises)."""
    try:
        body = resp.json()
    except Exception:
        return "<no detail>"
    if isinstance(body, dict):
        return str(body.get("detail", body))
    return str(body)


class ElevenLabsAdapter:
    """ElevenLabs Sound Effects generate adapter (a :class:`~foley.sources.base.GenerateAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (defaults to the module's). Passed positionally
            by the registry's lazy loader (the arioso ``Adapter(config)`` convention).
        api_key: The ElevenLabs token. Defaults to ``$ELEVENLABS_API_KEY``.
        http: The injected :class:`~foley.sources.http.Transport` (defaults to
            :func:`~foley.sources.http.requests_transport`); tests pass a fake.
        plan: The ElevenLabs account plan (``'elevenlabs-paid-plan'`` |
            ``'elevenlabs-free-plan'``), which decides the generated sound's licence.
            Defaults to ``$FOLEY_ELEVENLABS_PLAN``; with neither, ``generate`` refuses
            before calling the API (#56).
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        api_key: Optional[str] = None,
        http: Optional[Transport] = None,
        plan: Optional[str] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        self.name = self.config["name"]
        self._api_key = api_key
        self._plan = plan
        self._http: Transport = http if http is not None else requests_transport

    @property
    def plan(self) -> str:
        """The account plan = the generated sound's ``license_id`` (fail-closed when unknown)."""
        lic_cfg = self.config["license"]
        env_var = lic_cfg["plan_env_var"]
        plan = self._plan if self._plan is not None else os.environ.get(env_var)
        if plan not in lic_cfg["plans"]:
            got = "unset" if plan is None else repr(plan)
            raise SourceConfigurationError(
                f"ElevenLabs plan is {got}: set ${env_var} (or pass plan=) to one of "
                f"{list(lic_cfg['plans'])}. The plan decides whether the sound may be "
                "used commercially, so foley does not assume it; nothing was generated."
            )
        return plan

    def request_salt(self) -> str:
        """What besides the request decides the result: the plan (it decides the licence)."""
        return self.plan

    # -- auth / http helpers ------------------------------------------------

    @property
    def api_key(self) -> str:
        """The ElevenLabs token (constructor, else a bound key, else ``$ELEVENLABS_API_KEY``)."""
        return resolve_source_key(self.config, self._api_key)

    def _headers(self) -> dict:
        return {self.config["auth"]["header"]: self.api_key}

    # -- GenerateAdapter surface --------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        duration: Optional[float] = None,
        prompt_influence: Optional[float] = None,
        negative_prompt: Optional[str] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
        loop: bool = False,
        output_format: str = "wav",
        **kw,
    ) -> GeneratedClip:
        """Generate a sound effect for ``prompt``; return its bytes + provisional candidate.

        Args:
            prompt: The natural-language sound description (required).
            duration: Seconds (clamped to the native ``0.5..30`` range). ``None``
                lets the model auto-determine the length from the prompt.
            prompt_influence: ``0..1`` (identity map to the native field; higher =
                closer to the prompt, less variety). ``None`` (default) omits it, so
                the API applies its own default.
            negative_prompt / steps / seed: No ElevenLabs SFX equivalent — a
                non-default value warns-and-drops (recorded in the clip notes);
                ``generation_seed`` stays ``None``.
            loop: Produce a seamless-loopable clip (native ``loop``; v2 default).
            output_format: Coarse foley token (``wav`` | ``opus`` | ``mp3``)
                translated to the native enum; ``wav`` is the lossless ``pcm_48000``
                wrapped in a WAV header here, falling back to MP3 (with a note) if
                the account's plan refuses PCM. Ingest re-archives to FLAC.
            **kw: Extra/unknown affordances (warn-and-dropped).

        Returns:
            A :class:`~foley.sources.base.GeneratedClip` (``origin=generated``,
            ``license_id`` = the account plan, ``is_ai_generated=True``).

        Raises:
            RuntimeError: If the plan is unknown (before any API call).
        """
        license_id = self.plan  # fail closed BEFORE the paid call
        notes: list = []
        native_output_format = self._resolve_output_format(output_format, notes)
        self._warn_unsupported(
            notes, negative_prompt=negative_prompt, steps=steps, seed=seed, **kw
        )

        model_id = self.config["native_defaults"]["model_id"]
        native_influence = native_adherence(self.config, prompt_influence, notes)
        body: dict = {"text": prompt, "model_id": model_id, "loop": bool(loop)}
        if native_influence is not None:
            body["prompt_influence"] = native_influence
        if duration is not None:
            body["duration_seconds"] = self._clamp_duration(duration)

        audio_bytes, native_output_format = self._invoke_with_fallback(
            native_output_format, body, notes
        )
        audio_bytes = self._wrap_pcm(
            audio_bytes, native_output_format, body.get("duration_seconds"), notes
        )

        # The RESOLVED native params (guards against passing unified names) — recorded
        # verbatim in provenance for reproducibility/audit.
        resolved = {
            "model_id": model_id,
            "prompt_influence": native_influence,
            "loop": bool(loop),
            "output_format": native_output_format,
            "duration_seconds": body.get("duration_seconds"),
        }
        lic = generated_license(
            source=self.name,
            license_id=license_id,
            attribution_text=self.config["license"]
            .get("plan_attribution", {})
            .get(license_id),
            generator_model=model_id,
            generator_version=self.config["native_defaults"].get("generator_version"),
            generation_prompt=prompt,
            generation_seed=None,  # non-deterministic backend
            generation_params=resolved,
        )
        record = SoundRecord(
            id=f"{self.name}:pending",  # discarded placeholder (façade ingests with sound_id=None)
            license=lic,
            caption=prompt,
        )
        candidate = Candidate(sound=record, origin=CandidateOrigin.generated)
        return GeneratedClip(audio_bytes=audio_bytes, candidate=candidate, notes=notes)

    # -- helpers ------------------------------------------------------------

    def _resolve_output_format(self, output_format: str, notes: list) -> str:
        """Translate a coarse foley token to the native enum (with a fallback note)."""
        table = self.config["param_map"]["output_format"]["to_native_map"]
        native = table.get(output_format)
        if native is None:
            native = self.config["native_defaults"]["output_format"]
            notes.append(
                f"output_format {output_format!r} not offered by ElevenLabs SFX; "
                f"using {native!r}"
            )
        return native

    def _invoke_with_fallback(
        self, native_output_format: str, body: dict, notes: list
    ) -> "tuple[bytes, str]":
        """Call the endpoint; on a 4xx for a format with a declared fallback, retry once.

        Whether PCM needs a higher plan tier for sound effects is unverified, so a
        plan-tier refusal (``fallback_statuses``: 402/403) on ``pcm_*`` is retried
        with the config's ``fallback_on_4xx`` format (a refusal produces no audio,
        so nothing is billed twice) and recorded in ``notes``. Anything else raises. Returns ``(bytes, format actually used)``.
        """
        spec = self.config["param_map"]["output_format"]
        try:
            return self._invoke(
                params={"output_format": native_output_format}, body=body
            ), native_output_format
        except _HTTPStatusError as exc:
            fallback = spec.get("fallback_on_4xx", {}).get(native_output_format)
            if fallback is None or exc.status_code not in spec.get(
                "fallback_statuses", ()
            ):
                raise
            notes.append(
                f"output_format {native_output_format!r} refused by ElevenLabs "
                f"({exc.status_code}); fell back to {fallback!r}"
            )
            return self._invoke(params={"output_format": fallback}, body=body), fallback

    def _wrap_pcm(
        self,
        audio: bytes,
        native_output_format: str,
        duration_s: Optional[float],
        notes: list,
    ) -> bytes:
        """Give raw ``pcm_*`` bytes a WAV header (16-bit LE); other formats pass through.

        The channel count comes from the config. When a duration was requested, the
        byte length confirms mono or stereo; otherwise an unverified layout is noted.
        """
        layout = (self.config["param_map"]["output_format"].get("pcm") or {}).get(
            native_output_format
        )
        if layout is None or not _looks_like_raw_pcm(audio):
            return audio  # a container or a text error body: decode decides, never wrap
        rate, channels, width = layout["sample_rate"], layout.get("channels", 1), 2
        confirmed = False
        if duration_s:
            implied = len(audio) / (rate * width * float(duration_s))
            if 0.9 <= implied <= 1.1:
                channels, confirmed = 1, True
            elif 1.9 <= implied <= 2.1:
                channels, confirmed = 2, True
        if not confirmed and not layout.get("verified"):
            notes.append(
                f"{native_output_format}: channel layout not documented for ElevenLabs "
                f"SFX; assumed {channels} ch S16LE"
            )
        elif confirmed and channels != layout.get("channels", 1):
            notes.append(
                f"{native_output_format}: byte length for the requested duration "
                f"implies {channels} ch; wrapped as {channels} ch"
            )
        frame = width * channels
        audio = audio[: len(audio) - len(audio) % frame]  # never a partial frame
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.setframerate(rate)
            w.writeframes(audio)
        return buf.getvalue()

    def _warn_unsupported(self, notes: list, **passed) -> None:
        """Record a note for each unsupported affordance passed with a non-default value."""
        for name in _UNSUPPORTED:
            if passed.get(name) is not None:
                notes.append(
                    f"affordance {name!r} is unsupported by ElevenLabs SFX; ignored"
                )
        extra = [k for k in passed if k not in _UNSUPPORTED and passed[k] is not None]
        for name in extra:
            notes.append(f"affordance {name!r} is not a known SFX param; ignored")

    def _clamp_duration(self, duration: float) -> float:
        """Clamp ``duration`` to the native ``[min, max]`` seconds window."""
        lo = self.config["native_defaults"]["duration_min_s"]
        hi = self.config["native_defaults"]["duration_max_s"]
        return max(lo, min(float(duration), hi))

    def _invoke(self, *, params: dict, body: dict) -> bytes:
        """POST to the SFX endpoint and return the raw audio bytes (never JSON).

        ``output_format`` is a URL query param (``params``); the rest is the JSON
        ``body``. A non-200 raises ``RuntimeError`` with the best-effort ``detail``.
        """
        endpoint = self.config["api"]["generate_endpoint"]
        url = self.config["api"]["base_url"] + endpoint["path"]
        headers = dict(self._headers())
        headers["Content-Type"] = "application/json"
        resp = self._http(
            endpoint["method"], url, params=params, headers=headers, json=body
        )
        if resp.status_code != 200:
            raise _HTTPStatusError(
                resp.status_code,
                f"ElevenLabs {endpoint['method']} {url} -> {resp.status_code}: "
                f"{_safe_detail(resp)}",
            )
        return resp.content


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = ElevenLabsAdapter
