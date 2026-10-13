"""Stable Audio Open 1.0 generate adapter — local ``diffusers`` inference.

Turns a natural-language prompt into a :class:`~foley.sources.base.GeneratedClip`
via ``diffusers.StableAudioPipeline`` running on-device (report 02 §Stable Audio
Open). The model produces a 44.1 kHz stereo waveform (up to ~47 s); the adapter
encodes it to container bytes, which the :func:`foley.sources.generate.generate`
façade stores **by-value** (the generation flywheel) through the shared
:func:`~foley.index.ingest.ingest_one` pipeline.

Load-bearing details verified against the diffusers docs + HF model card:

* **The CFG kwarg is ``guidance_scale``** (NOT ``cfg_scale``), and it MUST be passed
  explicitly or the pipeline silently uses its own default 7.0. foley maps its
  unified ``prompt_influence`` (0..1) onto it linearly (1..15, declared in the
  config's ``coerce``); ``None`` sends the model's own default, and a distilled
  checkpoint (``native_defaults["distilled"]``) always gets its native default.
* **Output is channel-first ``(channels, samples)``** — transposed to the
  time-first ``(frames, channels)`` foley/soundfile convention before encoding.
* **The sample rate is read off the pipeline** (``pipe.vae.sampling_rate`` = 44100),
  never hardcoded.
* **``loop`` and ``output_format`` have no native pipeline param** (loop is a future
  WEAVE crossfade; format is the audio-write layer) — they warn-and-drop; the
  adapter never fabricates a pipeline kwarg.

``torch`` / ``diffusers`` are imported lazily inside the methods (the
``foley[stable-audio]`` extra), so ``import foley`` and source discovery stay
dol-only. The local-model DI seam is ``pipeline=`` (the analog of the hosted
adapters' ``http=``): inject a fake pipeline and no ML stack loads at all — the
whole adapter is testable with no torch. The adapter performs NO storage/library
access; the façade converges it on the shared ingest pipeline.
"""

from __future__ import annotations

from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import GeneratedClip, generated_license, native_adherence
from .config import SOURCE_CONFIG


