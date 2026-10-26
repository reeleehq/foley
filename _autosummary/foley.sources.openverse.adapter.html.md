# foley.sources.openverse.adapter

Openverse retrieve adapter: keyless audio search with ready attribution strings.

`search` calls `/v1/audio/` (anonymous: `page_size` ≤ 20, Freesound and Jamendo rows
excluded, see the config) with the licence filter pushed into the query, then re-checks
each row’s licence fail-closed through `foley.sources._keyless.license_for_item()`
(Openverse does not verify licences: a row’s licence is the one its origin provider
reported, trusted like Freesound’s own field; the landing page is the check for anything
that matters). The terms’ “made using Openverse” notice is stamped on each licence record
(`notice_text_required`), so the credits carry it. Durations arrive in milliseconds. `download` fetches
the row’s `url` (cached from search, else resolved from `/audio/{id}/`). HTTP and the
429 sleep are injected.

### Module Attributes

| [`Adapter`](#foley.sources.openverse.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.openverse.adapter.Adapter)                         | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                            |
|----------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`OpenverseAdapter`](#foley.sources.openverse.adapter.OpenverseAdapter)([config, ...]) | Keyless Openverse adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### foley.sources.openverse.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.openverse.adapter.OpenverseAdapter(config=None, , include_freesound=False, http=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Keyless Openverse adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (the registry passes it positionally).
  * **include_freesound** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Keep Freesound rows (stored by reference, bytes never cached);
    off by default: use the `freesound` source for those.
  * **http** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)]) – The injected [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport).

#### download(source_id)

The row’s audio bytes (from the URL a search hit gave, else resolved by id).

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### get(source_id)

Resolve one row id (a UUID) to its record.

* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If its licence is not accepted.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### *property* notice *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The sentence Openverse’s terms require an app to show prominently.

#### search(query, , license='cc0', k=15, \*\*kw)

Search Openverse audio for `query`; return licence-checked candidates.

* **Parameters:**
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – `'cc0'` (default) asks for CC0 only; anything else asks for CC0,
    CC-BY and public-domain-mark rows.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max rows (anonymous limit 20).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
