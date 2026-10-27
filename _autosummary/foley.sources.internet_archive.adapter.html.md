# foley.sources.internet_archive.adapter

Internet Archive retrieve adapter: opt-in discovery of archival sounds, never auto-verified.

Items come from `advancedsearch.php` restricted to audio with a `licenseurl`. Each
item’s licence string goes through the one licence SSOT and the config’s allowlist, and
every candidate gets `rights_verified=False` whatever it says: the field is what the
uploader asserted. So [`foley.sources.pull.add_from()`](foley.sources.pull.html.md#foley.sources.pull.add_from) skips these until a person has
confirmed an item; the adapter is for finding and fetching, not for clearing.
Constructing it without the opt-in raises [`SourceConfigurationError`](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError).

### Module Attributes

| [`Adapter`](#foley.sources.internet_archive.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.internet_archive.adapter.Adapter)                                        | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                  |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`InternetArchiveAdapter`](#foley.sources.internet_archive.adapter.InternetArchiveAdapter)([config, opt_in, http]) | Opt-in Internet Archive adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### foley.sources.internet_archive.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.internet_archive.adapter.InternetArchiveAdapter(config=None, , opt_in=None, http=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Opt-in Internet Archive adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (the registry passes it positionally).
  * **opt_in** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Use the archive. Default: whether `$FOLEY_INTERNET_ARCHIVE` is set to 1.
  * **http** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)]) – The injected [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport).

#### download(source_id)

The first audio file of the item under `max_file_bytes` (see the config).

* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the item’s licence is not accepted (checked here too, so a
      direct call cannot fetch what a search would have dropped), or it has no
      suitable audio file.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### get(source_id)

Resolve one item identifier to its record.

* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the item is missing or its licence is not accepted.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### invoke_native(url, \*\*params)

GET an Internet Archive `url` with native `params`; return the parsed JSON (#61).

It bypasses the licence filter and the per-item licence check that
[`search()`](#foley.sources.internet_archive.adapter.InternetArchiveAdapter.search) applies: the caller owns licence gating for what comes back.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### search(query, , license=None, k=15, provider_params=None, \*\*kw)

Search archive audio for `query`; return candidates (all unverified).

`license` is a licence id (`'CC0-1.0'`; `'cc0'` is an alias) and keeps only
items under it; `None` keeps every accepted licence. The default is `None`,
unlike the other CC sources’ `'cc0'`, because every archive licence is an
unverified claim anyway; `add_from` always passes its own (`'cc0'`) default.
The query always asks for items with a `licenseurl`.
`provider_params` are native advancedsearch params merged over the
translated ones (#61); a `q` is ANDed onto foley’s as one group, never
replaces it (the config’s `provider_params` policy).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
