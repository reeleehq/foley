"""``SOURCE_CONFIGS`` for the fal-hosted SFX endpoints (text-, video-to-audio and edits), executed through ``falaw`` (#73).

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

* ``fal_stable_audio_3`` (and ``fal_stable_audio_3_medium``, and the three Small-SFX edit
  endpoints) — Stable Audio 3 weights are under the Stability AI
  Community License (commercial use free under US $1M annual revenue, no use of outputs
  to train competing foundation models; Stability's licence gives the user the output;
  fal's terms only disclaim fal's own rights in it). Its text encoder (T5Gemma) also
  carries Gemma terms, which bind the model, not the audio it outputs. Row:
  ``Stability-Community`` (the $1M cap flows from the row and :func:`foley.keep` enforces it).
* ``fal_mmaudio`` — MMAudio weights are CC BY-NC 4.0, whatever fal's ``commercial`` label
  says. Row: ``CC-BY-NC-4.0`` with the MMAudio credit, so :func:`foley.keep` refuses it for
  commercial use and credits render the attribution.
* ``fal_elevenlabs``, ``fal_sonilo``, ``fal_mirelo`` (and its edit endpoints
  ``fal_mirelo_inpaint``, ``fal_mirelo_extend``) — partner models resold by fal. Whether the vendor's
  plan rules (ElevenLabs and Sonilo free tiers are non-commercial) apply to a fal-routed
  call is not documented (Sonilo's own page now allows commercial use of API output,
  but not specifically for calls billed through fal). Row: ``fal-partner-unverified`` — usable in a derivative,
  **not** commercially, until the terms are confirmed (foley#77). Narrowing, never widening.

Each licence block also states what the row rests on (#77): ``model-licence`` (confirmed)
for open weights, ``vendor-tos`` (unverified) for the partner rows, never fal's own
``commercial`` label; Mirelo and ElevenLabs say the vendor reuses its output, and Sonilo
reports its own watermark per clip (``native_defaults['watermark_field']``).

The edit endpoints (#162: ``fal_stable_audio_3_audio_to_audio``, ``_inpaint``, ``_extend``)
declare ``modes=['edit']`` and their ``edit_op`` (a :data:`foley.base.EDIT_OPS` name), so
only a call with a source clip (``audio=``, see :func:`foley.edit`) reaches them, and none
joins a text-to-audio or video-to-audio order. Their Stable Audio 3 row is the
generator's: the edit mode narrows each edit's rights to its source's
(:func:`foley.sources.edit.edit_lineage`). Mirelo SFX 1.6's inpaint and extend
endpoints (#215: ``fal_mirelo_inpaint``, ``fal_mirelo_extend``) are those ops'
fallbacks, registered after them so an unnamed edit keeps Stable Audio 3; their
schema limits (the clip's, a window's and the output's lengths) are their
``edit_limits``, and they are priced per second of the sound they make. fal
deprecates both on 2026-12-15, with no SFX 2.0 edit endpoint to move to (yet).

Pricing is fal's (``unit``/``amount_usd`` as in :func:`foley.cost.estimate_call`), with the
date it was read. ``per_second`` with no requested duration is priced at the
``duration_default_s`` the adapter sends in its place (or the endpoint's maximum, an upper
bound, when it declares none), never at zero.
"""

from __future__ import annotations

import copy

from ...base import EDIT_OPS
from ..elevenlabs.config import MP3_BY_RATE as _EL_MP3_BY_RATE
from ..elevenlabs.config import PCM_RATES as _EL_PCM_RATES
from ..media import MEDIA_INPUTS

#: ElevenLabs formats the direct API offers and fal's endpoint does not (report 17 §3).
_FAL_EL_LACKS = frozenset({"pcm_32000", "mp3_24000_48"})

