"""``SOURCE_CONFIG`` for the local Stable Audio 3 Small-SFX generator (#72 · report 13 · 17).

Stdlib-only and declarative, like every source config. The model runs on a laptop CPU
through Stability's TFLite/LiteRT build (`optimized/tflite` in
``Stability-AI/stable-audio-3``; weights in the **ungated** HF repo
``stabilityai/stable-audio-3-optimized``, about 1.2 GB), driven by that checkout's own
script in its own virtualenv: foley adds no dependency. The model is distilled (CFG 1,
8 steps), the same posture as the ``fal_stable_audio_3`` source, and generates under the
same Stability Community licence (commercial under US $1M revenue; the cap flows from the
``LICENSE_FLAGS`` row). The T5Gemma text encoder also carries the Gemma Terms of Use.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "stable_audio_3",
    "kind": "generate",
    "display_name": "Stable Audio 3 Small-SFX (local, TFLite CPU)",
    "website": "https://github.com/Stability-AI/stable-audio-3/tree/main/optimized/tflite",
    "auth": None,  # the optimized weights are ungated: no token
    # Read by foley.requirements: probed by check_requirements, with the setup command.
    "runtime": {
        "name": "stable-audio-3-tflite",
        "purpose": "the local Stable Audio 3 Small-SFX generator (CPU, no GPU, no token)",
        "url": "https://github.com/Stability-AI/stable-audio-3/tree/main/optimized/tflite",
        "ready": "foley.sources.stable_audio_3.adapter:runtime_ready",
        "setup": "foley.sources.stable_audio_3.adapter:setup_hint",
    },
    "dependencies": [],
    "optional_dependencies": [],  # the checkout's own venv carries ai_edge_litert etc.
    "param_map": {
        "prompt": {"native_name": "--prompt", "required": True},
        "duration": {"native_name": "--seconds"},
        # Distilled: a requested prompt_influence is noted and not applied (#70).
        "prompt_influence": {
            "native_name": "--cfg",
            "coerce": {"kind": "linear", "lo": 1.0, "hi": 25.0},
            "native_default": 1.0,
        },
        "negative_prompt": {"native_name": "--negative-prompt"},
        "steps": {"native_name": "--steps"},
        "seed": {"native_name": "--seed"},
    },
    "supported_affordances": [
        "prompt",
        "duration",
        "prompt_influence",
        "negative_prompt",
        "steps",
        "seed",
    ],
    "unsupported_affordances": ["loop", "output_format"],
    "on_unsupported_param": "warn",
    "native_defaults": {
        "model_id": "stabilityai/stable-audio-3-optimized",
        "generator_version": "stable-audio-3-small-sfx-tflite",
        "dit": "sm-sfx",
        "decoder": "same-s",  # the script prompts for one when none is given
        "distilled": True,
        "num_inference_steps_default": 8,
        "duration_default_s": 10.0,
        "duration_min_s": 1.0,
        "duration_max_s": 120.0,
        "sample_rate": 44100,
        # Where the Stability checkout lives ($FOLEY_SA3_DIR overrides), and the
        # subdirectory holding the TFLite build.
        "home_default": "~/.local/share/foley/sa3",
        "home_env": "FOLEY_SA3_DIR",
        "tflite_subdir": "optimized/tflite",
        "repo_url": "https://github.com/Stability-AI/stable-audio-3",
        "timeout_s": 900,
    },
    "output": {"default_format": "wav", "returns": "bytes", "storage": "by_value"},
    "license": {
        "default_license_id": "Stability-Community",
        "cache_bytes_ok": True,
    },
    "commercial_ok": True,  # revenue-capped; enforced by keep() from the licence row
    # What a caller's ``provider_params`` (#61) may not do: the prompt, the output
    # path and the model files are foley's (and are passed after any provider flag,
    # so the script's last-wins parsing keeps them).
    "provider_params": {
        "append": {},
        "reserved": ["prompt", "out", "dit", "decoder", "model", "model_id"],
        "priced": [],
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "local inference",
        "seen": "2026-10-26",
    },
    # Vendor facts a config cannot imply (foley.capabilities_of); only documented ones.
    "capabilities": {"watermarked": False},  # local open weights: no vendor watermark
    "data_egress": "local",
}
