# foley.sources.pull

`add_from` — the live-source pull façade (SOURCE → INDEX in one call).

The live analog of `foley.bootstrap.bootstrap()`’s per-corpus ingest loop:
resolve a registered live [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter), search it
(with the license filter pushed into the query), gate each hit through the
fail-closed [`foley.keep()`](foley.html.md#foley.keep) license check, fetch its (transient) bytes, and run
them through the SAME [`foley.index.ingest.ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) pipeline the local and
bulk paths use — so decode / QC / embed / tag / store are **not forked**.

For Freesound this stores every sound BY-REFERENCE (`cache_bytes_ok=False`): the
transient preview bytes are embedded once, then discarded; only the stable URI +
provenance + the CLAP vector persist. The audio is re-fetched on demand via the
adapter (there is no local blob to serve — `library.audio(id)` raises for a
remote by-reference sound; that is the contract).

### Module Attributes

| [`SOURCE_DEFAULT_LICENSE`](#foley.sources.pull.SOURCE_DEFAULT_LICENSE)   | the source's own (`config['license']['search_default']`), [`DFLT_SEARCH_LICENSE`](#foley.sources.pull.DFLT_SEARCH_LICENSE) when it declares none.   |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_SEARCH_LICENSE`](#foley.sources.pull.DFLT_SEARCH_LICENSE)      | The licence a search asks for when neither the call nor the source says.                                                                                |

### Functions

| [`add_from`](#foley.sources.pull.add_from)(source, \*, query[, license, limit, ...])   | Search a live `source` and ingest its license-clean hits into `library`.   |
|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`search_license`](#foley.sources.pull.search_license)(license, config)                      | The `license` a search sends: `license`, or the source's default for it.   |

### foley.sources.pull.DFLT_SEARCH_LICENSE *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'cc0'*

The licence a search asks for when neither the call nor the source says.

### foley.sources.pull.SOURCE_DEFAULT_LICENSE *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'source-default'*

the source’s own
(`config['license']['search_default']`), [`DFLT_SEARCH_LICENSE`](#foley.sources.pull.DFLT_SEARCH_LICENSE) when it
declares none. A music library has one licence, so it declares `None`.

* **Type:**
  `add_from`’s `license` default

### foley.sources.pull.add_from(source, , query, license='source-default', limit=50, library=None, intended_use=None, adapter=None, on_unsupported=None, provider_params=None, \*\*affordances)

Search a live `source` and ingest its license-clean hits into `library`.

Progressive disclosure: `add_from("freesound", query="ocean waves")` works out
of the box (CC0-only, into the process-wide default library); every other knob
is an optional keyword. Each hit is license-gated BEFORE any bytes are fetched
(fail-closed), then routed through [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one), which
applies the by-reference storage gate from the sound’s own license.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A registered live-source name (e.g. `'freesound'`).
  * **query** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – The natural-language search query (a music library also takes a
    list of titles).
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – License constraint pushed into the source query. Default: the
    source’s own (`config['license']['search_default']`), `'cc0'` for a
    source that declares none; a music library (one licence) declares no
    narrowing. The per-item fail-closed guard enforces the source’s
    accepted-license allowlist regardless.
  * **limit** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max candidates to request from the source.
  * **library** – Target [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the
    process-wide default library).
  * **intended_use** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)]) – The rights intent each candidate is gated against (default:
    `DEFAULT_INTENDED_USE`).
  * **adapter** – An optional pre-built adapter to use instead of the registry’s
    (the dependency-injection seam — a test passes a fake-transport
    adapter; production omits it and the registry lazily builds one).
  * **on_unsupported** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A search parameter the source cannot honour: `None`
    (default) drops it with a note in `report.notes`; `'raise'` raises
    (see `foley.sources._dispatch.translate_affordances()`).
  * **provider_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Native search params of the source that foley has no
    unified affordance for (#61), e.g. Freesound’s
    `{"filter": "ac_brightness:[50 TO 100]"}`. Passed to the adapter’s
    `search` untranslated (so the unsupported-parameter policy does not see
    them) and merged over its translated params; the licence filter and the
    fail-closed gate still apply.
  * **\*\*affordances** – Extra unified affordances forwarded to the adapter’s
    `search` (see [`foley.base.QUERY_AFFORDANCES`](foley.base.html.md#foley.base.QUERY_AFFORDANCES)): `duration_range`,
    `sort` (`relevance` | `newest` | `popular` | `duration`),
    `page`, `kind` (`sfx` | `music`), `sources`, `include_explicit`,
    `similar_to`, `ucs_category`.
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) — inspect `.ingested` for the
  stored records (each `storage_mode == by_reference` for Freesound) and
  `.summary()` for counts, exactly like [`foley.ingest()`](foley.html.md#foley.ingest).
* **Raises:**
  * [**SearchArgumentError**](foley.sources.base.html.md#foley.sources.base.SearchArgumentError) – A search argument the source refuses before any call
        (a `ValueError`), e.g. a `page` past its result window (Openverse
        serves ~240 results a query), or Freesound’s `kind` and
        `ucs_category` naming two different top levels.
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – A missing key or optional dependency.

### foley.sources.pull.search_license(license, config)

The `license` a search sends: `license`, or the source’s default for it.

```pycon
>>> search_license("CC-BY-4.0", {}), search_license(SOURCE_DEFAULT_LICENSE, {})
('CC-BY-4.0', 'cc0')
>>> print(search_license(SOURCE_DEFAULT_LICENSE, {"license": {"search_default": None}}))
None
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
