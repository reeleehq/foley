# foley.sources.fal.config

`SOURCE_CONFIGS` for the fal-hosted text-to-SFX endpoints, executed through `falaw` (#73).

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

* `fal_stable_audio_3` (and `fal_stable_audio_3_medium`) — Stable Audio 3 weights are under the Stability AI
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

Pricing is fal’s (`unit`/`amount_usd` as in [`foley.cost.estimate_call()`](foley.cost.html.md#foley.cost.estimate_call)), with the
date it was read. `per_second` with no requested duration is priced at the
`duration_default_s` the adapter sends in its place (or the endpoint’s maximum, an upper
bound, when it declares none), never at zero.

### Module Attributes

| [`FAL_SOURCES`](#foley.sources.fal.config.FAL_SOURCES)   | The fal source names, in the order above (the first is the recommended one).   |
|----------------------------------------------------------------|--------------------------------------------------------------------------------|

### foley.sources.fal.config.FAL_SOURCES *= ('fal_stable_audio_3', 'fal_stable_audio_3_medium', 'fal_mirelo', 'fal_elevenlabs', 'fal_sonilo', 'fal_mmaudio', 'fal_mirelo_v2a', 'fal_sonilo_v2a', 'fal_mmaudio_v2a', 'fal_thinksound', 'fal_hunyuan_foley')*

The fal source names, in the order above (the first is the recommended one).
