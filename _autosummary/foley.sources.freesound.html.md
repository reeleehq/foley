# foley.sources.freesound

Freesound APIv2 retrieve source — CC0 sounds, stored by-reference (`foley[freesound]`).

Declares `SOURCE_CONFIG` (auto-discovered by
[`foley.sources.registry`](foley.sources.registry.html.md#module-foley.sources.registry)) and the `FreesoundAdapter` (aliased
`Adapter` for the registry’s lazy loader). Importing this package is dol-only —
and it is also **discovery-light**: [`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources)
imports only `config.py`, so `adapter.py` (and, later, its lazy `requests`)
is not loaded until an adapter is actually built. To preserve that, the adapter
classes are exposed via a module-level `__getattr__` rather than eagerly imported
here.

### Classes

| `Adapter`                                   |                                                                                                                                            |
|---------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| `FreesoundAdapter`([config, api_key, http]) | Live Freesound APIv2 retrieve adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### Modules

| [`adapter`](foley.sources.freesound.adapter.html.md#module-foley.sources.freesound.adapter)   | Freesound APIv2 retrieve adapter — CC0 (and CC-BY) sounds, stored strictly by-reference.   |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`config`](foley.sources.freesound.config.html.md#module-foley.sources.freesound.config)     | `SOURCE_CONFIG` for the Freesound APIv2 retrieve source (report 01 · 07 · 10 §4.1).        |