#: fal's documented pricing and model pages (read 2026-10-25).
_FAL_PRICING_SOURCE = "fal pricing API (GET /v1/models/pricing?endpoint_id=...)"
_SEEN = "2026-10-25"
#: The video-to-audio endpoints' prices, read off their fal model pages (#74).
_FAL_V2A_PRICING_SOURCE = "fal model page (pricing note)"
_SEEN_V2A = "2026-10-27"
#: The Stable Audio 3 edit endpoints' schemas and prices (#162).
_SEEN_EDIT = "2026-10-27"

#: What a licence row rests on (#77). A model's own licence binds its output whoever
#: hosts it; a partner model's row is foley's reading of the vendor's terms, which are
#: not documented to reach a fal-routed call. fal's own ``commercial`` label is never
#: the basis (an aggregator's label is not the model's licence).
_MODEL_LICENCE = {
    "license_basis": "model-licence",
    "license_basis_confidence": "confirmed",
}
#: A model licence whose reach is in doubt (report 13 §2B, §2D): MMAudio's CC BY-NC
#: weights (whether fal holds a commercial licence from its authors is undocumented)
#: and ThinkSound (HF tag Apache-2.0, README research only). foley keeps the stricter
#: reading either way.
_DOUBTED_MODEL_LICENCE = {**_MODEL_LICENCE, "license_basis_confidence": "unverified"}
_PARTNER_TERMS = {
    "default_license_id": "fal-partner-unverified",
    "cache_bytes_ok": True,
    "license_basis": "vendor-tos",
    "license_basis_confidence": "unverified",
}
#: Mirelo's terms (report 13 §2A): a training licence on input and output (§7.4) and
#: watermarked free-plan output (§7.5).
_MIRELO_TERMS = {
    **_PARTNER_TERMS,
    "vendor_trains_on_output": True,
    # ... and on input: an edit's source clip goes into it, so the edit gate refuses a
    # source whose rights forbid AI training (foley.licensing.vendor_training_refusal).
    "vendor_trains_on_input": True,
    "terms_notes": [
        "Mirelo's terms (§7.4) give Mirelo a training licence on your input and "
        "output; only a paid direct Mirelo account can opt out, which a fal-routed "
        "call cannot show."
    ],
}
_MIRELO_WATERMARK = (
    "Mirelo's terms (§7.5): free-plan output may carry a watermark; whether a "
    "fal-routed call does is unverified."
)
#: ElevenLabs' sound-effects terms (report 07 §5.1): outputs are sublicensed to other
#: users unless the account disables it, and here the account is fal's.
_FAL_ELEVENLABS_TERMS = {
    **_PARTNER_TERMS,
    "vendor_trains_on_output": True,
    "terms_notes": [
        "ElevenLabs' sound-effects terms sublicense outputs to other ElevenLabs users "
        "unless the account disables it; for a fal-routed call that account is "
        "fal's, and its setting is unverified."
    ],
}
_SONILO_WATERMARK = (
    "Sonilo documents an inaudible provenance watermark, reported per clip in a "
    "'watermark' response field when present (not in fal's schema as read "
    "2026-11-02, so usually unreported)."
)

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
            # fal's LLM prompt rewrite (#75); off unless asked (fixed_arguments below),
            # and the prompt the endpoint used is recorded beside the one sent.
            "expand_prompt": {"native_name": "enable_prompt_expansion"},
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
            "expand_prompt",
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
            # Sent on every call: prompt expansion only when expand_prompt=True asks.
            "fixed_arguments": {
                "enable_prompt_expansion": False,
                "enable_safety_checker": True,
            },
            "seed_field": "seed",  # the response echoes the seed it used
        },
        license={
            "default_license_id": "Stability-Community",
            "cache_bytes_ok": True,
            **_MODEL_LICENCE,
        },
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
        license={
            "default_license_id": "Stability-Community",
            "cache_bytes_ok": True,
            **_MODEL_LICENCE,
        },
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
            # Billed per sample, and the default is 2: one clip per call here, unless
            # foley.variations asks for several (the batch knob below, #210).
            "fixed_arguments": {"num_samples": 1},
            # Per-sample seeds are reported (the "seeds" list), so a seeded request
            # batches too: each take is keyed by the seed it reports.
            "batch": {"native_name": "num_samples", "max": 4, "seeds": "reported"},
            "seed_field": "seeds",  # a list, one per sample ("each sample's seed")
            "seed_limit": 2**63,  # the schema's seed: a signed 64-bit integer
        },
        license=copy.deepcopy(_MIRELO_TERMS),
        capabilities={"watermark_statement": _MIRELO_WATERMARK},
        commercial_ok=False,
        # $0.010/s per sample until 2026-12-13, then $0.015: priced at the later rate
        # so the estimate never under-quotes.
        pricing={
            "unit": "per_second",
            "per_sample": True,  # billed per sample (foley.cost.for_samples)
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
                # fal's enum (report 17 §3): the direct API's, less _FAL_EL_LACKS.
                "by": "sample_rate",
                "to_native_by_rate": {
                    "wav": {
                        r: f"pcm_{r}"
                        for r in _EL_PCM_RATES
                        if f"pcm_{r}" not in _FAL_EL_LACKS
                    },
                    "mp3": {
                        r: f
                        for r, f in _EL_MP3_BY_RATE.items()
                        if f not in _FAL_EL_LACKS
                    },
                    "opus": {48000: "opus_48000_128"},
                },
            },
        },
        supported_affordances=[
            "prompt",
            "duration_s",
            "prompt_influence",
            "loop",
            "output_format",
            "sample_rate",
        ],
        unsupported_affordances=["negative_prompt", "steps", "seed"],
        native_defaults={
            "model_id": "eleven_text_to_sound_v2",
            "generator_version": "fal-ai/elevenlabs/sound-effects/v2",
            "output_format": "pcm_44100",
            "duration_min_s": 0.5,
            "duration_max_s": 22.0,  # fal's cap (ElevenLabs' own API allows 30 s)
        },
        license=copy.deepcopy(_FAL_ELEVENLABS_TERMS),
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
            # The response's own watermark report (#77; report 13 §2A).
            "watermark_field": "watermark",
        },
        license=copy.deepcopy(_PARTNER_TERMS),
        capabilities={"watermark_statement": _SONILO_WATERMARK},
        commercial_ok=False,
        pricing={
            "unit": "per_second",
            "per_sample": True,  # billed per sample (foley.cost.for_samples)
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
            **_DOUBTED_MODEL_LICENCE,
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
    # -- video-to-audio (#74): modes=['v2a'], so only a call with video= reaches them --
    _source(
        "fal_mirelo_v2a",
        display_name="Mirelo SFX 2.0 video-to-audio (fal)",
        website="https://fal.ai/models/mirelo-ai/sfx2.0/video-to-audio",
        api={"endpoint_id": "mirelo-ai/sfx2.0/video-to-audio"},
        modes=["v2a"],
        param_map={
            "prompt": {"native_name": "text_prompt"},  # optional: the picture leads
            "video": {"native_name": "video_url"},
            "keep_source_audio": {"native_name": "preserve_speech"},
            "duration_s": {"native_name": "duration"},  # clamped to the video's length
            "negative_prompt": {"native_name": "negative_prompt"},
            "seed": {"native_name": "seed"},
            "output_format": {
                "native_name": "upload_audio_format",
                "to_native_map": {"wav": "wav", "flac": "flac", "mp3": "mp3"},
            },
        },
        supported_affordances=[
            "prompt",
            "video",
            "keep_source_audio",
            "duration_s",
            "negative_prompt",
            "seed",
            "output_format",
        ],
        unsupported_affordances=["prompt_influence", "steps", "loop"],
        native_defaults={
            "model_id": "mirelo-sfx-2.0",
            "generator_version": "mirelo-ai/sfx2.0/video-to-audio",
            "upload_audio_format": "wav",
            "duration_default_s": 10.0,  # fal's own default; never past the video
            "duration_min_s": 1.0,
            "duration_max_s": 600.0,
            # One clip per call (billed per sample), and no separated speech track;
            # foley.variations asks for several through the batch knob (#210). The
            # response reports no seeds: a single take records the seed sent, a
            # batch's takes record none (and say so).
            "fixed_arguments": {"num_samples": 1, "return_speech": False},
            # No per-sample seeds: only an unseeded request batches (a seeded one's
            # takes could not be keyed by their seeds).
            "batch": {"native_name": "num_samples", "max": 4},
            # The schema takes up to 2**64 - 1; the narrower int64 range of the
            # text-to-audio endpoint is kept for both.
            "seed_limit": 2**63,
        },
        license=copy.deepcopy(_MIRELO_TERMS),
        capabilities={"watermark_statement": _MIRELO_WATERMARK},
        commercial_ok=False,
        # $0.010/s per sample until 2026-12-13, then $0.015: priced at the later rate.
        pricing={
            "unit": "per_second",
            "per_sample": True,  # billed per sample (foley.cost.for_samples)
            "amount_usd": 0.015,
            "source": _FAL_V2A_PRICING_SOURCE + " (0.010 until 2026-12-13)",
            "seen": _SEEN_V2A,
        },
    ),
    _source(
        "fal_sonilo_v2a",
        display_name="Sonilo v1.1 video-to-sound-effects (fal)",
        website="https://fal.ai/models/sonilo/v1.1/video-to-sound-effects",
        api={"endpoint_id": "sonilo/v1.1/video-to-sound-effects"},
        modes=["v2a"],
        param_map={
            "prompt": {"native_name": "prompt"},  # optional: steers every scene
            "video": {"native_name": "video_url"},
            "keep_source_audio": {"native_name": "keep_speech_vocal"},
            "output_format": {
                "native_name": "audio_format",
                "to_native_map": {"wav": "wav", "flac": "flac", "mp3": "mp3"},
            },
        },
        # The length is the video's: no duration knob; no seed.
        supported_affordances=["prompt", "video", "keep_source_audio", "output_format"],
        unsupported_affordances=[
            "duration_s",
            "prompt_influence",
            "negative_prompt",
            "steps",
            "seed",
            "loop",
        ],
        native_defaults={
            "model_id": "sonilo-v1.1",
            "generator_version": "sonilo/v1.1/video-to-sound-effects",
            "audio_format": "wav",
            "watermark_field": "watermark",  # read when the response carries it (#77)
        },
        license=copy.deepcopy(_PARTNER_TERMS),
        capabilities={"watermark_statement": _SONILO_WATERMARK},
        commercial_ok=False,
        pricing={
            "unit": "per_second",
            "per_sample": True,  # billed per sample (foley.cost.for_samples)
            "amount_usd": 0.009,  # per second of output (the video's length), per sample
            "seconds_from": "video",
            "source": _FAL_V2A_PRICING_SOURCE,
            "seen": _SEEN_V2A,
        },
    ),
    # -- non-commercial video-to-audio (#74): the licence fence. Named only (not in the
    # V2A order); each answers a video with the sound muxed in, and foley keeps the
    # audio track (output container 'video', foley.sources.video.audio_track).
    _source(
        "fal_mmaudio_v2a",
        display_name="MMAudio v2 video-to-audio (fal; CC BY-NC weights)",
        website="https://fal.ai/models/fal-ai/mmaudio-v2",
        api={"endpoint_id": "fal-ai/mmaudio-v2"},
        modes=["v2a"],
        param_map={
            "prompt": {"native_name": "prompt", "required": True},
            "video": {"native_name": "video_url"},
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
            "video",
            "duration_s",
            "prompt_influence",
            "negative_prompt",
            "steps",
            "seed",
        ],
        # mask_away_clip is not keeping the source audio: no keep_source_audio here.
        unsupported_affordances=["loop", "output_format", "keep_source_audio"],
        native_defaults={
            "model_id": "mmaudio-v2",
            "generator_version": "fal-ai/mmaudio-v2",
            "duration_default_s": 8.0,
            "duration_min_s": 1.0,
            "duration_max_s": 30.0,
        },
        output={**_COMMON["output"], "audio_field": "video", "container": "video"},
        license={
            "default_license_id": "CC-BY-NC-4.0",
            "cache_bytes_ok": True,
            **_DOUBTED_MODEL_LICENCE,
            "attribution_text": (
                "Generated with MMAudio (Cheng et al., CC BY-NC 4.0 weights) via fal.ai"
            ),
        },
        commercial_ok=False,
        pricing={
            "unit": "per_second",
            "amount_usd": 0.001,
            "source": _FAL_V2A_PRICING_SOURCE,
            "seen": _SEEN_V2A,
        },
    ),
    _source(
        "fal_thinksound",
        display_name="ThinkSound video-to-audio (fal; research only)",
        website="https://fal.ai/models/fal-ai/thinksound",
        api={"endpoint_id": "fal-ai/thinksound"},
        modes=["v2a"],
        param_map={
            "prompt": {"native_name": "prompt"},  # optional: drawn from the video
            "video": {"native_name": "video_url"},
            "prompt_influence": {
                "native_name": "cfg_scale",
                "coerce": {"kind": "linear", "lo": 1.0, "hi": 20.0},
                "native_default": 5.0,
            },
            "steps": {"native_name": "num_inference_steps"},
            "seed": {"native_name": "seed"},
        },
        supported_affordances=["prompt", "video", "prompt_influence", "steps", "seed"],
        unsupported_affordances=[
            "duration_s",
            "negative_prompt",
            "loop",
            "output_format",
            "keep_source_audio",
        ],
        native_defaults={
            "model_id": "thinksound",
            "generator_version": "fal-ai/thinksound",
            "fixed_arguments": {"enable_safety_checker": True},
        },
        output={**_COMMON["output"], "audio_field": "video", "container": "video"},
        license={
            "default_license_id": "research-only",
            "cache_bytes_ok": True,
            **_DOUBTED_MODEL_LICENCE,
        },
        commercial_ok=False,
        # Billed per *compute* second: not knowable before the call, so the estimate is
        # unknown (an unknown cost needs approval); the actual is priced from the run
        # time fal reports (#186), unknown when it reports none.
        pricing={
            "unit": "per_compute_second",
            "amount_usd": 0.001,
            # fal's run metric the actual cost is priced from (#186; falaw#125).
            "compute_seconds_field": "inference_time",
            "source": _FAL_V2A_PRICING_SOURCE,
            "seen": _SEEN_V2A,
        },
    ),
    _source(
        "fal_hunyuan_foley",
        display_name="HunyuanVideo-Foley (fal; not valid in the EU, UK or KR)",
        website="https://fal.ai/models/fal-ai/hunyuan-video-foley",
        api={"endpoint_id": "fal-ai/hunyuan-video-foley"},
        modes=["v2a"],
        param_map={
            "prompt": {"native_name": "text_prompt", "required": True},
            "video": {"native_name": "video_url"},
            "prompt_influence": {
                "native_name": "guidance_scale",
                "coerce": {"kind": "linear", "lo": 1.0, "hi": 10.0},
                "native_default": 4.5,
            },
            "negative_prompt": {"native_name": "negative_prompt"},
            "steps": {"native_name": "num_inference_steps"},
            "seed": {"native_name": "seed"},
        },
        supported_affordances=[
            "prompt",
            "video",
            "prompt_influence",
            "negative_prompt",
            "steps",
            "seed",
        ],
        unsupported_affordances=[
            "duration_s",
            "loop",
            "output_format",
            "keep_source_audio",
        ],
        native_defaults={
            "model_id": "hunyuan-video-foley",
            "generator_version": "fal-ai/hunyuan-video-foley",
            "fixed_arguments": {"enable_safety_checker": True},
        },
        output={**_COMMON["output"], "audio_field": "video", "container": "video"},
        license={
            "default_license_id": "Tencent-Hunyuan-Community",
            "cache_bytes_ok": True,
            **_MODEL_LICENCE,
        },
        commercial_ok=False,
        # $0.10 per 10 s of video: billed in whole 10 s blocks (an assumption from the
        # wording, unverified by a live call; it can only over-quote a budget).
        pricing={
            "unit": "per_second",
            "amount_usd": 0.01,
            "seconds_from": "video",
            "billing_increment_s": 10,
            "source": _FAL_V2A_PRICING_SOURCE,
            "seen": _SEEN_V2A,
        },
    ),
)

