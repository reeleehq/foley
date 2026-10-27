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
dol-only. The local-model DI seams are ``pipeline=`` (the analog of the hosted
adapters' ``http=``) and ``make_generator=`` (the seeded ``torch.Generator``): inject
fakes for both and no ML stack loads at all — the whole adapter is testable with no
torch. The adapter performs NO storage/library
access; the façade converges it on the shared ingest pipeline.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    draw_seed,
    generated_license,
    merge_provider_params,
    native_adherence,
    recorded_params,
    unsupported_notes,
)
from .config import SOURCE_CONFIG

#: ``make_generator(device, seed) -> generator``: the seeded RNG the pipeline draws from.
GeneratorFactory = Callable[[Any, int], Any]


def torch_generator(device, seed: int):
    """A ``torch.Generator`` on ``device`` seeded with ``seed`` (the default factory)."""
    import torch  # lazy: foley[stable-audio]

    return torch.Generator(device=device).manual_seed(int(seed))


class StableAudioAdapter:
    """Local Stable Audio Open 1.0 generate adapter (a :class:`~foley.sources.base.GenerateAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (defaults to the module's). Passed positionally
            by the registry's lazy loader (the arioso ``Adapter(config)`` convention).
        pipeline: An optional pre-built pipeline (the dependency-injection seam —
            a test injects a fake callable exposing ``.vae.sampling_rate`` +
            ``.device``; production omits it and the real
            ``diffusers.StableAudioPipeline`` lazy-loads on first generation).
        make_generator: ``make_generator(device, seed)``, the seeded generator handed
            to the pipeline (default :func:`torch_generator`); a test with a fake
            pipeline passes a fake one, so no torch is needed.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        pipeline=None,
        make_generator: Optional[GeneratorFactory] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        self.name = self.config["name"]
        self._injected_pipeline = pipeline
        self._make_generator = (
            make_generator if make_generator is not None else torch_generator
        )
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
        duration_s: Optional[float] = None,
        prompt_influence: Optional[float] = None,
        negative_prompt: Optional[str] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
        loop: bool = False,
        output_format: str = "wav",
        provider_params: Optional[dict] = None,
        **kw,
    ) -> GeneratedClip:
        """Generate a sound for ``prompt``; return its bytes + provisional candidate.

        Args:
            prompt: The natural-language sound description (required).
            duration_s: Seconds (clamped to the model's ~47.55 s max). ``None`` uses a
                sane 10 s default (NOT the 47.55 s maximum).
            prompt_influence: ``0..1`` unified adherence, mapped linearly onto the
                native ``guidance_scale`` (1..15). ``None`` (default) sends the
                model's own default (7.0 for Stable Audio Open 1.0); a distilled
                checkpoint ignores it with a note.
            negative_prompt: Content to exclude (ignored by the model when guidance
                ≤ 1).
            steps: Diffusion steps (native ``num_inference_steps``); default 200.
            seed: Reproducibility seed → a per-device ``torch.Generator``; recorded
                in provenance. ``None`` draws one (:func:`~foley.sources.base.draw_seed`)
                and records it, so the clip is reproducible all the same (#163).
            loop: No native param (a future WEAVE crossfade) — warn-and-drop.
            output_format: No native param (the audio-write layer) — warn-and-drop;
                the clip is archived as FLAC by ingest regardless.
            provider_params: Native ``StableAudioPipeline`` kwargs merged over the
                translated ones (#61; e.g. ``{"num_inference_steps": 50}``), recorded
                in ``generation_params``.
            **kw: Extra/unknown affordances (warn-and-dropped).

        Returns:
            A :class:`~foley.sources.base.GeneratedClip` (``origin=generated``,
            ``license_id='Stability-Community'``, ``is_ai_generated=True``,
            ``generation_seed`` captured).
        """
        nd = self.config["native_defaults"]
        notes = unsupported_notes(
            self.config, loop=loop, output_format=output_format, **kw
        )

        # Resolve unified affordances -> native params (recorded verbatim, so
        # provenance never carries the unified names — the guard against arioso's
        # confirmed cfg_scale mislabel + dropped-guidance bug).
        guidance_scale = native_adherence(self.config, prompt_influence, notes)
        if guidance_scale is None:  # never let the pipeline pick its own CFG
            raise SourceConfigurationError(
                f"{self.name}: param_map['prompt_influence'] needs a native_default "
                "(the guidance_scale to send when none is asked for)"
            )
        audio_end_in_s = min(
            duration_s if duration_s is not None else nd["duration_default_s"],
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
        native = merge_provider_params(
            native, provider_params, policy=self.config.get("provider_params")
        )

        seed = int(seed) if seed is not None else draw_seed()
        audio_bytes, sample_rate = self.invoke_native(prompt, native=native, seed=seed)

        resolved = recorded_params(
            dict(native, sample_rate=sample_rate, model_id=nd["model_id"]),
            provider_params,
        )
        lic = generated_license(
            source=self.name,
            license_id=self.config["license"]["default_license_id"],
            generator_model=nd["generator_version"],
            generator_version=nd["generator_version"],
            generation_prompt=prompt,
            generation_seed=seed,  # the seed sent: the caller's or the one drawn
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

    def invoke_native(self, prompt: str, *, native: dict, seed: Optional[int] = None):
        """Run the pipeline with native kwargs; return ``(encoded_bytes, sample_rate)``.

        The public entry below foley's translation (#61): ``native`` goes to the
        ``StableAudioPipeline`` call as is (``guidance_scale``, ``audio_end_in_s``, …).
        No licence record is built and no dispatch-layer check runs (cost, egress): a
        caller of this method owns those, and of the seed: ``seed=None`` here sends no
        generator (the pipeline's own randomness), where :meth:`generate` draws one.
        """
        pipe = self._pipe()
        generator = None if seed is None else self._make_generator(pipe.device, seed)
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
