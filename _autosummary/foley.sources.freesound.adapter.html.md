# foley.sources.freesound.adapter

Freesound APIv2 retrieve adapter — CC0 (and CC-BY) sounds, stored strictly by-reference.

Freesound (report 01 §Freesound) is foley’s anchor retrieve source. This adapter
turns a natural-language query into ranked, license-clean
[`Candidate`](foley.base.html.md#foley.base.Candidate)s over the Freesound APIv2, honoring two
load-bearing constraints:

* **CC0 by default, CC-BY on request, pushed into the query.** The CC0 filter is sent
  as the native `filter=license:"Creative Commons 0"` so other sounds never leave the
  server (a `license` other than CC0 also asks for `"Attribution"`: the
  credit-bearing sounds the [`keep()`](foley.licensing.html.md#foley.licensing.keep) gate then admits only for a
  caller that can attribute). Each returned item is *also* re-checked fail-closed
  against the `accepted_license_ids` allowlist — the server filter is a promise foley
  does not control, so an NC / SA / ND item that slips through is dropped, never indexed.
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

#### invoke_native(path, \*\*params)

GET a Freesound APIv2 `path` with native `params`; return the parsed JSON.

The public escape hatch below foley’s translation (#61), e.g.
`invoke_native("/search/", query="rain", filter="ac_brightness:[50 TO 100]")`.
It bypasses the licence filter and the per-item licence re-check that
[`search()`](#foley.sources.freesound.adapter.FreesoundAdapter.search) applies: the caller owns licence gating for what it gets back
(and the dispatch layer’s egress check is not run either).

* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – On a non-200 response (with Freesound’s `detail`).

#### search(query, , license='cc0', k=15, duration_range=None, sort=None, page=1, kind='sfx', similar_to=None, ucs_category=None, provider_params=None, \*\*kw)

Search Freesound for `query`; return license-clean candidates.

The license filter is pushed into the native Solr `filter` so other sounds
never leave the server; every returned item is still re-checked fail-closed
before it becomes a candidate.

* **Parameters:**
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A licence id (`'cc0'` is an alias for CC0-1.0, `'cc-by'` keeps
    the CC-BY ids). `'cc0'` (default) sends the CC0 filter; another id asks
    for CC0 + Attribution; `None` sends no filter. Whatever the filter, only
    items under the asked id (and the `accepted_license_ids` allowlist) are
    kept, so NC / SA / ND never come back.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max results (Freesound caps `page_size` at 150).
  * **duration_range** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Optional `(min_s, max_s)` native duration filter.
  * **sort** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – `relevance` (default) | `newest` | `popular` | `duration`,
    translated to Freesound’s native key.
  * **page** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The results page (1-based, `k` per page).
  * **kind** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `sfx` (default, no filter) or `music` (the Broad Sound
    Taxonomy’s “Music” top level). With a `ucs_category` that maps to
    another top level it raises `SearchArgumentError` (nothing could match).
  * **similar_to** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A Freesound sound id (either id form): “more like this one”.
  * **ucs_category** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A UCS CatID or category, mapped to a coarse Broad Sound
    Taxonomy `category` pre-filter (no filter if it is not recognised;
    `SearchArgumentError` if `kind` asks for another top level).
  * **provider_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Native Freesound search params foley has no affordance
    for, merged over the translated ones (#61), e.g.
    `{"filter": "ac_brightness:[50 TO 100]"}`. Per the config’s
    `provider_params` policy, a `filter` is appended to foley’s as one
    group (the licence filter cannot be replaced or widened), `fields` are
    appended to foley’s (the licence fields cannot be dropped), and
    `query` is refused; the per-item licence re-check still applies.
  * **\*\*kw** – Ignored extra affordances (`on_unsupported_param='warn'`).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  Up to `k` [`Candidate`](foley.base.html.md#foley.base.Candidate)s (`origin=retrieved`),
  each carrying a by-reference [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), a
  transient `preview_uri` and the item JSON it was parsed from as `raw`.
