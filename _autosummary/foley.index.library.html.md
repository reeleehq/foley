# foley.index.library

The `SoundLibrary` façade — one searchable, license-aware sound library.

Composes the four injected storage concerns behind a stable interface (report
04 §6.1), so each swaps local->cloud with no change to retrieval logic:

```default
SoundLibrary
├── sounds : Mapping[content_key -> bytes]   # audio blobs   (dol.Files -> S3)
├── meta   : Mapping[id -> SoundRecord]       # canonical SSOT (JSON -> S3/PG)
├── vindex : VectorIndex                      # CLAP 512-d    (LanceDB/sqlite/memory)
└── kindex : KeywordIndex (BM25)              # tags+caption  (same, or separate)
```

Progressive disclosure: `SoundLibrary()` works out of the box with sensible
local defaults (all components lazily constructed), while every store, index, and
the embedder is an optional keyword injection (open-closed). The library is a
read-only `Mapping` of `SoundRecord`s (``lib[sound_id]``);
`add()` is the write path that stores bytes and updates both indexes.

`search` embeds the query, runs the vector KNN and the BM25 keyword search, and
RRF-fuses them ([`foley.index.search`](foley.index.search.html.md#module-foley.index.search)) — nothing here changes between the
in-memory, LanceDB, or sqlite backends, or between local and cloud storage.

### Functions

| [`default_library`](#foley.index.library.default_library)()   | The process-wide default library (local stores + CLAP + best index).   |
|----------------------------------------------------------------------|------------------------------------------------------------------------|

### Classes

| [`SoundLibrary`](#foley.index.library.SoundLibrary)(\*[, sounds, meta, vindex, ...])   | A searchable, license-aware library of sounds (the foley INDEX façade).   |
|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|

### *class* foley.index.library.SoundLibrary(, sounds=None, meta=None, vindex=None, kindex=None, embedder=None, data_dir=None, candidate_k=50, rrf_k=60)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

A searchable, license-aware library of sounds (the foley INDEX façade).

Read it as a `Mapping` of `SoundRecord`s; search it with
:meth:`search` (text) / [`search_clip()`](#foley.index.library.SoundLibrary.search_clip) (a reference clip) / [`similar()`](#foley.index.library.SoundLibrary.similar)
(audio<->audio by id); browse it with [`filter()`](#foley.index.library.SoundLibrary.filter); grow it with [`add()`](#foley.index.library.SoundLibrary.add).

#### add(record, , data=None, vector=None)

Store a sound and index it (the ingest write path).

Persists bytes via [`store_sound()`](foley.stores.html.md#foley.stores.store_sound) (honouring the
by-value/by-reference license gate), upserts the CLAP vector into the
vector index, and indexes `caption``+``tags` into the keyword index.

A sound is retrieval-first, so it MUST carry an embedding: supply either
`data` (bytes to embed — note a by-reference sound is embedded from its
transient bytes even though they are not cached) or a precomputed
`vector`. Adding with neither raises, rather than silently indexing a
vectorless row (which the single-table `LanceIndex` cannot persist,
producing backend-dependent search results).

* **Parameters:**
  * **record** ([`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)) – The record to add (mutated by `store_sound` with resolved
    storage fields, and stamped with the embedding model/dim).
  * **data** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The archive bytes (required for by-value storage; also the
    source for computing `vector` when it is not supplied).
  * **vector** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]) – A precomputed CLAP embedding; when omitted and `data` is
    given, it is computed via the library’s embedder.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)
* **Returns:**
  The same (persisted, indexed) `record`.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If neither `data` nor `vector` is provided (no way to
      obtain an embedding).

#### array(sound_id, , sr=None, mono=True)

Decode a sound to a working array (`float32`).

* **Parameters:**
  * **sound_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The record id.
  * **sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Target sample rate (default: the working rate, 48 kHz).
  * **mono** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Down-mix to mono (default `True`).
* **Return type:**
  `ndarray`
* **Returns:**
  The decoded working array.

#### audio(sound_id)

Return a sound’s archive bytes (by-value from the store, or from a
local by-reference path).

* **Parameters:**
  **sound_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The record id.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
* **Returns:**
  The raw archive bytes.
* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the bytes are neither cached (by-value) nor readable
      from a local `uri` — a remote by-reference sound needs its
      source adapter (subtask #5) to fetch.

#### *property* data_dir *: [Path](https://docs.python.org/3/library/pathlib.html#pathlib.Path)*

The data root for default stores/index.

#### *property* embedder

The text<->audio embedder (CLAP by default).

#### filter(\*\*facets)

Browse the library by metadata facets (no ranking).

Accepts the same facet keywords as [`search()`](#foley.index.library.SoundLibrary.search)’s filters
(`commercial_ok`, `ucs_category`, `min_snr`, `duration_range`)
plus any `record_attr=value` equality predicate.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)]

#### *property* kindex

The keyword index.

#### *property* meta

The metadata store (`id -> SoundRecord`).

#### search(query, , k=10, filters=None, commercial_ok=None, ucs_category=None, min_snr=None, duration_range=None, rerank=False)

Hybrid (CLAP vector ⊕ BM25) search for a text query.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language query.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of results to return.
  * **filters** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Extra `{record_attr: value}` equality predicates.
  * **commercial_ok** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – If `True`, keep only commercially-usable sounds.
  * **ucs_category** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Keep only sounds with this UCS CatID.
  * **min_snr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Keep only sounds whose QC `snr_db` is at least this.
  * **duration_range** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Keep only sounds whose `duration_s` is in
    `(min, max)`.
  * **rerank** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Re-order the shortlist by direct query<->audio cosine
    (fills the CLAP score for keyword-only hits).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  ~foley.base.Candidate\`s, best first.

#### search_clip(clip, , sr=None, k=10)

Search by a reference audio clip (audio<->audio via CLAP).

* **Parameters:**
  * **clip** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – A working array, or a path/bytes/file decodable by
    [`foley.audio.load()`](foley.audio.html.md#foley.audio.load).
  * **sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Sample rate when `clip` is already a working array.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of results.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  ~foley.base.Candidate\`s, most-similar first.

#### similar(sound_id, , k=10)

Return the `k` sounds most similar to `sound_id` (audio<->audio).

Uses the stored vector (no re-decoding); the query sound itself is
excluded from the results.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

#### *property* sounds

The content-addressed byte store.

#### update_record(record)

Rewrite a stored record’s metadata and re-index its keyword text.

For corrections that do not touch the audio (a re-stamped licence, a removed
caption): the bytes and the CLAP vector stay as they are.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If `record.id` is not in the library.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### *property* vindex

The vector index.

### foley.index.library.default_library()

The process-wide default library (local stores + CLAP + best index).

* **Return type:**
  [`SoundLibrary`](#foley.index.library.SoundLibrary)