_SMALL = SOURCE_CONFIGS[0]
_MEDIUM = SOURCE_CONFIGS[1]
_MEDIUM["param_map"] = copy.deepcopy(_SMALL["param_map"])
_MEDIUM["supported_affordances"] = list(_SMALL["supported_affordances"])

#: What the three Small-SFX edit endpoints share with each other: the source clip, the
#: sampler, the seed it echoes, the output format (read off their OpenAPI schemas).
_SA3_EDIT_PARAM_MAP = {
    "prompt": {"native_name": "prompt", "required": True},
    "audio": {"native_name": "audio_url"},
    # Distilled like the text-to-audio endpoint: a requested adherence is noted only.
    "prompt_influence": {
        "native_name": "guidance_scale",
        "coerce": {"kind": "linear", "lo": 1.0, "hi": 25.0},
        "native_default": 1.0,
    },
    "negative_prompt": {"native_name": "negative_prompt"},
    "steps": {"native_name": "num_inference_steps"},
    "seed": {"native_name": "seed"},
    "expand_prompt": {"native_name": "enable_prompt_expansion"},
    "output_format": copy.deepcopy(_SMALL["param_map"]["output_format"]),
}
_SA3_EDIT_AFFORDANCES = [
    "prompt",
    "audio",
    "prompt_influence",
    "negative_prompt",
    "steps",
    "seed",
    "output_format",
    "expand_prompt",
]


