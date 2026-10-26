# foley.sources.stable_audio_3

Stable Audio 3 Small-SFX generate source (local, CPU, no GPU and no HF token; #72).

Auto-discovered by [`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources), which imports ONLY
[`config`](foley.sources.stable_audio_3.config.html.md#module-foley.sources.stable_audio_3.config) (stdlib-only). The adapter loads on first
use via the module `__getattr__` below, so `import foley` stays dol-only.

### Classes

| `Adapter`                                     |                                                                                                                                                 |
|-----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| `StableAudio3Adapter`([config, runner, home]) | Local Stable Audio 3 Small-SFX adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### Modules

| [`adapter`](foley.sources.stable_audio_3.adapter.html.md#module-foley.sources.stable_audio_3.adapter)   | Stable Audio 3 Small-SFX generate adapter: Stability's TFLite CPU build, run as a process.   |
|--------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`config`](foley.sources.stable_audio_3.config.html.md#module-foley.sources.stable_audio_3.config)     | `SOURCE_CONFIG` for the local Stable Audio 3 Small-SFX generator (#72 · report 13 · 17).     |
