"""pyfxr procedural adapter: a category preset, seeded, rendered to audio bytes (#76).

pyfxr's presets (``pyfxr.laser()``, ``pyfxr.pickup()``, ...) draw their parameters from
the module-level ``random`` of ``pyfxr``. The adapter swaps a ``random.Random(seed)``
in for the one draw, under a lock, and puts the module back: the global ``random`` is
never reseeded. The drawn parameters, with the caller's ``provider_params`` over them,
build a ``pyfxr.SFX``; its full resolved parameter set (every field, defaults included)
is recorded in ``generation_params``, so the clip can be rebuilt from parameters alone.

pyfxr renders mono 16-bit PCM at ``pyfxr.SAMPLE_RATE`` (44.1 kHz) at full scale; the
adapter scales it to float with the config's ``render`` gain, pads a blip shorter than
Tier-0 QC admits (:func:`~foley.sources.base.pad_to_qc_minimum`), and encodes it with
:func:`foley.audio.encode`. A noise-waveform clip records ``bit_exact: False``. The licence is
``procedural-free`` with ``is_ai_generated=False`` (no disclosure, no watermark). The
adapter does no storage: :func:`foley.generate` ingests the clip.
"""

from __future__ import annotations

import random
import threading
from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import (
    GeneratedClip,
    draw_seed,
    generated_license,
    source_stated_terms,
    merge_provider_params,
    pad_to_qc_minimum,
    recorded_params,
    resolve_preset,
    unsupported_notes,
)
from .config import SFX_PARAMS, SOURCE_CONFIG

#: Serialises the swap of ``pyfxr.random``: two threads must not share one draw.
_DRAW_LOCK = threading.Lock()


def _pyfxr():
    """``pyfxr``, imported lazily (the ``foley[pyfxr]`` extra)."""
    import pyfxr

    return pyfxr


def _seeded_draw(pyfxr, preset_fn: str, seed: int):
    """The ``SFX`` pyfxr's ``preset_fn`` draws with its ``random`` seeded by ``seed``."""
    with _DRAW_LOCK:
        module_random = pyfxr.random
        pyfxr.random = random.Random(seed)
        try:
            return getattr(pyfxr, preset_fn)()
        finally:
            pyfxr.random = module_random


def _full_params(sfx) -> dict:
    """Every native parameter of ``sfx``, defaults included (``wave_type`` as an int)."""
    params = {name: getattr(sfx, name) for name in SFX_PARAMS}
    params["wave_type"] = params["wave_type"].value
    return params


class PyfxrAdapter:
    """The pyfxr procedural adapter (a :class:`~foley.sources.base.GenerateAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (defaults to the module's), passed positionally
            by the registry's lazy loader.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config if config is not None else SOURCE_CONFIG
        self.name = self.config["name"]

    def generate(
        self,
        prompt: str,
        *,
        preset: Optional[str] = None,
        seed: Optional[int] = None,
        provider_params: Optional[dict] = None,
        loop: bool = False,
        output_format: str = "wav",
        **kw,
    ) -> GeneratedClip:
        """Synthesize the category preset ``prompt`` names (or ``preset``).

        Args:
            prompt: The sound description; picks the preset when ``preset`` is not
                given (``config['preset_keywords']``), and is the clip's caption.
            preset: A canonical preset (``config['presets']``), overriding the prompt.
            seed: Seeds the preset's parameter draw. ``None`` draws one
                (:func:`~foley.sources.base.draw_seed`) and records it.
            provider_params: Native ``pyfxr.SFX`` params (``base_freq``,
                ``env_decay``, ``wave_type``, ...) set over the preset's draw.
            loop: No native param: noted and ignored.
            output_format: No native param (the audio layer's): noted and ignored.
            **kw: Other affordances (``duration_s``, ``steps``, ...): noted and ignored.

        Returns:
            A :class:`~foley.sources.base.GeneratedClip` under ``procedural-free``,
            ``is_ai_generated=False``.

        Raises:
            UnsupportedParameter: When no preset is given and none matches the prompt.
        """
        notes = unsupported_notes(
            self.config, loop=loop, output_format=output_format, **kw
        )
        preset, matched = resolve_preset(self.config, prompt, preset)
        notes += [matched] if matched else []
        seed = int(seed) if seed is not None else draw_seed()

        pyfxr = _pyfxr()
        drawn = _seeded_draw(pyfxr, self.config["presets"][preset], seed)
        params = merge_provider_params(
            _full_params(drawn), provider_params, policy=self.config["provider_params"]
        )
        sfx = pyfxr.SFX(**params)
        params = _full_params(sfx)  # normalised by pyfxr (a wave_type name -> its int)
        render = self.config["render"]
        audio_bytes, rendered = _render(
            sfx, pyfxr.SAMPLE_RATE, gain_db=render["output_gain_db"], notes=notes
        )
        if params["wave_type"] == render["noise_wave_type"]:
            rendered["bit_exact"] = False
            notes.append(
                "noise waveform: pyfxr renders noise with C rand, so the same seed and "
                "params give a different noise each time (not bit-reproducible)"
            )
        lic = generated_license(
            terms=source_stated_terms(self.config),
            source=self.name,
            license_id=self.config["license"]["default_license_id"],
            generator_model=self.name,
            generator_version=_version(),
            generation_prompt=prompt,
            generation_seed=seed,
            generation_params=recorded_params(
                dict(params, preset=preset, sample_rate=pyfxr.SAMPLE_RATE, **rendered),
                provider_params,
            ),
            ai_generated=False,
        )
        record = SoundRecord(
            id=f"{self.name}:pending", license=lic, caption=prompt or preset
        )
        return GeneratedClip(
            audio_bytes=audio_bytes,
            candidate=Candidate(sound=record, origin=CandidateOrigin.generated),
            notes=notes,
        )


def _render(
    sfx, sample_rate: int, *, gain_db: float, notes: list
) -> "tuple[bytes, dict]":
    """``(container bytes, how it was rendered)``: ``sfx`` scaled by ``gain_db``, a blip
    shorter than Tier-0 QC admits padded with trailing silence (noted)."""
    import numpy as np

    from ...audio import encode

    pcm = np.frombuffer(memoryview(sfx.build()), dtype=np.int16)
    samples = pcm.astype(np.float32) * np.float32(10 ** (gain_db / 20) / 32768.0)
    samples, padded_to_s = pad_to_qc_minimum(samples, sample_rate, notes=notes)
    rendered = {"gain_db": gain_db}
    if padded_to_s is not None:
        rendered["padded_to_s"] = padded_to_s
    return encode(samples, sample_rate), rendered


def _version() -> Optional[str]:
    """The installed pyfxr version (recorded as the generator version)."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"pyfxr {version('pyfxr')}"
    except PackageNotFoundError:  # pragma: no cover - imported, yet not installed
        return None


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = PyfxrAdapter