def _sa3_edit(
    name: str,
    op: str,
    endpoint: str,
    *,
    price: float,
    params: dict,
    native_defaults=None,
    unsupported=("loop",),
) -> dict:
    """One Stable Audio 3 Small-SFX edit source (#162): the text-to-audio row's licence,
    the shared edit schema plus the op's own ``params`` (affordance -> native spec)."""
    return _source(
        name,
        display_name=f"Stable Audio 3 Small-SFX {op.replace('_', '-')} (fal)",
        website=f"https://fal.ai/models/{endpoint}",
        api={"endpoint_id": endpoint},
        modes=["edit"],
        edit_op=op,
        param_map={**copy.deepcopy(_SA3_EDIT_PARAM_MAP), **params},
        supported_affordances=[*_SA3_EDIT_AFFORDANCES, *params],
        unsupported_affordances=list(unsupported),
        native_defaults={
            "model_id": "stable-audio-3-small-sfx",
            "generator_version": endpoint,
            "output_format": "wav",
            "distilled": True,
            "sample_rate": 44100,
            "fixed_arguments": {
                "enable_prompt_expansion": False,
                "enable_safety_checker": True,
            },
            "seed_field": "seed",
            **(native_defaults or {}),
        },
        license={
            "default_license_id": "Stability-Community",
            "cache_bytes_ok": True,
            **_MODEL_LICENCE,
        },
        commercial_ok=True,  # revenue-capped; the edit mode narrows to the source's rights
        pricing={
            "unit": "per_call",
            "amount_usd": price,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN_EDIT,
        },
    )


