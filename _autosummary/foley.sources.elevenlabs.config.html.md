# foley.sources.elevenlabs.config

`SOURCE_CONFIG` for the ElevenLabs Sound Effects generator (report 02 · 07 · 10 §4.1).

Stdlib-only and declarative — imports nothing heavy, so
[`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources) can read it cheaply (it imports
only `config.py`; the adapter + `requests` load lazily). It declares the hosted
Text-to-SFX v2 endpoint, the `xi-api-key` token auth, maps foley’s unified
[`GENERATION_AFFORDANCES`](foley.base.html.md#foley.base.GENERATION_AFFORDANCES) onto the native request fields, and — as
required for every source — the **license block**, with `cache_bytes_ok=True`
(generated audio is stored **by-value** — the opposite of Freesound).

License note (report 07, #56): what a generation may be used for depends on the
**account’s plan**, which foley cannot see. A paid plan’s SFX are royalty-free and
embeddable without attribution; a free plan’s are non-commercial and need
attribution. So the plan is never assumed: it comes from the adapter’s `plan=` or
`$FOLEY_ELEVENLABS_PLAN` (`elevenlabs-paid-plan` | `elevenlabs-free-plan`, the
same codes as `an`), each value being its own `LICENSE_FLAGS` row, and an unknown
plan refuses to generate (no paid call is made). The Prohibited-Use policy forbids
standalone redistribution of the raw SFX, which is why both rows set
`redistribute_standalone_ok=False`.

### Module Attributes

| [`PCM_RATES`](#foley.sources.elevenlabs.config.PCM_RATES)   | The raw-PCM rates (Hz) of the direct API's `pcm_<rate>` formats (report 13 §2A).   |
|--------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`MP3_BY_RATE`](#foley.sources.elevenlabs.config.MP3_BY_RATE) | The `mp3_*` format per rate (one bitrate each).                                    |

### foley.sources.elevenlabs.config.MP3_BY_RATE *= {22050: 'mp3_22050_32', 24000: 'mp3_24000_48', 44100: 'mp3_44100_128'}*

The `mp3_*` format per rate (one bitrate each).

### foley.sources.elevenlabs.config.PCM_RATES *= (8000, 16000, 22050, 24000, 32000, 44100, 48000)*

The raw-PCM rates (Hz) of the direct API’s `pcm_<rate>` formats (report 13 §2A).
