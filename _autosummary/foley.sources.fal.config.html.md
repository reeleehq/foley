# foley.sources.fal.config

`SOURCE_CONFIGS` for the fal-hosted SFX endpoints (text-, video-to-audio and edits), executed through `falaw` (#73).

One package, several sources: each fal endpoint is its own foley source (its own params,
price and licence), and they all share one adapter class
([`FalAdapter`](foley.sources.fal.adapter.html.md#foley.sources.fal.adapter.FalAdapter)) and one transport (`falaw`, the fleet’s
fal client: content-addressed cache, typed errors, credentials). The registry reads
`SOURCE_CONFIGS` (see `foley.sources.registry._declared_configs()`).

Stdlib-only and declarative, so discovery stays cheap. The native parameter names, ranges
and output shapes below were read from each endpoint’s OpenAPI schema
(`https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>`) and checked with one
live call each on 2026-10-25. Evidence and the comparison with the other models:
`misc/docs/research/13-generation-targets-2026-10.md` and
`17-genai-sfx-update-2026-10-25.md`.

Licences (the per-sound record is fail-closed, so each row says only what is known):

* `fal_stable_audio_3` (and `fal_stable_audio_3_medium`, and the three Small-SFX edit
  endpoints) — Stable Audio 3 weights are under the Stability AI
  Community License (commercial use free under US $1M annual revenue, no use of outputs
  to train competing foundation models; Stability’s licence gives the user the output;
  fal’s terms only disclaim fal’s own rights in it). Its text encoder (T5Gemma) also
  carries Gemma terms, which bind the model, not the audio it outputs. Row:
  `Stability-Community` (the $1M cap flows from the row and [`foley.keep()`](foley.html.md#foley.keep) enforces it).
* `fal_mmaudio` — MMAudio weights are CC BY-NC 4.0, whatever fal’s `commercial` label
  says. Row: `CC-BY-NC-4.0` with the MMAudio credit, so [`foley.keep()`](foley.html.md#foley.keep) refuses it for
  commercial use and credits render the attribution.
* `fal_elevenlabs`, `fal_sonilo`, `fal_mirelo` — partner models resold by fal. Whether the vendor’s
  plan rules (ElevenLabs and Sonilo free tiers are non-commercial) apply to a fal-routed
  call is not documented (Sonilo’s own page now allows commercial use of API output,
  but not specifically for calls billed through fal). Row: `fal-partner-unverified` — usable in a derivative,
  **not** commercially, until the terms are confirmed (foley#77). Narrowing, never widening.

The edit endpoints (#162: `fal_stable_audio_3_audio_to_audio`, `_inpaint`, `_extend`)
declare `modes=['edit']` and their `edit_op` (a [`foley.base.EDIT_OPS`](foley.base.html.md#foley.base.EDIT_OPS) name), so
only a call with a source clip (`audio=`, see [`foley.edit()`](foley.html.md#foley.edit)) reaches them, and none
joins a text-to-audio or video-to-audio order. Their Stable Audio 3 row is the
generator’s: the edit mode narrows each edit’s rights to its source’s
([`foley.sources.edit.edit_lineage()`](foley.sources.edit.html.md#foley.sources.edit.edit_lineage)).

Pricing is fal’s (`unit`/`amount_usd` as in [`foley.cost.estimate_call()`](foley.cost.html.md#foley.cost.estimate_call)), with the
date it was read. `per_second` with no requested duration is priced at the
`duration_default_s` the adapter sends in its place (or the endpoint’s maximum, an upper
bound, when it declares none), never at zero.

### Module Attributes

| [`EDIT_SOURCE_CONFIGS`](#foley.sources.fal.config.EDIT_SOURCE_CONFIGS)   | named, or picked by foley.edit from their edit_op.                           |
|------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`FAL_SOURCES`](#foley.sources.fal.config.FAL_SOURCES)           | The fal source names, in the order above (the first is the recommended one). |

### foley.sources.fal.config.EDIT_SOURCE_CONFIGS *= ({'api': {'endpoint_id': 'fal-ai/stable-audio-3/small/sfx/audio-to-audio'}, 'auth': {'apply_url': 'https://fal.ai/dashboard/keys', 'env_var': 'FAL_KEY', 'extra': 'fal', 'type': 'token'}, 'commercial_ok': True, 'data_egress': 'external', 'dependencies': [], 'display_name': 'Stable Audio 3 Small-SFX audio-to-audio (fal)', 'edit_op': 'audio_to_audio', 'kind': 'generate', 'license': {'cache_bytes_ok': True, 'default_license_id': 'Stability-Community'}, 'modes': ['edit'], 'name': 'fal_stable_audio_3_audio_to_audio', 'native_defaults': {'distilled': True, 'duration_default_s': 10.0, 'duration_max_s': 120.0, 'duration_min_s': 1.0, 'fixed_arguments': {'enable_prompt_expansion': False, 'enable_safety_checker': True}, 'generator_version': 'fal-ai/stable-audio-3/small/sfx/audio-to-audio', 'model_id': 'stable-audio-3-small-sfx', 'output_format': 'wav', 'sample_rate': 44100, 'seed_field': 'seed'}, 'on_unsupported_param': 'warn', 'optional_dependencies': ['falaw'], 'output': {'audio_field': 'audio', 'returns': 'url', 'storage': 'by_value'}, 'param_map': {'audio': {'native_name': 'audio_url'}, 'duration_s': {'native_name': 'duration'}, 'expand_prompt': {'native_name': 'enable_prompt_expansion'}, 'negative_prompt': {'native_name': 'negative_prompt'}, 'output_format': {'native_name': 'output_format', 'to_native_map': {'flac': 'flac', 'mp3': 'mp3', 'opus': 'opus', 'wav': 'wav'}}, 'prompt': {'native_name': 'prompt', 'required': True}, 'prompt_influence': {'coerce': {'hi': 25.0, 'kind': 'linear', 'lo': 1.0}, 'native_default': 1.0, 'native_name': 'guidance_scale'}, 'seed': {'native_name': 'seed'}, 'steps': {'native_name': 'num_inference_steps'}, 'strength': {'native_name': 'init_noise_level'}}, 'pricing': {'amount_usd': 0.024, 'seen': '2026-10-27', 'source': 'fal pricing API (GET /v1/models/pricing?endpoint_id=...)', 'unit': 'per_call'}, 'provider_params': {'append': {}, 'priced': ['duration'], 'reserved': ['audio_url', 'enable_prompt_expansion', 'enable_safety_checker', 'num_samples', 'prompt']}, 'rate': {'per_min': 60}, 'supported_affordances': ['prompt', 'audio', 'prompt_influence', 'negative_prompt', 'steps', 'seed', 'output_format', 'expand_prompt', 'duration_s', 'strength'], 'unsupported_affordances': ['loop'], 'website': 'https://fal.ai/models/fal-ai/stable-audio-3/small/sfx/audio-to-audio'}, {'api': {'endpoint_id': 'fal-ai/stable-audio-3/small/sfx/audio-inpainting'}, 'auth': {'apply_url': 'https://fal.ai/dashboard/keys', 'env_var': 'FAL_KEY', 'extra': 'fal', 'type': 'token'}, 'commercial_ok': True, 'data_egress': 'external', 'dependencies': [], 'display_name': 'Stable Audio 3 Small-SFX inpaint (fal)', 'edit_op': 'inpaint', 'kind': 'generate', 'license': {'cache_bytes_ok': True, 'default_license_id': 'Stability-Community'}, 'modes': ['edit'], 'name': 'fal_stable_audio_3_inpaint', 'native_defaults': {'distilled': True, 'fixed_arguments': {'enable_prompt_expansion': False, 'enable_safety_checker': True}, 'generator_version': 'fal-ai/stable-audio-3/small/sfx/audio-inpainting', 'model_id': 'stable-audio-3-small-sfx', 'output_format': 'wav', 'sample_rate': 44100, 'seed_field': 'seed'}, 'on_unsupported_param': 'warn', 'optional_dependencies': ['falaw'], 'output': {'audio_field': 'audio', 'returns': 'url', 'storage': 'by_value'}, 'param_map': {'audio': {'native_name': 'audio_url'}, 'expand_prompt': {'native_name': 'enable_prompt_expansion'}, 'inpaint_end_s': {'native_name': 'mask_end_seconds'}, 'inpaint_start_s': {'native_name': 'mask_start_seconds'}, 'negative_prompt': {'native_name': 'negative_prompt'}, 'output_format': {'native_name': 'output_format', 'to_native_map': {'flac': 'flac', 'mp3': 'mp3', 'opus': 'opus', 'wav': 'wav'}}, 'prompt': {'native_name': 'prompt', 'required': True}, 'prompt_influence': {'coerce': {'hi': 25.0, 'kind': 'linear', 'lo': 1.0}, 'native_default': 1.0, 'native_name': 'guidance_scale'}, 'seed': {'native_name': 'seed'}, 'steps': {'native_name': 'num_inference_steps'}}, 'pricing': {'amount_usd': 0.0259, 'seen': '2026-10-27', 'source': 'fal pricing API (GET /v1/models/pricing?endpoint_id=...)', 'unit': 'per_call'}, 'provider_params': {'append': {}, 'priced': ['duration'], 'reserved': ['audio_url', 'enable_prompt_expansion', 'enable_safety_checker', 'num_samples', 'prompt']}, 'rate': {'per_min': 60}, 'supported_affordances': ['prompt', 'audio', 'prompt_influence', 'negative_prompt', 'steps', 'seed', 'output_format', 'expand_prompt', 'inpaint_start_s', 'inpaint_end_s'], 'unsupported_affordances': ['loop', 'duration_s'], 'website': 'https://fal.ai/models/fal-ai/stable-audio-3/small/sfx/audio-inpainting'}, {'api': {'endpoint_id': 'fal-ai/stable-audio-3/small/sfx/audio-outpainting'}, 'auth': {'apply_url': 'https://fal.ai/dashboard/keys', 'env_var': 'FAL_KEY', 'extra': 'fal', 'type': 'token'}, 'commercial_ok': True, 'data_egress': 'external', 'dependencies': [], 'display_name': 'Stable Audio 3 Small-SFX extend (fal)', 'edit_op': 'extend', 'kind': 'generate', 'license': {'cache_bytes_ok': True, 'default_license_id': 'Stability-Community'}, 'modes': ['edit'], 'name': 'fal_stable_audio_3_extend', 'native_defaults': {'distilled': True, 'fixed_arguments': {'enable_prompt_expansion': False, 'enable_safety_checker': True}, 'generator_version': 'fal-ai/stable-audio-3/small/sfx/audio-outpainting', 'model_id': 'stable-audio-3-small-sfx', 'output_format': 'wav', 'sample_rate': 44100, 'seed_field': 'seed'}, 'on_unsupported_param': 'warn', 'optional_dependencies': ['falaw'], 'output': {'audio_field': 'audio', 'returns': 'url', 'storage': 'by_value'}, 'param_map': {'audio': {'native_name': 'audio_url'}, 'expand_prompt': {'native_name': 'enable_prompt_expansion'}, 'extend_after_s': {'max': 120.0, 'native_name': 'extend_seconds_after'}, 'extend_before_s': {'max': 120.0, 'native_name': 'extend_seconds_before'}, 'negative_prompt': {'native_name': 'negative_prompt'}, 'output_format': {'native_name': 'output_format', 'to_native_map': {'flac': 'flac', 'mp3': 'mp3', 'opus': 'opus', 'wav': 'wav'}}, 'prompt': {'native_name': 'prompt', 'required': True}, 'prompt_influence': {'coerce': {'hi': 25.0, 'kind': 'linear', 'lo': 1.0}, 'native_default': 1.0, 'native_name': 'guidance_scale'}, 'seed': {'native_name': 'seed'}, 'steps': {'native_name': 'num_inference_steps'}}, 'pricing': {'amount_usd': 0.0271, 'seen': '2026-10-27', 'source': 'fal pricing API (GET /v1/models/pricing?endpoint_id=...)', 'unit': 'per_call'}, 'provider_params': {'append': {}, 'priced': ['duration'], 'reserved': ['audio_url', 'enable_prompt_expansion', 'enable_safety_checker', 'num_samples', 'prompt']}, 'rate': {'per_min': 60}, 'supported_affordances': ['prompt', 'audio', 'prompt_influence', 'negative_prompt', 'steps', 'seed', 'output_format', 'expand_prompt', 'extend_before_s', 'extend_after_s'], 'unsupported_affordances': ['loop', 'duration_s'], 'website': 'https://fal.ai/models/fal-ai/stable-audio-3/small/sfx/audio-outpainting'})*

named, or picked by foley.edit from their edit_op.

* **Type:**
  The edit sources (#162)

### foley.sources.fal.config.FAL_SOURCES *= ('fal_stable_audio_3', 'fal_stable_audio_3_medium', 'fal_mirelo', 'fal_elevenlabs', 'fal_sonilo', 'fal_mmaudio', 'fal_mirelo_v2a', 'fal_sonilo_v2a', 'fal_mmaudio_v2a', 'fal_thinksound', 'fal_hunyuan_foley', 'fal_stable_audio_3_audio_to_audio', 'fal_stable_audio_3_inpaint', 'fal_stable_audio_3_extend')*

The fal source names, in the order above (the first is the recommended one).