#: The Mirelo SFX 1.6 edit endpoints' schemas and prices (#215).
_SEEN_MIRELO_EDIT = "2026-11-02"
#: Mirelo's edit endpoints have no ``seed`` echo and answer a list of samples; one
#: sample per call (``num_samples`` defaults to 2, likely billed per sample).
_MIRELO_EDIT_PARAM_MAP = {
    "prompt": {"native_name": "text_prompt"},  # optional: the source clip leads
    "audio": {"native_name": "audio_url"},  # http(s) or a data URI of up to 8 MB
    "seed": {"native_name": "seed"},
    "output_format": copy.deepcopy(  # fal_mirelo's (no aac)
        next(c for c in SOURCE_CONFIGS if c["name"] == "fal_mirelo")["param_map"][
            "output_format"
        ]
    ),
}


def _mirelo_edit(
    name: str,
    op: str,
    endpoint: str,
    *,
    params: dict,
    edit_limits: dict,
    unsupported: tuple,
    fixed_arguments=None,
) -> dict:
    """One Mirelo SFX 1.6 edit source (#215): Mirelo's partner row and watermark
    statement (as ``fal_mirelo``), the shared schema plus the op's own ``params``."""
    return _source(
        name,
        display_name=f"Mirelo SFX 1.6 {op.replace('_', '-')} (fal)",
        website=f"https://fal.ai/models/{endpoint}",
        api={"endpoint_id": endpoint},
        # fal deprecates both endpoints on 2026-12-15 ("Migrate to SFX 2.0"), and SFX
        # 2.0 has no edit endpoint (its openapi 404s, read 2026-11-02): after it, no
        # default, suggestion or estimate offers them (foley.sources.generate.edit_backends).
        deprecated_after="2026-12-15",
        modes=["edit"],
        edit_op=op,
        param_map={**copy.deepcopy(_MIRELO_EDIT_PARAM_MAP), **params},
        supported_affordances=[*_MIRELO_EDIT_PARAM_MAP, *params],
        unsupported_affordances=list(unsupported),
        # The schema's own limits, checked before anything is paid for
        # (foley.base.check_edit_args): the clip's, a window's and the output's lengths.
        edit_limits=edit_limits,
        native_defaults={
            "model_id": "mirelo-sfx-1.6",
            "generator_version": endpoint,
            "upload_audio_format": "wav",
            "fixed_arguments": {"num_samples": 1, **(fixed_arguments or {})},
            # The schema takes up to 2**64 - 1; the int64 range of fal_mirelo is kept.
            "seed_limit": 2**63,
        },
        license=copy.deepcopy(_MIRELO_TERMS),
        capabilities={"watermark_statement": _MIRELO_WATERMARK},
        commercial_ok=False,
        # $0.01 per second (fal's billing unit "seconds"). Which seconds (the output's,
        # or only the regenerated or added part) and whether per sample is not stated:
        # priced by the output's length per sample, an upper bound (unverified by a
        # live call; it can only over-quote a budget).
        pricing={
            "unit": "per_second",
            "per_sample": True,
            "amount_usd": 0.01,
            "source": _FAL_PRICING_SOURCE,
            "seen": _SEEN_MIRELO_EDIT,
        },
    )