class StableAudioAdapter:
    """Local Stable Audio Open 1.0 generate adapter (a :class:`~foley.sources.base.GenerateAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (defaults to the module's). Passed positionally
            by the registry's lazy loader (the arioso ``Adapter(config)`` convention).
        pipeline: An optional pre-built pipeline (the dependency-injection seam —
            a test injects a fake callable exposing ``.vae.sampling_rate`` +
            ``.device``; production omits it and the real
            ``diffusers.StableAudioPipeline`` lazy-loads on first generation).
    """

    def __init__(self, config: Optional[dict] = None, *, pipeline=None):
        self.config = config if config is not None else SOURCE_CONFIG
        self.name = self.config["name"]
        self._injected_pipeline = pipeline
        self._loaded_pipeline = None

    # -- pipeline lifecycle -------------------------------------------------

    def _pipe(self):
        """Return the pipeline — the injected one, else lazy-load + cache it."""
        if self._injected_pipeline is not None:
            return self._injected_pipeline
        if self._loaded_pipeline is None:
            self._loaded_pipeline = self._load_pipeline()
        return self._loaded_pipeline

    def _load_pipeline(self):
        """Lazy-load ``StableAudioPipeline`` (float16 on CUDA, float32 on CPU)."""
        import torch  # lazy: foley[stable-audio]; keeps `import foley` dol-only
        from diffusers import StableAudioPipeline

        model_id = self.config["native_defaults"]["model_id"]
        cuda = torch.cuda.is_available()
        # float16-on-CPU is broken/very slow — branch the dtype on the device.
        dtype = torch.float16 if cuda else torch.float32
        from ...runtime import load_pretrained

        pipe = load_pretrained(
            StableAudioPipeline.from_pretrained, model_id, torch_dtype=dtype
        )
        return pipe.to("cuda" if cuda else "cpu")

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
        """Generate a sound for ``prompt``; return its bytes + provisional candidate.

        Args:
            prompt: The natural-language sound description (required).
            duration: Seconds (clamped to the model's ~47.55 s max). ``None`` uses a
                sane 10 s default (NOT the 47.55 s maximum).
            prompt_influence: ``0..1`` unified adherence, mapped linearly onto the
                native ``guidance_scale`` (1..15). ``None`` (default) sends the
                model's own default (7.0 for Stable Audio Open 1.0); a distilled
                checkpoint ignores it with a note.
            negative_prompt: Content to exclude (ignored by the model when guidance
                ≤ 1).
            steps: Diffusion steps (native ``num_inference_steps``); default 200.
            seed: Reproducibility seed → a per-device ``torch.Generator``; recorded
                in provenance. ``None`` → non-deterministic (no torch import).
            loop: No native param (a future WEAVE crossfade) — warn-and-drop.
            output_format: No native param (the audio-write layer) — warn-and-drop;
                the clip is archived as FLAC by ingest regardless.
            **kw: Extra/unknown affordances (warn-and-dropped).

        Returns:
            A :class:`~foley.sources.base.GeneratedClip` (``origin=generated``,
            ``license_id='Stability-Community'``, ``is_ai_generated=True``,
            ``generation_seed`` captured).
        """
        nd = self.config["native_defaults"]
        notes = self._warn_unsupported(loop=loop, output_format=output_format, **kw)

        # Resolve unified affordances -> native params (recorded verbatim, so
        # provenance never carries the unified names — the guard against arioso's
        # confirmed cfg_scale mislabel + dropped-guidance bug).
        guidance_scale = native_adherence(self.config, prompt_influence, notes)
        audio_end_in_s = min(
            duration if duration is not None else nd["duration_default_s"],
            nd["duration_max_s"],
        )
        native = {
            "audio_end_in_s": audio_end_in_s,
            "audio_start_in_s": nd["audio_start_in_s"],
            "num_inference_steps": (
                steps if steps is not None else nd["num_inference_steps_default"]
            ),
            "guidance_scale": guidance_scale,
            "negative_prompt": negative_prompt,
            "num_waveforms_per_prompt": nd["num_waveforms_per_prompt"],
        }

        audio_bytes, sample_rate = self._invoke(prompt, native=native, seed=seed)

        resolved = dict(native, sample_rate=sample_rate, model_id=nd["model_id"])
        lic = generated_license(
            source=self.name,
            license_id=self.config["license"]["default_license_id"],
            generator_model=nd["generator_version"],
            generator_version=nd["generator_version"],
            generation_prompt=prompt,
            generation_seed=seed,  # captured even when None
            generation_params=resolved,
        )
        record = SoundRecord(
            id=f"{self.name}:pending",  # discarded placeholder (façade ingests sound_id=None)
            license=lic,
            caption=prompt,
        )
        candidate = Candidate(sound=record, origin=CandidateOrigin.generated)
        return GeneratedClip(audio_bytes=audio_bytes, candidate=candidate, notes=notes)

    # -- helpers ------------------------------------------------------------

    def _warn_unsupported(self, *, loop: bool, output_format: str, **kw) -> list:
        """Collect notes for affordances the pipeline has no native param for."""
        notes: list = []
        if loop:
            notes.append(
                "loop has no native Stable Audio Open param (a future WEAVE "
                "crossfade); ignored"
            )
        if output_format and output_format != self.config["output"]["default_format"]:
            notes.append(
                f"output_format {output_format!r} is applied by the audio layer, "
                "not the model; ignored (archived as FLAC on ingest)"
            )
        for name, value in kw.items():
            if value is not None:
                notes.append(
                    f"affordance {name!r} is not a known Stable Audio param; ignored"
                )
        return notes

    def _invoke(self, prompt: str, *, native: dict, seed: Optional[int]):
        """Run the pipeline and return ``(encoded_bytes, sample_rate)``.

        Builds a per-device ``torch.Generator`` only when ``seed`` is set (so a
        ``seed=None`` generation never imports torch — the fake-pipeline test path).
        """
        pipe = self._pipe()
        generator = None
        if seed is not None:
            import torch  # lazy: only a seeded run needs a Generator

            generator = torch.Generator(device=pipe.device).manual_seed(int(seed))
        output = pipe(
            prompt=prompt,
            output_type=self.config["native_defaults"]["output_type"],
            generator=generator,
            **native,
        )
        sample_rate = int(pipe.vae.sampling_rate)  # read off the pipeline (44100)
        return self._encode(output.audios[0], sample_rate), sample_rate

    def _encode(self, audio, sample_rate: int) -> bytes:
        """Encode one waveform to container (FLAC) bytes for ingest.

        The pipeline emits channel-first ``(channels, samples)``; transpose to the
        time-first ``(frames, channels)`` foley/soundfile convention before encoding.
        """
        import numpy as np

        from ...audio import encode

        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim == 2:  # (channels, samples) -> (samples, channels)
            arr = arr.T
        return encode(arr, sample_rate)


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = StableAudioAdapter
