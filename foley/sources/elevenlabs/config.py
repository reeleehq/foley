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
        # The rest of the fleet (an, voxy) also reads ELEVEN_API_KEY for this provider.
        "env_var_aliases": ("ELEVEN_API_KEY",),
        "header": "xi-api-key",  # 'xi-api-key: <key>' (keeps the key out of URLs)
        "apply_url": "https://elevenlabs.io/app/settings/api-keys",
    },
    "dependencies": [],
    "optional_dependencies": ["requests"],  # foley[elevenlabs]; imported lazily
    # unified foley GENERATION_AFFORDANCES -> ElevenLabs native request fields.
    # 'in' marks whether the field is a JSON body field or a URL query param.
    "param_map": {
        "prompt": {"native_name": "text", "required": True, "in": "body"},
        "duration_s": {"native_name": "duration_seconds", "in": "body"},  # None => auto
        # Pin the model (eleven_text_to_sound_v2 | _v3); None => native_defaults' one.
        "model": {"native_name": "model_id", "in": "body"},
        # 0..1 on both sides; None -> omitted, so the API applies its own default.
        "prompt_influence": {
            "native_name": "prompt_influence",
            "in": "body",
            "coerce": {"kind": "identity"},
            "native_default": None,
        },
        "loop": {"native_name": "loop", "in": "body"},  # v2 only (v2 is default)
        # The rate is part of the native format enum (#75): see to_native_by_rate.
        "sample_rate": {"via": "output_format"},
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
            # A requested sample_rate picks the enum (the documented direct-API set,
            # report 17 §3); a rate missing here keeps to_native_map's, with a note.
            "to_native_by_rate": {
                "wav": {
                    r: f"pcm_{r}" for r in (8000, 16000, 22050, 24000, 44100, 48000)
                },
                "mp3": {
                    22050: "mp3_22050_32",
                    24000: "mp3_24000_48",
                    44100: "mp3_44100_128",
                },
                "opus": {48000: "opus_48000_128"},
            },
            # Retried once with the fallback only for a plan-tier refusal of the
            # format; any other error is raised as is (#100). ElevenLabs' documented
            # error body is {"detail": {"type", "code", "message", "status", ...}}: a
            # tier gate is a 403 authorization_error, code 'subscription_required'
            # (reported in the field as legacy status 'output_format_not_allowed',
            # with a message naming the format: "Requested output format pcm_44100
            # ... is only allowed for Pro tier and above"). A 402 is payment_required
            # (out of credits), which MP3 would not fix. Live confirmation: #95.
            "fallback_on_4xx": {
                f"pcm_{r}": "mp3_44100_128"
                for r in (8000, 16000, 22050, 24000, 44100, 48000)
            },
            "fallback_statuses": [403],
            "fallback_detail_codes": [
                "subscription_required",
                "output_format_not_allowed",
            ],
            # Raw PCM layout per native enum: 16-bit little-endian, headerless
            # (content-type audio/pcm). Stereo, verified live 2026-10-26 (#95): a
            # 1.0 s request returned 192,000 bytes (48,000 x 2 ch x 2 B), and five
            # studio clips of 1.5-8 s all implied 2 ch; a paid plan was not refused
            # PCM. The byte-length check still corrects a clip that disagrees.
            # The other rates are assumed stereo like pcm_48000 (not verified live).
            "pcm": {
                "pcm_48000": {"sample_rate": 48000, "channels": 2, "verified": True},
                **{
                    f"pcm_{r}": {"sample_rate": r, "channels": 2, "verified": False}
                    for r in (8000, 16000, 22050, 24000, 44100)
                },
            },
        },
    },
    "supported_affordances": [
        "prompt",
        "duration_s",
        "model",
        "prompt_influence",
        "loop",
        "output_format",
        "sample_rate",
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
        # The response header carrying the credits the call was charged (seen live
        # 2026-10-26: 10 credits for a 1.0 s clip); recorded as a note per clip.
        "credits_header": "character-cost",
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
    # falaw-style price (foley.cost.estimate_call): $0.12 per minute of audio, the API
    # pay-as-you-go rate, which is also the overage rate on every paid plan; a paid
    # plan's monthly allowance is consumed first, so the marginal cost is 0 until it
    # runs out and this is an upper bound. Same per-second price as the fal route
    # (fal_elevenlabs), with the plan's licence instead of an unverified one, which is
    # why it comes first in foley.sources.generate.DEFAULT_GENERATE_ORDER. With the
    # duration left to the model, the estimate is the 30 s maximum (an upper bound).
    # What a caller's ``provider_params`` (#61) may not do: the prompt is what foley
    # screened and records; duration and model decide the price foley reserved.
    "provider_params": {
        "append": {},
        "reserved": ["text"],
        "priced": ["duration_seconds", "model_id"],
    },
    "pricing": {
        "unit": "per_second",
        "amount_usd": 0.002,
        "source": "https://elevenlabs.io/pricing/api (Sound Effects: $0.12 per minute)",
        "seen": "2026-10-26",
    },
    "rate": {"per_min": 60},
    # A 'wav' request answered by the MP3 fallback replays that MP3 for a day (so an
    # account whose plan refuses PCM does not pay for every 'wav' request), then asks
    # for PCM again (so an account that moved to a tier allowing it gets PCM) (#97).
    "generations_cache": {"fallback_replay_s": 86_400},
    "data_egress": "external",  # for offline/sensitive-narration mode (report 12)
}
