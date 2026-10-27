"""``SOURCE_CONFIG`` for the local Stable Audio Open 1.0 generator (report 02 · 07 · 10 §4.1).

Stdlib-only and declarative — imports neither ``torch`` nor ``diffusers``, so
:func:`foley.sources.registry.discover_sources` can read it cheaply (it imports
only ``config.py``; the adapter + the heavy ML stack load lazily on first
generation). It declares the local ``diffusers.StableAudioPipeline`` backend, maps
foley's unified :data:`~foley.base.GENERATION_AFFORDANCES` onto the pipeline's
native ``__call__`` params, and — as required for every source — the **license
block**: ``default_license_id='Stability-Community'`` with ``cache_bytes_ok=True``
(generated audio is stored **by-value** — the generation flywheel).

Commercial guardrail (report 02/07): the Stability AI Community License permits
commercial use free **under $1M annual revenue**; that cap flows automatically from
the ``LICENSE_FLAGS['Stability-Community']`` row (``revenue_cap_usd=1_000_000``,
never hand-set) and is enforced by :func:`foley.keep` at select time.

Two foley affordances have **no** native pipeline param — ``loop`` (a future WEAVE
crossfade) and ``output_format`` (the audio-write layer, not the model) — so they
are listed unsupported and warn-and-drop; the adapter never fabricates a kwarg.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "stable_audio",
    "kind": "generate",
    "display_name": "Stable Audio Open 1.0 (local diffusers)",
    "website": "https://huggingface.co/stabilityai/stable-audio-open-1.0",
    "auth": None,  # local model (a HF token is only needed if the repo is gated)
    "dependencies": [],
    "optional_dependencies": [
        "torch",
        "diffusers",
        "transformers",
        "soundfile",
        "accelerate",
    ],  # foley[stable-audio]; imported lazily inside the adapter
    # unified foley GENERATION_AFFORDANCES -> StableAudioPipeline native param names.
    "param_map": {
        "prompt": {"native_name": "prompt", "required": True},
        "duration": {"native_name": "audio_end_in_s"},
        # foley prompt_influence (0..1) -> native guidance_scale, linear 1..15
        # (foley.sources.base.native_adherence); None -> native_default, the
        # model's own 7.0. NB: the CFG kwarg is 'guidance_scale' (NOT 'cfg_scale');
        # it is always passed explicitly (the adapter never relies on the pipeline).
        "prompt_influence": {
            "native_name": "guidance_scale",
            "coerce": {"kind": "linear", "lo": 1.0, "hi": 15.0},
            "native_default": 7.0,
        },
        "negative_prompt": {"native_name": "negative_prompt"},
        "steps": {"native_name": "num_inference_steps"},
        # foley seed -> a torch.Generator built in the adapter.
        "seed": {"native_name": "generator", "adapter_handled": True},
    },
    "supported_affordances": [
        "prompt",
        "duration",
        "prompt_influence",
        "negative_prompt",
        "steps",
        "seed",
    ],
    # No native pipeline param: loop (future WEAVE crossfade), output_format
    # (audio-write layer). Warn-and-drop.
    "unsupported_affordances": ["loop", "output_format"],
    "on_unsupported_param": "warn",
    "native_defaults": {
        "model_id": "stabilityai/stable-audio-open-1.0",
        "generator_version": "stable-audio-open-1.0",
        "audio_start_in_s": 0.0,
        "duration_default_s": 10.0,  # NOT the 47.55s model max
        "duration_max_s": 47.55,
        "sample_rate": 44100,  # the model's fixed output rate (the pipeline reports it)
        "num_inference_steps_default": 200,
        # A distilled checkpoint (post-trained for CFG 1, ~8 steps) sets this True,
        # with prompt_influence's native_default 1.0: a requested prompt_influence is
        # then noted and not applied (#70). Stable Audio Open 1.0 is not distilled.
        "distilled": False,
        "num_waveforms_per_prompt": 1,
        "output_type": "np",
    },
    "output": {"default_format": "wav", "returns": "bytes", "storage": "by_value"},
    # MANDATORY license block (foley-dev-add-source) — the SSOT seed. cache_bytes_ok
    # True => by-value storage; the $1M revenue cap flows from the license_id row.
    "license": {
        "default_license_id": "Stability-Community",
        "cache_bytes_ok": True,
    },
    "commercial_ok": True,  # generate guardrail (revenue-capped; enforced by keep())
    # What a caller's ``provider_params`` (#61) may not do: the prompt (and its
    # embeddings), the seed (its generator / latents) and the output type are
    # foley's, so provenance records what was actually run.
    "provider_params": {
        "append": {},
        "reserved": [
            "prompt",
            "prompt_embeds",
            "negative_prompt_embeds",
            "seed",
            "generator",
            "latents",
            "output_type",
        ],
        "priced": [],
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "local inference",
        "seen": "2026-10-04",
    },
    # Vendor facts a config cannot imply (foley.capabilities_of); only documented ones.
    "capabilities": {"watermarked": False},  # local open weights: no vendor watermark
    "data_egress": "local",  # runs entirely on-device (offline-capable; report 12)
}
