# foley.sources.stable_audio

Stable Audio Open 1.0 generate source (local default; #6).

Auto-discovered by [`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources), which imports
ONLY [`config`](foley.sources.stable_audio.config.html.md#module-foley.sources.stable_audio.config) (stdlib-only — no `torch` /
`diffusers`). The [`StableAudioAdapter`](foley.sources.stable_audio.adapter.html.md#foley.sources.stable_audio.adapter.StableAudioAdapter)
and its heavy ML stack (the `foley[stable-audio]` extra) load on first use — never
at `import foley` or during discovery — via the module `__getattr__` below.

### Classes

| `Adapter`                                     |                                                                                                                                                       |
|-----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `StableAudioAdapter`([config, pipeline, ...]) | Local Stable Audio Open 1.0 generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### Modules

| [`adapter`](foley.sources.stable_audio.adapter.html.md#module-foley.sources.stable_audio.adapter)   | Stable Audio Open 1.0 generate adapter — local `diffusers` inference.                     |
|------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`config`](foley.sources.stable_audio.config.html.md#module-foley.sources.stable_audio.config)     | `SOURCE_CONFIG` for the local Stable Audio Open 1.0 generator (report 02 · 07 · 10 §4.1). |
