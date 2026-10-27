"""``SOURCE_CONFIGS`` for the fal-hosted text-to-SFX endpoints, executed through ``falaw`` (#73).

One package, several sources: each fal endpoint is its own foley source (its own params,
price and licence), and they all share one adapter class
(:class:`~foley.sources.fal.adapter.FalAdapter`) and one transport (``falaw``, the fleet's
fal client: content-addressed cache, typed errors, credentials). The registry reads
``SOURCE_CONFIGS`` (see :func:`foley.sources.registry._declared_configs`).

Stdlib-only and declarative, so discovery stays cheap. The native parameter names, ranges
and output shapes below were read from each endpoint's OpenAPI schema
(``https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>``) and checked with one
live call each on 2026-10-25. Evidence and the comparison with the other models:
``misc/docs/research/13-generation-targets-2026-10.md`` and
``17-genai-sfx-update-2026-10-25.md``.

Licences (the per-sound record is fail-closed, so each row says only what is known):

* ``fal_stable_audio_3`` (and ``fal_stable_audio_3_medium``) — Stable Audio 3 weights are under the Stability AI
  Community License (commercial use free under US $1M annual revenue, no use of outputs
  to train competing foundation models; Stability's licence gives the user the output;
  fal's terms only disclaim fal's own rights in it). Its text encoder (T5Gemma) also
  carries Gemma terms, which bind the model, not the audio it outputs. Row:
  ``Stability-Community`` (the $1M cap flows from the row and :func:`foley.keep` enforces it).
* ``fal_mmaudio`` — MMAudio weights are CC BY-NC 4.0, whatever fal's ``commercial`` label
  says. Row: ``CC-BY-NC-4.0`` with the MMAudio credit, so :func:`foley.keep` refuses it for
  commercial use and credits render the attribution.
* ``fal_elevenlabs``, ``fal_sonilo``, ``fal_mirelo`` — partner models resold by fal. Whether the vendor's
  plan rules (ElevenLabs and Sonilo free tiers are non-commercial) apply to a fal-routed
  call is not documented (Sonilo's own page now allows commercial use of API output,
  but not specifically for calls billed through fal). Row: ``fal-partner-unverified`` — usable in a derivative,
  **not** commercially, until the terms are confirmed (foley#77). Narrowing, never widening.

Pricing is fal's (``unit``/``amount_usd`` as in :func:`foley.cost.estimate_call`), with the
date it was read. ``per_second`` with no requested duration is priced at the
``duration_default_s`` the adapter sends in its place (or the endpoint's maximum, an upper
bound, when it declares none), never at zero.
"""

from __future__ import annotations

import copy

#: fal's documented pricing and model pages (read 2026-10-25).
_FAL_PRICING_SOURCE = "fal pricing API (GET /v1/models/pricing?endpoint_id=...)"
_SEEN = "2026-10-25"

#: What every fal source shares: the key, the extra, the transport, the egress class.
_COMMON = {
    "kind": "generate",
    "auth": {
        "type": "token",
        "env_var": "FAL_KEY",  # falaw also reads FAL_API_KEY
        "apply_url": "https://fal.ai/dashboard/keys",
        "extra": "fal",
    },
    "dependencies": [],
    "optional_dependencies": ["falaw"],  # foley[fal]; imported lazily in the adapter
    "on_unsupported_param": "warn",
    "output": {"returns": "url", "storage": "by_value", "audio_field": "audio"},
    "rate": {"per_min": 60},
    "data_egress": "external",
}


def _source(name: str, **spec) -> dict:
    """One fal source config: the shared block, then the endpoint's own."""
    config = {**_COMMON, "name": name, **spec}
    config["auth"] = dict(_COMMON["auth"])
    return config


