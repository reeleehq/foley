# foley.sources.freesound.adapter

Freesound APIv2 retrieve adapter — CC0 sounds, stored strictly by-reference.

Freesound (report 01 §Freesound) is foley’s anchor retrieve source. This adapter
turns a natural-language query into ranked, license-clean
[`Candidate`](foley.base.html.md#foley.base.Candidate)s over the Freesound APIv2, honoring two
load-bearing constraints:

* **CC0-only (for #5), pushed into the query.** The CC0 filter is sent as the
  native `filter=license:"Creative Commons 0"` so non-CC0 sounds never leave the
  server; each returned item is *also* re-checked fail-closed against the
  `accepted_license_ids` allowlist — the server filter is a promise foley does
  not control, so a non-CC0 item that slips through is dropped, never indexed.
* **By-reference storage (TOS).** The Freesound API TOS forbids caching the audio
  bytes even for CC0, so every sound is licensed `cache_bytes_ok=False` (a
  per-item override on top of its own CC id — see
  [`api_license()`](foley.sources.base.html.md#foley.sources.base.api_license)). foley keeps the stable sound-page URI
  + provenance + the CLAP vector; the bytes fetched here (a token-tier preview
  > transcode) are transient — embedded once by [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one),
  > then discarded, never persisted.

HTTP is dependency-injected (a [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)), so the
adapter is fully testable with no network and `import foley` stays dol-only; the
real `requests` lives only behind
[`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport) (the `foley[freesound]` extra).
Ingestion (decode / QC / embed / tag / store) is NOT reimplemented here — the
[`foley.sources.pull.add_from()`](foley.sources.pull.html.md#foley.sources.pull.add_from) façade routes every hit through the shared
`ingest_one` pipeline (it wraps the corpus machinery, it does not fork it).

### Module Attributes

| [`Adapter`](#foley.sources.freesound.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.freesound.adapter.Adapter)                                   | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                        |
|--------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| [`FreesoundAdapter`](#foley.sources.freesound.adapter.FreesoundAdapter)([config, api_key, http]) | Live Freesound APIv2 retrieve adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### foley.sources.freesound.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.freesound.adapter.FreesoundAdapter(config=None, , api_key=None, http=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Live Freesound APIv2 retrieve adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (defaults to the module’s). Passed positionally
    by the registry’s lazy loader (the arioso `Adapter(config)` convention).
  * **api_key** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The Freesound token. Defaults to `$FREESOUND_API_KEY`.
  * **http** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)]) – The injected [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) (defaults to
    [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)); tests pass a fake.

#### *property* api_key *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The Freesound token (constructor, else a bound key, else `$FREESOUND_API_KEY`).

#### download(source_id, , preview_url=None)

Return a sound’s transient preview bytes (token-tier; never cached).

* **Parameters:**
  * **source_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The Freesound id (either id form).
  * **preview_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional known preview URL (from a prior search hit) — used
    directly to save a round-trip; otherwise the sound instance is
    fetched to resolve it.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
* **Returns:**
  The preview audio bytes (embedded once, then discarded — see the
  by-reference storage contract).
* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the sound exposes no preview.

#### get(source_id)

Resolve one Freesound id (`'12345'` or `'freesound:12345'`) to a record.

* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the sound’s license is not in the accepted allowlist.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### search(query, , license='cc0', k=15, duration_range=None, sort=None, \*\*kw)

Search Freesound for `query`; return license-clean candidates.

The `license='cc0'` filter is pushed into the native Solr `filter` so
non-CC0 sounds never leave the server; every returned item is still
re-checked fail-closed before it becomes a candidate.

* **Parameters:**
  * **license** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – License constraint. `'cc0'` (default) sends the CC0 filter;
    `None` sends none (the per-item guard still enforces the
    `accepted_license_ids` allowlist, so results stay CC0 for #5).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max results (Freesound caps `page_size` at 150).
  * **duration_range** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Optional `(min_s, max_s)` native duration filter.
  * **sort** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional native sort key (default: Freesound relevance).
  * **\*\*kw** – Ignored extra affordances (`on_unsupported_param='warn'`).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  Up to `k` [`Candidate`](foley.base.html.md#foley.base.Candidate)s (`origin=retrieved`),
  each carrying a by-reference [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) and a
  transient `preview_uri`.
