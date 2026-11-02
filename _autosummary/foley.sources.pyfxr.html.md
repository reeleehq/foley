# foley.sources.pyfxr

pyfxr procedural source: sfxr-family category presets, free, offline and seeded (#76).

Auto-discovered by [`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources), which imports ONLY
[`config`](foley.sources.pyfxr.config.html.md#module-foley.sources.pyfxr.config) (stdlib-only). The adapter, and `pyfxr` itself
(the `foley[pyfxr]` extra), load on first use via the module `__getattr__` below.

### Classes

| `Adapter`                |                                                                                                                                       |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `PyfxrAdapter`([config]) | The pyfxr procedural adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### Modules

| [`adapter`](foley.sources.pyfxr.adapter.html.md#module-foley.sources.pyfxr.adapter)   | pyfxr procedural adapter: a category preset, seeded, rendered to audio bytes (#76).   |
|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`config`](foley.sources.pyfxr.config.html.md#module-foley.sources.pyfxr.config)     | `SOURCE_CONFIG` for pyfxr, the first procedural source (#76; report 13 §2E, §5.12).   |