SOURCE_CONFIGS = (
    _source(
        "fal_stable_audio_3",
        display_name="Stable Audio 3 Small-SFX (fal)",
        website="https://fal.ai/models/fal-ai/stable-audio-3/small/sfx/text-to-audio",
        api={"endpoint_id": "fal-ai/stable-audio-3/small/sfx/text-to-audio"},
        param_map={
            "prompt": {"native_name": "prompt", "required": True},
            "duration_s": {"native_name": "duration"},
            # Distilled (post-trained for CFG 1, 8 steps): a requested prompt_influence
            # is noted and not applied (foley.sources.base.native_adherence, #70).
            "prompt_influence": {
                "native_name": "guidance_scale",
                "coerce": {"kind": "linear", "lo": 1.0, "hi": 25.0},
                "native_default": 1.0,
            },
            "negative_prompt": {"native_name": "negative_prompt"},
            "steps": {"native_name": "num_inference_steps"},
            "seed": {"native_name": "seed"},
            "output_format": {
                "native_name": "output_format",
                "to_native_map": {
                    "wav": "wav",
                    "flac": "flac",
                    "mp3": "mp3",
                    "opus": "opus",
                },
            },
        },
        supported_affordances=[
            "prompt",
            "duration_s",
            "prompt_influence",
            "negative_prompt",
            "steps",
            "seed",
            "output_format",
        ],
        unsupported_affordances=["loop"],
        native_defaults={
            "model_id": "stable-audio-3-small-sfx",
            "generator_version": "fal-ai/stable-audio-3/small/sfx/text-to-audio",
            "output_format": "wav",
            "distilled": True,
            "duration_default_s": 10.0,  # fal's own default is 30 s, long for an effect
            "duration_min_s": 1.0,
            "duration_max_s": 120.0,
            "sample_rate": 44100,  # SAME-Small autoencoder; read live 2026-10-25 (report 17)
            # Sent on every call; prompt expansion would rewrite the prompt we record.
            "fixed_arguments": {
                "enable_prompt_expansion": False,
                "enable_safety_checker": True,
            },
            "seed_field": "seed",  # the response echoes the seed it used
        },
        license={"default_license_id": "Stability-Community", "cache_bytes_ok": True},
        commercial_ok=True,  # revenue-capped; the cap flows from the licence row
        pricing={
            "unit": "per_call",
            "amount_usd": 0.0206,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN,
        },
    ),
    _source(
        "fal_stable_audio_3_medium",
        display_name="Stable Audio 3 Medium (fal)",
        website="https://fal.ai/models/fal-ai/stable-audio-3/medium/text-to-audio",
        api={"endpoint_id": "fal-ai/stable-audio-3/medium/text-to-audio"},
        param_map=None,  # copied from Small-SFX below: the two schemas are identical
        supported_affordances=None,
        unsupported_affordances=["loop"],
        native_defaults={
            "model_id": "stable-audio-3-medium",
            "generator_version": "fal-ai/stable-audio-3/medium/text-to-audio",
            "output_format": "wav",
            "distilled": True,
            "duration_default_s": 10.0,
            "duration_min_s": 1.0,
            "duration_max_s": 380.0,
            "fixed_arguments": {
                "enable_prompt_expansion": False,
                "enable_safety_checker": True,
            },
            "seed_field": "seed",
        },
        license={"default_license_id": "Stability-Community", "cache_bytes_ok": True},
        commercial_ok=True,
        pricing={
            "unit": "per_call",
            "amount_usd": 0.0376,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN,
        },
    ),
    _source(
        "fal_mirelo",
        display_name="Mirelo SFX 2.0 (fal)",
        website="https://fal.ai/models/mirelo-ai/sfx2.0/text-to-audio",
        api={"endpoint_id": "mirelo-ai/sfx2.0/text-to-audio"},
        param_map={
            "prompt": {"native_name": "prompt", "required": True},
            "duration_s": {"native_name": "duration"},
            "negative_prompt": {"native_name": "negative_prompt"},
            "seed": {"native_name": "seed"},
            "output_format": {
                "native_name": "upload_audio_format",
                "to_native_map": {"wav": "wav", "flac": "flac", "mp3": "mp3"},
            },
        },
        supported_affordances=[
            "prompt",
            "duration_s",
            "negative_prompt",
            "seed",
            "output_format",
        ],
        unsupported_affordances=["prompt_influence", "steps", "loop"],
        native_defaults={
            "model_id": "mirelo-sfx-2.0",
            "generator_version": "mirelo-ai/sfx2.0/text-to-audio",
            "upload_audio_format": "wav",
            "duration_default_s": 10.0,  # fal's own default is 30 s
            "duration_min_s": 0.1,
            "duration_max_s": 600.0,
            # Billed per sample, and the default is 2: one clip per call here.
            "fixed_arguments": {"num_samples": 1},
            "seed_field": "seeds",  # a list, one per sample
        },
        license={
            "default_license_id": "fal-partner-unverified",
            "cache_bytes_ok": True,
        },
        commercial_ok=False,
        # $0.010/s per sample until 2026-12-13, then $0.015: priced at the later rate
        # so the estimate never under-quotes.
        pricing={
            "unit": "per_second",
            "amount_usd": 0.015,
            "source": _FAL_PRICING_SOURCE + " (0.010 until 2026-12-13)",
            "seen": _SEEN,
        },
    ),
    _source(
        "fal_elevenlabs",
        display_name="ElevenLabs Sound Effects v2 (fal)",
        website="https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2",
        api={"endpoint_id": "fal-ai/elevenlabs/sound-effects/v2"},
        param_map={
            "prompt": {"native_name": "text", "required": True},
            "duration_s": {
                "native_name": "duration_seconds"
            },  # None => the model decides
            "prompt_influence": {
                "native_name": "prompt_influence",
                "coerce": {"kind": "identity"},
                "native_default": None,
            },
            "loop": {"native_name": "loop"},
            "output_format": {
                "native_name": "output_format",
                # fal returns pcm_* as a WAV file (checked live: RIFF header, 2 ch).
                "to_native_map": {
                    "wav": "pcm_44100",
                    "mp3": "mp3_44100_128",
                    "opus": "opus_48000_128",
                },
            },
        },
        supported_affordances=[
            "prompt",
            "duration_s",
            "prompt_influence",
            "loop",
            "output_format",
        ],
        unsupported_affordances=["negative_prompt", "steps", "seed"],
        native_defaults={
            "model_id": "eleven_text_to_sound_v2",
            "generator_version": "fal-ai/elevenlabs/sound-effects/v2",
            "output_format": "pcm_44100",
            "duration_min_s": 0.5,
            "duration_max_s": 22.0,  # fal's cap (ElevenLabs' own API allows 30 s)
        },
        license={
            "default_license_id": "fal-partner-unverified",
            "cache_bytes_ok": True,
        },
        commercial_ok=False,
        pricing={
            "unit": "per_second",
            "amount_usd": 0.002,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN,
        },
    ),
    _source(
        "fal_sonilo",
        display_name="Sonilo Sound Effects v1.1 (fal)",
        website="https://fal.ai/models/sonilo/v1.1/text-to-sound-effects",
        api={"endpoint_id": "sonilo/v1.1/text-to-sound-effects"},
        param_map={
            "prompt": {"native_name": "prompt", "required": True},
            "duration_s": {"native_name": "duration"},
            "output_format": {
                "native_name": "audio_format",
                "to_native_map": {"wav": "wav", "flac": "flac", "mp3": "mp3"},
            },
        },
        # No sample-count knob: one clip per call (checked live: `audios` held one).
        supported_affordances=["prompt", "duration_s", "output_format"],
        unsupported_affordances=[
            "prompt_influence",
            "negative_prompt",
            "steps",
            "seed",
            "loop",
        ],
        native_defaults={
            "model_id": "sonilo-v1.1",
            "generator_version": "sonilo/v1.1/text-to-sound-effects",
            "audio_format": "wav",
            "duration_default_s": 8.0,
            "duration_min_s": 0.5,
            "duration_max_s": 180.0,
        },
        license={
            "default_license_id": "fal-partner-unverified",
            "cache_bytes_ok": True,
        },
        commercial_ok=False,
        pricing={
            "unit": "per_second",
            "amount_usd": 0.0018,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN,
        },
    ),
    _source(
        "fal_mmaudio",
        display_name="MMAudio v2 text-to-audio (fal; CC BY-NC weights)",
        website="https://fal.ai/models/fal-ai/mmaudio-v2/text-to-audio",
        api={"endpoint_id": "fal-ai/mmaudio-v2/text-to-audio"},
        param_map={
            "prompt": {"native_name": "prompt", "required": True},
            "duration_s": {"native_name": "duration"},
            "prompt_influence": {
                "native_name": "cfg_strength",
                "coerce": {"kind": "linear", "lo": 0.0, "hi": 20.0},
                "native_default": 4.5,
            },
            "negative_prompt": {"native_name": "negative_prompt"},
            "steps": {"native_name": "num_steps"},
            "seed": {"native_name": "seed"},
        },
        supported_affordances=[
            "prompt",
            "duration_s",
            "prompt_influence",
            "negative_prompt",
            "steps",
            "seed",
        ],
        unsupported_affordances=["loop", "output_format"],  # always MP3
        native_defaults={
            "model_id": "mmaudio-v2",
            "generator_version": "fal-ai/mmaudio-v2/text-to-audio",
            "duration_default_s": 8.0,
            "duration_min_s": 1.0,
            "duration_max_s": 30.0,
        },
        license={
            "default_license_id": "CC-BY-NC-4.0",
            "cache_bytes_ok": True,
            "attribution_text": (
                "Generated with MMAudio (Cheng et al., CC BY-NC 4.0 weights) via fal.ai"
            ),
        },
        commercial_ok=False,
        pricing={
            "unit": "per_second",
            "amount_usd": 0.001,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN,
        },
    ),
)

