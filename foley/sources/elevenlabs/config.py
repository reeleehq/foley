"""``SOURCE_CONFIG`` for the ElevenLabs Sound Effects generator (report 02 · 07 · 10 §4.1).

Stdlib-only and declarative — imports nothing heavy, so
:func:`foley.sources.registry.discover_sources` can read it cheaply (it imports
only ``config.py``; the adapter + ``requests`` load lazily). It declares the hosted
Text-to-SFX v2 endpoint, the ``xi-api-key`` token auth, maps foley's unified
:data:`~foley.base.GENERATION_AFFORDANCES` onto the native request fields, and — as
required for every source — the **license block**, with ``cache_bytes_ok=True``
(generated audio is stored **by-value** — the opposite of Freesound).

License note (report 07, #56): what a generation may be used for depends on the
**account's plan**, which foley cannot see. A paid plan's SFX are royalty-free and
embeddable without attribution; a free plan's are non-commercial and need
attribution. So the plan is never assumed: it comes from the adapter's ``plan=`` or
``$FOLEY_ELEVENLABS_PLAN`` (``elevenlabs-paid-plan`` | ``elevenlabs-free-plan``, the
same codes as ``an``), each value being its own ``LICENSE_FLAGS`` row, and an unknown
plan refuses to generate (no paid call is made). The Prohibited-Use policy forbids
standalone redistribution of the raw SFX, which is why both rows set
``redistribute_standalone_ok=False``.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "elevenlabs",
    "kind": "generate",
    "display_name": "ElevenLabs Sound Effects (Text-to-SFX v2)",
    "website": "https://elevenlabs.io/sound-effects",
    "auth": {
        "type": "token",
        "env_var": "ELEVENLABS_API_KEY",
        "header": "xi-api-key",  # 'xi-api-key: <key>' (keeps the key out of URLs)
        "apply_url": "https://elevenlabs.io/app/settings/api-keys",
    },
    "dependencies": [],
    "optional_dependencies": ["requests"],  # foley[elevenlabs]; imported lazily
    # unified foley GENERATION_AFFORDANCES -> ElevenLabs native request fields.
    # 'in' marks whether the field is a JSON body field or a URL query param.
    "param_map": {
        "prompt": {"native_name": "text", "required": True, "in": "body"},
        "duration": {"native_name": "duration_seconds", "in": "body"},  # None => auto
        # 0..1 on both sides; None -> omitted, so the API applies its own default.
        "prompt_influence": {
            "native_name": "prompt_influence",
            "in": "body",
            "coerce": {"kind": "identity"},
            "native_default": None,
        },
        "loop": {"native_name": "loop", "in": "body"},  # v2 only (v2 is default)
        "output_format": {
            "native_name": "output_format",
            "in": "query",  # a URL query param, NOT a body field
            # coarse foley token -> concrete native enum. 'wav' is the lossless
            # pcm_48000 (raw S16LE; the adapter adds the WAV header). Whether PCM
            # needs a higher plan tier for SFX is unverified, so on a 4xx the
            # adapter retries once with fallback_on_4xx and notes it (#71).
            "to_native_map": {
                "mp3": "mp3_44100_128",
                "opus": "opus_48000_128",
                "wav": "pcm_48000",
            },
            # Retried once with the fallback only on these statuses (a plan-tier
            # refusal); any other error is raised as is.
            "fallback_on_4xx": {"pcm_48000": "mp3_44100_128"},
            "fallback_statuses": [402, 403],
            # Raw PCM layout per native enum: 16-bit little-endian. The channel count
            # is not documented for the SFX endpoint: until a live call confirms it,
            # verified=False and a clip whose layout the byte length cannot confirm
            # (no duration requested) carries a note saying mono was assumed.
            "pcm": {
                "pcm_48000": {"sample_rate": 48000, "channels": 1, "verified": False}
            },
        },
    },
    "supported_affordances": [
        "prompt",
        "duration",
        "prompt_influence",
        "loop",
        "output_format",
    ],
    # No native equivalent on this endpoint (non-deterministic, no CFG/steps).
    "unsupported_affordances": ["negative_prompt", "steps", "seed"],
    "on_unsupported_param": "warn",
    "native_defaults": {
        "model_id": "eleven_text_to_sound_v2",  # NOT a foley affordance
        "generator_version": "eleven_text_to_sound_v2",
        "output_format": "mp3_44100_128",
        "duration_min_s": 0.5,
        "duration_max_s": 30.0,
    },
    "api": {
        "base_url": "https://api.elevenlabs.io",  # overridable for data-residency
        "generate_endpoint": {"method": "POST", "path": "/v1/sound-generation"},
    },
    "output": {"default_format": "mp3", "returns": "bytes", "storage": "by_value"},
    # MANDATORY license block (foley-dev-add-source) — the SSOT seed. cache_bytes_ok
    # True => by-value storage (the generation flywheel). commercial guardrail is
    # carried by the LICENSE_FLAGS row (commercial_ok=True, no revenue cap).
    "license": {
        # No default: the licence row IS the account's plan (see the module docstring).
        "default_license_id": None,
        "plan_env_var": "FOLEY_ELEVENLABS_PLAN",
        "plans": ("elevenlabs-paid-plan", "elevenlabs-free-plan"),  # LICENSE_FLAGS rows
        # The credit line a free-plan sound carries (its row requires attribution).
        "plan_attribution": {
            "elevenlabs-free-plan": "Created with ElevenLabs (elevenlabs.io)"
        },
        "cache_bytes_ok": True,
    },
    "commercial_ok": None,  # decided by the plan's LICENSE_FLAGS row
    # falaw-style price (foley.cost.estimate_call): $0.12 per minute of audio. With the
    # duration left to the model, the estimate is the 30 s maximum (an upper bound).
    "pricing": {
        "unit": "per_second",
        "amount_usd": 0.002,
        "source": "ElevenLabs pricing via foley report 13 [4]",
        "seen": "2026-10-03",
    },
    "rate": {"per_min": 60},
    # A 'wav' request answered by the MP3 fallback replays that MP3 for a day (so an
    # account whose plan refuses PCM does not pay for every 'wav' request), then asks
    # for PCM again (so an account that moved to a tier allowing it gets PCM) (#97).
    "generations_cache": {"fallback_replay_s": 86_400},
    "data_egress": "external",  # for offline/sensitive-narration mode (report 12)
}
