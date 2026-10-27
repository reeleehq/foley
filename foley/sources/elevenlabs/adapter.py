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

from ...base import Candidate, CandidateOrigin, SoundRecord, reject_renamed
from ...cost import actual_call_cost
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    generated_license,
    merge_provider_params,
    native_adherence,
    recorded_params,
    bound_source_account,
    native_output_format as native_output_format_for,
    operator_env_key,
    resolve_source_key,
    source_account_id,
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
    """A non-200 from ElevenLabs (still a ``RuntimeError``); carries ``status_code``.

    ``detail`` is the body's ``detail`` (a dict in the documented shape, a string in
    older responses), or ``None`` when the body is not JSON. ``unbilled``: the
    endpoint is one POST that returns the audio or an error, and an error produced
    no audio, so it was not charged
    (:func:`foley.sources._dispatch.provider_refused`).
    """

    unbilled = True

    def __init__(self, status_code: int, message: str, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _detail_of(resp):
    """The ElevenLabs error ``detail`` of ``resp`` (``None`` when absent; never raises)."""
    try:
        body = resp.json()
    except Exception:
        return None
    return body.get("detail", body) if isinstance(body, dict) else body


def _safe_detail(resp) -> str:
    """Best-effort extract of an ElevenLabs error ``detail`` (never raises)."""
    detail = _detail_of(resp)
    return "<no detail>" if detail is None else str(detail)


def _is_format_refusal(detail, native_output_format: str, codes) -> bool:
    """Whether an error ``detail`` says the plan refuses this output format (#100).

    The documented shape carries a ``code`` (and a legacy ``status``); a match on
    either against ``codes`` is a refusal. Without one, a message that names the
    requested format (``"Requested output format pcm_48000 ... is only allowed for
    Pro tier and above"``) is too; a message is read only when the detail carries
    no code or status at all. Anything else (another 403, such as a key missing
    a permission, or no body at all) is not.

    >>> _is_format_refusal({"code": "subscription_required"}, "pcm_48000",
    ...                    ["subscription_required"])
    True
    >>> _is_format_refusal("Requested output format pcm_48000 (PCM at 48000hz) is "
    ...                    "only allowed for Pro tier and above.", "pcm_48000", [])
    True
    >>> _is_format_refusal({"code": "missing_permissions", "message": "pcm_48000"},
    ...                    "pcm_48000", ["subscription_required"])
    False
    >>> _is_format_refusal({"code": ["subscription_required"]}, "pcm_48000",
    ...                    ["subscription_required"])
    False
    """
    if isinstance(detail, dict):
        tags = [detail.get("code"), detail.get("status")]
        if any(isinstance(t, str) and t in codes for t in tags):
            return True
        if any(t is not None for t in tags):
            return False  # a coded error that is not a tier refusal (its message aside)
        detail = detail.get("message")
    return isinstance(detail, str) and native_output_format in detail


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
            before calling the API (#56). When the key in use is a per-request one
            (bound, not passed as ``api_key=``), the plan is the one bound with it
            (:func:`~foley.sources.base.using_source_accounts`), never this or the
            env's (#98).
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
        """The account plan = the generated sound's ``license_id`` (fail-closed when unknown).

        It follows the key: a bound (per-request) key brings its own plan, and one
        bound without a plan is refused rather than labelled with the operator's.
        """
        lic_cfg = self.config["license"]
        env_var = lic_cfg["plan_env_var"]
        account = None if self._api_key else bound_source_account(self.name)
        if account is not None:
            plan = account.get("plan")
            if plan is None:
                raise SourceConfigurationError(
                    f"An ElevenLabs key is bound for this request without its plan. "
                    "Bind them together, e.g. foley.using_source_accounts(elevenlabs="
                    "{'key': ..., 'plan': ...}), with the plan one of "
                    f"{list(lic_cfg['plans'])}. The operator's plan (${env_var} or "
                    "plan=) is not assumed for another account's key; nothing was "
                    "generated."
                )
        elif self._is_other_accounts_key():
            plan = self._plan  # another account's api_key= brings its own plan=
            if plan is None:
                raise SourceConfigurationError(
                    "api_key= is not the operator's ElevenLabs key, so pass its plan= "
                    f"too (one of {list(lic_cfg['plans'])}). The operator's plan "
                    f"(${env_var}) is not assumed for another account's key; nothing "
                    "was generated."
                )
        else:
            plan = self._plan if self._plan is not None else os.environ.get(env_var)
        if plan not in lic_cfg["plans"]:
            got = "unset" if plan is None else repr(plan)
            raise SourceConfigurationError(
                f"ElevenLabs plan is {got}: set ${env_var} (or pass plan=) to one of "
                f"{list(lic_cfg['plans'])}. The plan decides whether the sound may be "
                "used commercially, so foley does not assume it; nothing was generated."
            )
        return plan

    def _is_other_accounts_key(self) -> bool:
        """Whether ``api_key=`` is not the operator's: an env key is set and differs.

        With no env key, an ``api_key=`` is how the operator configures foley in code,
        and the operator's plan (``plan=`` or the env's) applies to it.
        """
        env_key = operator_env_key(self.config)
        return bool(self._api_key and env_key and self._api_key != env_key)

    def account_id(self) -> str:
        """The account a call is made on, for the generations cache (``'operator'`` or a fingerprint)."""
        return source_account_id(self.config, self._api_key)

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
        duration_s: Optional[float] = None,
        model: Optional[str] = None,
        prompt_influence: Optional[float] = None,
        negative_prompt: Optional[str] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
        loop: bool = False,
        output_format: str = "wav",
        sample_rate: Optional[int] = None,
        provider_params: Optional[dict] = None,
        **kw,
    ) -> GeneratedClip:
        """Generate a sound effect for ``prompt``; return its bytes + provisional candidate.

        Args:
            prompt: The natural-language sound description (required).
            duration_s: Seconds (clamped to the native ``0.5..30`` range). ``None``
                lets the model auto-determine the length from the prompt.
            model: The native ``model_id`` to pin (``eleven_text_to_sound_v2`` |
                ``eleven_text_to_sound_v3``); ``None`` uses ``native_defaults``'.
                Recorded as the licence's ``generator_model`` / ``generator_version``.
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
            sample_rate: The rate (Hz) to ask for; it picks the native enum for
                ``output_format`` (``wav`` at 22050 is ``pcm_22050``). A rate the
                format lacks keeps its default rate, with a note.
            provider_params: Native request fields merged over the translated ones
                (#61): JSON body fields, except ``output_format``, which replaces the
                native format sent as the URL query param. Recorded in
                ``generation_params``.
            **kw: Extra/unknown affordances (warn-and-dropped).

        Returns:
            A :class:`~foley.sources.base.GeneratedClip` (``origin=generated``,
            ``license_id`` = the account plan, ``is_ai_generated=True``), its ``raw``
            the response's status code and headers.

        Raises:
            RuntimeError: If the plan is unknown (before any API call).
        """
        license_id = self.plan  # fail closed BEFORE the paid call
        notes: list = []
        overridden = "output_format" in (provider_params or {})  # it decides the rate
        native_output_format = native_output_format_for(
            self.config,
            output_format,
            sample_rate=sample_rate,
            notes=None if overridden else notes,
        )
        self._warn_unsupported(
            notes, negative_prompt=negative_prompt, steps=steps, seed=seed, **kw
        )

        model_id = model or self.config["native_defaults"]["model_id"]
        native_influence = native_adherence(self.config, prompt_influence, notes)
        body: dict = {"text": prompt, "model_id": model_id, "loop": bool(loop)}
        if native_influence is not None:
            body["prompt_influence"] = native_influence
        if duration_s is not None:
            body["duration_seconds"] = self._clamp_duration(duration_s)
        body = merge_provider_params(
            body, provider_params, policy=self.config.get("provider_params")
        )
        native_output_format = body.pop("output_format", native_output_format)

        resp, native_output_format = self._invoke_with_fallback(
            native_output_format, body, notes
        )
        audio_bytes = self._wrap_pcm(
            resp.content, native_output_format, body.get("duration_seconds"), notes
        )

        # The RESOLVED native params (guards against passing unified names) — recorded
        # verbatim in provenance for reproducibility/audit.
        resolved = recorded_params(
            {
                "prompt_influence": None,  # recorded even when not sent
                "duration_seconds": None,
                **{k: v for k, v in body.items() if k != "text"},
                "output_format": native_output_format,
            },
            provider_params,
        )
        lic = generated_license(
            source=self.name,
            license_id=license_id,
            attribution_text=self.config["license"]
            .get("plan_attribution", {})
            .get(license_id),
            generator_model=model_id,
            generator_version=model
            or self.config["native_defaults"].get("generator_version"),
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
        candidate.cost_actual_usd = actual_call_cost(
            self.config, duration_s=body.get("duration_seconds")
        )
        return GeneratedClip(
            audio_bytes=audio_bytes,
            candidate=candidate,
            notes=notes,
            raw=_response_meta(resp),
        )

    # -- helpers ------------------------------------------------------------

    def _invoke_with_fallback(self, native_output_format: str, body: dict, notes: list):
        """Call the endpoint; on a 4xx for a format with a declared fallback, retry once.

        A plan-tier refusal of the format (a ``fallback_statuses`` status whose
        error detail is a ``fallback_detail_codes`` code, or names the format; see
        :func:`_is_format_refusal`) is retried with the config's ``fallback_on_4xx``
        format (a refusal produces no audio, so nothing is billed twice) and
        recorded in ``notes``. Anything else raises. Returns ``(response, format
        actually used)``.
        """
        spec = self.config["param_map"]["output_format"]
        try:
            return self._invoke(
                params={"output_format": native_output_format}, body=body, notes=notes
            ), native_output_format
        except _HTTPStatusError as exc:
            fallback = spec.get("fallback_on_4xx", {}).get(native_output_format)
            if (
                fallback is None
                or exc.status_code not in spec.get("fallback_statuses", ())
                or not _is_format_refusal(
                    exc.detail,
                    native_output_format,
                    spec.get("fallback_detail_codes", ()),
                )
            ):
                raise
            notes.append(
                f"output_format {native_output_format!r} refused by ElevenLabs "
                f"({exc.status_code}); fell back to {fallback!r}"
            )
            return self._invoke(
                params={"output_format": fallback}, body=body, notes=notes
            ), fallback

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
        """Record a note for each unsupported affordance passed with a non-default value.

        A renamed affordance's old spelling raises ``TypeError`` instead (#75).
        """
        reject_renamed(passed)
        for name in _UNSUPPORTED:
            if passed.get(name) is not None:
                notes.append(
                    f"affordance {name!r} is unsupported by ElevenLabs SFX; ignored"
                )
        extra = [k for k in passed if k not in _UNSUPPORTED and passed[k] is not None]
        for name in extra:
            notes.append(f"affordance {name!r} is not a known SFX param; ignored")

    def _clamp_duration(self, duration_s: float) -> float:
        """Clamp ``duration_s`` to the native ``[min, max]`` seconds window."""
        lo = self.config["native_defaults"]["duration_min_s"]
        hi = self.config["native_defaults"]["duration_max_s"]
        return max(lo, min(float(duration_s), hi))

    def _invoke(self, *, params: dict, body: dict, notes: list):
        """:meth:`invoke_native`, with the credits the account was charged (the
        ``api.credits_header`` response header, when present) recorded in ``notes``."""
        resp = self.invoke_native(params=params, body=body)
        credits = _header(resp, self.config["api"].get("credits_header"))
        if credits is not None:
            notes.append(f"ElevenLabs charged {credits} credits for this call")
        return resp

    def invoke_native(self, *, params: dict, body: dict):
        """POST native ``params`` (URL query) and ``body`` (JSON) to the SFX endpoint.

        The public entry below foley's translation (#61): returns the transport's
        response as is (``.content`` holds the audio bytes, ``.headers`` the
        metadata). No plan/licence check and no dispatch-layer gate (cost
        authorization, egress, the generations cache) runs here: a caller of this
        method owns them, and pays for the call.

        Raises:
            RuntimeError: On a non-200 (an ``unbilled`` error carrying
                ``status_code`` and the best-effort ``detail``).
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
                detail=_detail_of(resp),
            )
        return resp


def _response_meta(resp) -> dict:
    """What an ElevenLabs response carries besides the audio: its status and headers."""
    headers = getattr(resp, "headers", None) or {}
    return {"status_code": resp.status_code, "headers": dict(headers)}


def _header(resp, name: Optional[str]) -> Optional[str]:
    """Response header ``name`` (case-insensitive), or ``None`` (a fake may have no headers)."""
    headers = getattr(resp, "headers", None) or {}
    if not name:
        return None
    wanted = name.lower()
    return next((v for k, v in headers.items() if k.lower() == wanted), None)


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = ElevenLabsAdapter