_SMALL = SOURCE_CONFIGS[0]
_MEDIUM = SOURCE_CONFIGS[1]
_MEDIUM["param_map"] = copy.deepcopy(_SMALL["param_map"])
_MEDIUM["supported_affordances"] = list(_SMALL["supported_affordances"])

#: What a caller's ``provider_params`` (#61) may not do on any fal endpoint: switch on
#: prompt expansion (it rewrites the prompt foley screened and records), switch off the
#: safety checker, or ask for more samples (billed per sample).
_FAL_RESERVED = ("enable_prompt_expansion", "enable_safety_checker", "num_samples")

for _config in SOURCE_CONFIGS:
    # One policy row per source (see foley.sources.base.merge_provider_params): the
    # prompt field and the fixed arguments are foley's; the duration field decides the
    # price foley estimated and reserved.
    _pm = _config["param_map"]
    _config["provider_params"] = {
        "append": {},
        "reserved": sorted(
            {
                _pm["prompt"]["native_name"],
                *_FAL_RESERVED,
                *(_config["native_defaults"].get("fixed_arguments") or {}),
            }
        ),
        "priced": [(_pm.get("duration_s") or {}).get("native_name") or "duration"],
    }

#: The fal source names, in the order above (the first is the recommended one).
FAL_SOURCES = tuple(c["name"] for c in SOURCE_CONFIGS)
