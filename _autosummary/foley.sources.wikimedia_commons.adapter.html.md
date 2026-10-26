# foley.sources.wikimedia_commons.adapter

Wikimedia Commons retrieve adapter: audio files with their licence, keyless.

`search` turns a query into `list=search` over the File namespace restricted to audio
(`filetype:audio`), asking for each file’s URL, size, duration and `extmetadata` in
the same call (the generator form). Each file’s licence is read from `extmetadata`
(`LicenseUrl`, else `LicenseShortName`) through the one licence SSOT, so:

* CC0 and CC-BY become candidates, verified; a request for CC0 only (the façade’s
  default `license='cc0'`) keeps CC0 alone;
* “Public domain” becomes `PDM-1.0` with `rights_verified=False`: a claim, never
  cleared by the licence field alone (Commons also holds impressions of copyrighted
  characters labelled public domain), so the pull gate stops it until a person confirms;
* share-alike, no-derivatives and anything unrecognised are dropped (fail closed).

The bytes come from `upload.wikimedia.org` with the same descriptive `User-Agent`;
a 429 is waited out by the resilient transport the registry wraps around `http`
(see `retry` in the config). HTTP is injected.

### Module Attributes

| [`Adapter`](#foley.sources.wikimedia_commons.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.wikimedia_commons.adapter.Adapter)                                 | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                    |
|------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| [`WikimediaCommonsAdapter`](#foley.sources.wikimedia_commons.adapter.WikimediaCommonsAdapter)([config, http]) | Keyless Wikimedia Commons adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### foley.sources.wikimedia_commons.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.wikimedia_commons.adapter.WikimediaCommonsAdapter(config=None, , http=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Keyless Wikimedia Commons adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (the registry passes it positionally).
  * **http** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)]) – The injected [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport).

#### download(source_id)

The file’s audio bytes (from the URL a search hit gave, else resolved by id).

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### get(source_id)

Resolve one file (page id) to its record.

* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the file is missing or its licence is not accepted.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### invoke_native(\*\*params)

Call the MediaWiki `action=query` API with native `params`; return its JSON (#61).

It bypasses the licence filter and the per-item licence check that
[`search()`](#foley.sources.wikimedia_commons.adapter.WikimediaCommonsAdapter.search) applies: the caller owns licence gating for what comes back.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### search(query, , license='cc0', k=15, provider_params=None, \*\*kw)

Search Commons audio for `query`; return licence-checked candidates.

* **Parameters:**
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – `'cc0'` (default) keeps CC0 files only; anything else (`None`,
    `'cc-by'`) also keeps CC-BY and the unverified public-domain claims.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max files requested (the API’s limit is 50).
  * **provider_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Native search params merged over the translated ones
    (#61); the per-item licence check still applies.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