#: The edit sources (#162): named, or picked by foley.edit from their edit_op (the
#: first registered with its key set: the Stable Audio 3 ones, so Mirelo's are the
#: inpaint and extend fallbacks, #215).
EDIT_SOURCE_CONFIGS = (
    _sa3_edit(
        "fal_stable_audio_3_audio_to_audio",
        "audio_to_audio",
        "fal-ai/stable-audio-3/small/sfx/audio-to-audio",
        price=0.024,
        params={
            "duration_s": {
                "native_name": "duration"
            },  # the source's length when unasked
            # how far from the source: 1.0 is pure generation (fal's default 0.9)
            "strength": {"native_name": "init_noise_level"},
        },
        native_defaults={
            "duration_default_s": 10.0,  # fal's own default is 30 s
            "duration_min_s": 1.0,
            "duration_max_s": 120.0,
        },
    ),
    _sa3_edit(
        "fal_stable_audio_3_inpaint",
        "inpaint",
        "fal-ai/stable-audio-3/small/sfx/audio-inpainting",
        price=0.0259,
        params={
            "inpaint_start_s": {"native_name": "mask_start_seconds"},
            "inpaint_end_s": {"native_name": "mask_end_seconds"},
        },
        unsupported=("loop", "duration_s"),  # the length is the source's
    ),
    _sa3_edit(
        "fal_stable_audio_3_extend",
        "extend",
        "fal-ai/stable-audio-3/small/sfx/audio-outpainting",
        price=0.0271,
        params={  # fal's schema bounds each side to 0..120 s
            "extend_before_s": {"native_name": "extend_seconds_before", "max": 120.0},
            "extend_after_s": {"native_name": "extend_seconds_after", "max": 120.0},
        },
        unsupported=("loop", "duration_s"),  # the source's length plus the extension
    ),
    _mirelo_edit(
        "fal_mirelo_inpaint",
        "inpaint",
        "mirelo-ai/sfx1.6/inpaint-audio",
        params={  # one nested "segment": {start_s, end_s} (AudioSegmentSpec)
            "inpaint_start_s": {
                "native_name": "segment.start_s",
                "min": 1.0,
                "max": 9.0,
            },
            "inpaint_end_s": {"native_name": "segment.end_s", "min": 2.0, "max": 10.0},
        },
        # a source of 10 s at most; a window of 1 to 8 s (1 s <= start < end <= 10 s)
        edit_limits={"clip_s": (None, 10.0), "span_s": (1.0, 8.0)},
        unsupported=(
            "duration_s",  # the length is the source's
            "prompt_influence",
            "negative_prompt",
            "steps",
            "loop",
        ),
    ),
    _mirelo_edit(
        "fal_mirelo_extend",
        "extend",
        "mirelo-ai/sfx1.6/extend-audio",
        params={
            "extend_after_s": {
                "native_name": "append_duration",
                "min": 1.0,
                "max": 57.0,
            },
            # extend, then stitch the end back to the start: a seamless loop tile
            "loop": {"native_name": "ambience"},
        },
        # a source of 3 to 59 s; the output (source + extension) of 60 s at most
        edit_limits={"clip_s": (3.0, 59.0), "output_s": (None, 60.0)},
        unsupported=(
            "extend_before_s",  # it only appends
            "duration_s",  # the source's length plus the extension
            "prompt_influence",
            "negative_prompt",
            "steps",
        ),
        # a looped tile doubled in length would bill twice the seconds foley priced
        fixed_arguments={"double_output": False},
    ),
)
SOURCE_CONFIGS = (*SOURCE_CONFIGS, *EDIT_SOURCE_CONFIGS)

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
                # a media input is keyed by its content: a provider param may not swap it
                *(_pm[m]["native_name"] for m in MEDIA_INPUTS if m in _pm),
                *_FAL_RESERVED,
                *(_config["native_defaults"].get("fixed_arguments") or {}),
                # a nested field (Mirelo's inpaint segment) is the edit's window, which
                # its lineage records: a provider param may not replace it
                *(
                    spec["native_name"].split(".")[0]
                    for spec in _pm.values()
                    if "." in spec.get("native_name", "")
                ),
            }
        ),
        "priced": [
            (_pm.get("duration_s") or {}).get("native_name") or "duration",
            # what an edit adds to the output's length, which a per-second edit bills
            *(
                _pm[p]["native_name"]
                for p in getattr(EDIT_OPS.get(_config.get("edit_op")), "adds", ())
                if p in _pm and _config["pricing"]["unit"] == "per_second"
            ),
        ],
    }

#: The fal source names, in the order above (the first is the recommended one).
FAL_SOURCES = tuple(c["name"] for c in SOURCE_CONFIGS)
