# foley.sources.registry

Live-source adapter registry: auto-discovery + lazy loading (arioso’s registry, ported).

Scans [`foley.sources`](foley.sources.html.md#module-foley.sources) for sub-**packages** that declare a `SOURCE_CONFIG`
(a `config.py` with the plugin declaration), registers them, and lazily imports

+ instantiates each adapter only on first use. Mirrors `arioso.registry` /
  `PLATFORM_CONFIG` (report 10 §4.1).

This is the **live-source** registry (Freesound; hosted generators in #6) — a
*separate* registry from the bulk-corpus
[`foley.sources.base.CORPUS_REGISTRY`](foley.sources.base.html.md#foley.sources.base.CORPUS_REGISTRY). The two adapter kinds have different
contracts (`search` / `get` / `download` vs `iter_clips` /
`resolve_license`) and different façades ([`foley.add_from()`](foley.html.md#foley.add_from) vs
[`foley.bootstrap()`](foley.html.md#foley.bootstrap)). They stay disjoint **by construction**: discovery only
picks up sub-packages (`ispkg` and not `_`-prefixed), so the flat bulk-corpus
modules (`fsd50k.py` …) and the flat helper modules here (`base`, `http`,
`pull`, `registry`) are never cross-captured.

Out-of-tree plugins — and test doubles — register directly via
[`register_source()`](#foley.sources.registry.register_source) (no package needed).

### Module Attributes

| [`SOURCE_REGISTRY`](#foley.sources.registry.SOURCE_REGISTRY)   | Public read alias of the registry (callers/tests inspect discovered sources).   |
|--------------------------------------------------------------------|---------------------------------------------------------------------------------|

### Functions

| [`discover_sources`](#foley.sources.registry.discover_sources)()                       | Scan [`foley.sources`](foley.sources.html.md#module-foley.sources) sub-packages for a `SOURCE_CONFIG` and register them.   |
|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| [`get_source`](#foley.sources.registry.get_source)(name)                         | Return the `{'config', 'adapter'}` entry for `name`, lazily building the adapter.                                                                |
| [`list_sources`](#foley.sources.registry.list_sources)(\*[, egress_allow])         | Return the names of registered live sources (runs discovery first).                                                                              |
| [`local_sources`](#foley.sources.registry.local_sources)()                          | The names of sources that run entirely on-device (`data_egress == 'local'`).                                                                     |
| [`register_source`](#foley.sources.registry.register_source)(name, config[, adapter]) | Register a live source directly (out-of-tree plugin or a test double).                                                                           |
| [`require_source_egress`](#foley.sources.registry.require_source_egress)(name[, config])    | Raise [`EgressBlocked`](foley.runtime.html.md#foley.runtime.EgressBlocked) if source `name` may not run now.               |
| [`source_egress`](#foley.sources.registry.source_egress)(name)                      | The declared `data_egress` class of source `name` (`None` if undeclared).                                                                        |

### foley.sources.registry.SOURCE_REGISTRY *= {}*

Public read alias of the registry (callers/tests inspect discovered sources).

### foley.sources.registry.discover_sources()

Scan [`foley.sources`](foley.sources.html.md#module-foley.sources) sub-packages for a `SOURCE_CONFIG` and register them.

A valid live source is a sub-package of [`foley.sources`](foley.sources.html.md#module-foley.sources) (`ispkg` and
not `_`-prefixed) whose `config.py` defines a `SOURCE_CONFIG` dict with a
`name` (or a `SOURCE_CONFIGS` sequence of them: several sources sharing one
adapter class, see `_declared_configs()`). Flat modules (bulk-corpus adapters + helpers) are skipped, so this
never cross-captures the corpus adapters. Only `config.py` is imported here
(stdlib-cheap); the adapter loads lazily in [`get_source()`](#foley.sources.registry.get_source). Idempotent —
an already-registered name (e.g. a test double) is never overwritten.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The list of discovered source names.

### foley.sources.registry.get_source(name)

Return the `{'config', 'adapter'}` entry for `name`, lazily building the adapter.

Runs a discovery pass if `name` is not yet known, then instantiates the
adapter on first use (cached in the entry).

* **Parameters:**
  **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The source name.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  The registry entry (`{'config': dict, 'adapter': SourceAdapter, ...}`).
* **Raises:**
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If no such source is registered (after discovery).
  * [**EgressBlocked**](foley.runtime.html.md#foley.runtime.EgressBlocked) – If the source sends data off the device and an offline scope
        is active ([`foley.offline()`](foley.html.md#foley.offline) / `$FOLEY_OFFLINE`).

### foley.sources.registry.list_sources(, egress_allow=None)

Return the names of registered live sources (runs discovery first).

* **Parameters:**
  **egress_allow** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – If given, keep only sources whose declared
  `config['data_egress']` is in this set (the local-first / offline
  filter — see [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig)). A source that does
  not declare `data_egress` is **excluded** (fail-closed).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.registry.local_sources()

The names of sources that run entirely on-device (`data_egress == 'local'`).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.registry.register_source(name, config, adapter=None)

Register a live source directly (out-of-tree plugin or a test double).

Overwrites any existing entry for `name` — the seam a test uses to inject a
fake-transport-backed adapter. If `adapter` is `None` it is lazily built
from `config` on first [`get_source()`](#foley.sources.registry.get_source) (the source must then be an
importable `foley.sources.<name>` package).

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The source name (the `add_from()` / [`get_source()`](#foley.sources.registry.get_source) key).
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – The `SOURCE_CONFIG` declaration.
  * **adapter** – An optional pre-instantiated adapter (bypasses lazy loading).
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.registry.require_source_egress(name, config=None)

Raise [`EgressBlocked`](foley.runtime.html.md#foley.runtime.EgressBlocked) if source `name` may not run now.

The one offline check every source path goes through: [`get_source()`](#foley.sources.registry.get_source), and the
generate / pull façades when an adapter is injected. The egress class comes from
`config['data_egress']` (the passed config, else the registered one); a source
that declares none is treated as external (fail-closed), so it is refused offline.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.registry.source_egress(name)

The declared `data_egress` class of source `name` (`None` if undeclared).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
