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

import os
from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    generated_license,
    native_adherence,
)
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

#: Unified affordances with no ElevenLabs SFX equivalent (warn-and-drop).
_UNSUPPORTED = ("negative_prompt", "steps", "seed")


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
        """The ElevenLabs token (from the constructor or ``$ELEVENLABS_API_KEY``)."""
        env_var = self.config["auth"]["env_var"]
        key = self._api_key if self._api_key is not None else os.environ.get(env_var)
        if not key:
            raise SourceConfigurationError(
                f"ElevenLabs needs an API token: set ${env_var} or pass api_key=. "
                f"Get one at {self.config['auth'].get('apply_url', 'https://elevenlabs.io')}."
            )
        return key

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
                translated to the native enum; ``wav`` falls back to MP3 (the SFX
                endpoint has no lossless container) and is re-archived to FLAC by
                ingest.
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

        audio_bytes = self._invoke(
            params={"output_format": native_output_format}, body=body
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
        elif output_format == "wav":
            notes.append(
                "ElevenLabs SFX has no lossless WAV container; requested as "
                f"{native!r} (re-archived to FLAC on ingest)"
            )
        return native

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
            raise RuntimeError(
                f"ElevenLabs {endpoint['method']} {url} -> {resp.status_code}: "
                f"{_safe_detail(resp)}"
            )
        return resp.content


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = ElevenLabsAdapter
