# foley.sources.fal

fal-hosted generate sources, executed through `falaw` (#73).

Declares `SOURCE_CONFIGS` — one foley source per fal
text-to-SFX endpoint (`fal_stable_audio_3`, `fal_stable_audio_3_medium`,
`fal_mirelo`, `fal_elevenlabs`, `fal_sonilo`, `fal_mmaudio`) — auto-discovered by [`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources).
The shared [`FalAdapter`](foley.sources.fal.adapter.html.md#foley.sources.fal.adapter.FalAdapter) and `falaw` (the
`foley[fal]` extra) load on first use, never at `import foley`.

### Classes

| `Adapter`                                        |                                                                                                                                        |
|--------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `FalAdapter`(config, \*[, api_key, runner, ...]) | A fal-hosted generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### Modules

| [`adapter`](foley.sources.fal.adapter.html.md#module-foley.sources.fal.adapter)   | The fal generate adapter — one class for every fal-hosted SFX endpoint, run through `falaw`.   |
|---------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| [`config`](foley.sources.fal.config.html.md#module-foley.sources.fal.config)     | `SOURCE_CONFIGS` for the fal-hosted text-to-SFX endpoints, executed through `falaw` (#73).     |
