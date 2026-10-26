# foley.index

foley INDEX stage — make every sound findable by keyword *and* meaning.

The retrieval keystone (report 04 / report 10 §5): a CLAP joint embedding space,
a hybrid vector+keyword index with Reciprocal Rank Fusion, a `dol`-native
[`SoundLibrary`](#foley.index.SoundLibrary) façade composing the byte/metadata stores with the two
indexes, and the UCS/AudioSet taxonomy resolver — all behind small, swappable
protocols with zero-config defaults.

Everything heavy (`torch`/`transformers`/`lancedb`/`sqlite_vec`) is
lazy-imported inside the method that needs it, so `import foley.index` costs
only the stdlib; install the capability you use via the matching extra
(`foley[clap]`, `foley[index]`, `foley[index-sqlite]`).

### Functions

| [`default_embedder`](#foley.index.default_embedder)()                                 | Return a process-wide default [`ClapEmbedder`](#foley.index.ClapEmbedder) (loaded once, reused).   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| [`default_tagger`](#foley.index.default_tagger)()                                   | The default supervised tagger (PANNs CNN14; `foley[tag]`).                                                           |
| [`default_zeroshot_tagger`](#foley.index.default_zeroshot_tagger)([embedder])                | The default zero-shot tagger (CLAP vs UCS subcategories; `foley[clap]`).                                             |
| [`ingest_one`](#foley.index.ingest_one)(src, \*[, library, sound_id, ...])      | Ingest one clip into `library` and return an [`IngestResult`](#foley.index.IngestResult).          |
| [`ingest_folder`](#foley.index.ingest_folder)(path, \*[, library, recursive, ...]) | Ingest every audio file under `path` and return an [`IngestReport`](#foley.index.IngestReport).    |
| [`resolve_ingest_license`](#foley.index.resolve_ingest_license)(license, \*[, source_url])  | The rights record for a local ingest: fail-closed unless rights are asserted (#55).                                  |
| [`restamp_rights`](#foley.index.restamp_rights)([library, license, ids, ...])       | Re-stamp the licence of stored sounds; a dry run unless `apply=True`.                                                |
| [`default_index`](#foley.index.default_index)(\*, data_dir, dim)                   | Build the best available persistent index for a library.                                                             |
| [`lancedb_available`](#foley.index.lancedb_available)()                                | True if `lancedb` is importable (the `foley[index]` extra is present).                                               |
| [`sqlite_vec_loadable`](#foley.index.sqlite_vec_loadable)()                              | True if `sqlite_vec` is installed AND this interpreter can load it.                                                  |
| [`reciprocal_rank_fusion`](#foley.index.reciprocal_rank_fusion)(ranked_id_lists, \*[, k])   | Fuse several ranked id lists into one, by reciprocal rank.                                                           |
| [`fuse_hits`](#foley.index.fuse_hits)(vector_hits, keyword_hits, \*, k[, ...]) | RRF-fuse a vector ranker's hits with a keyword ranker's hits.                                                        |
| [`hybrid_search`](#foley.index.hybrid_search)(query, \*, embedder, vindex, kindex) | Embed `query`, run the vector + keyword rankers, and RRF-fuse them.                                                  |
| [`vector_search`](#foley.index.vector_search)(qvec, \*, vindex[, k, where])        | Pure audio<->audio (or clip->library) vector search — no keyword leg.                                                |
| [`default_library`](#foley.index.default_library)()                                  | The process-wide default library (local stores + CLAP + best index).                                                 |
| [`resolve_catid`](#foley.index.resolve_catid)(\*[, tags, caption, ...])            | Resolve inputs to a best UCS CatID by the staged precedence.                                                         |
| [`parse_ucs_filename`](#foley.index.parse_ucs_filename)(filename, \*[, table])          | Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.                                                |

### Classes

| [`Embedder`](#foley.index.Embedder)(\*args, \*\*kwargs)                      | A joint text<->audio embedding space (CLAP by default).                     |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`VectorIndex`](#foley.index.VectorIndex)(\*args, \*\*kwargs)                   | Approximate-nearest-neighbour store over embedding vectors.                 |
| [`KeywordIndex`](#foley.index.KeywordIndex)(\*args, \*\*kwargs)                  | BM25 / full-text index over each sound's tags + caption.                    |
| [`Tagger`](#foley.index.Tagger)(\*args, \*\*kwargs)                        | Map a clip to `(label, score)` pairs against a label vocabulary.            |
| [`Captioner`](#foley.index.Captioner)(\*args, \*\*kwargs)                     | Produce one natural-language sentence describing a clip (report 03).        |
| [`ClapEmbedder`](#foley.index.ClapEmbedder)([model_id, device, ...])             | LAION-CLAP text<->audio embedder (the default retrieval engine).            |
| [`ClapZeroShotTagger`](#foley.index.ClapZeroShotTagger)(\*[, embedder, labels, ...])   | Zero-shot tagger: score a clip against a label set via CLAP cosine.         |
| [`PannsTagger`](#foley.index.PannsTagger)(\*[, device, threshold])              | PANNs CNN14 supervised tagger over the 527 AudioSet classes (`foley[tag]`). |
| [`IngestResult`](#foley.index.IngestResult)(id, status[, record, qc, ...])       | The outcome of ingesting one clip.                                          |
| [`IngestReport`](#foley.index.IngestReport)(root[, results, notes])              | The rolled-up outcome of a folder ingest (JSON-serializable).               |
| [`MemoryIndex`](#foley.index.MemoryIndex)(\*[, dim])                            | In-memory vector + keyword index (numpy cosine + compact BM25).             |
| [`LanceIndex`](#foley.index.LanceIndex)(\*, uri, dim[, table_name])            | LanceDB-backed index: one table with a vector column + a native FTS index.  |
| [`SqliteVecIndex`](#foley.index.SqliteVecIndex)(\*, path, dim)                     | Single-file index: sqlite-vec `vec0` KNN + stdlib FTS5 keyword search.      |
| [`FusedHit`](#foley.index.FusedHit)(id[, rrf_score, clap_score, bm25_score]) | One fused retrieval hit: an id plus the scores that produced it.            |
| [`SoundLibrary`](#foley.index.SoundLibrary)(\*[, sounds, meta, vindex, ...])     | A searchable, license-aware library of sounds (the foley INDEX façade).     |
| [`CatIdResolution`](#foley.index.CatIdResolution)([catid, category, ...])           | The result of resolving free tags/caption/labels to a UCS CatID.            |

### *class* foley.index.Captioner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Produce one natural-language sentence describing a clip (report 03).

The caption feeds the BM25 keyword index and human display. Default is a
dedicated AAC model (EnCLAP); Qwen2-Audio is a richer promptable upgrade.
Both are `foley[caption]` adapters plugged in behind this protocol.

#### caption(wav, sr)

Return a one-sentence caption for the clip.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* foley.index.CatIdResolution(catid=None, category=None, subcategory=None, source=None, confidence=0.0, matched_terms=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of resolving free tags/caption/labels to a UCS CatID.

`catid` feeds `ucs_category` and
`subcategory` feeds `ucs_subcategory` on
ingest, and `ucs_catid` on the query side.

### *class* foley.index.ClapEmbedder(model_id='laion/larger_clap_general', , device=None, prompt_match_threshold=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LAION-CLAP text<->audio embedder (the default retrieval engine).

Returns **L2-normalized** `float32` embeddings so a plain inner product is
cosine similarity. `embed_text` always returns a 2-D `(n, dim)` array;
`embed_audio` returns a 1-D `(dim,)` array for one clip.

#### model_id

The HF checkpoint id.

#### dim

The embedding dimensionality.

#### open_source

Whether the checkpoint is an open-source model (the LAION
releases are). Read by the ingest AI-use gate for sounds whose rights
holder allows only open-source models (#69).

#### *property* device *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The resolved torch device string (`'cuda'`/`'cpu'`).

#### *property* dim *: [int](https://docs.python.org/3/builtins/functions.html#int)*

The embedding dimensionality (512 for the default; resolved for others).

For a non-default checkpoint this fetches only the model’s `config.json`
(via `AutoConfig`) — never the ~1.7 GB weights — so building an index
for it does not force a model download. Falls back to the loaded model’s
config if the standalone config lacks `projection_dim`.

#### embed_audio(wav, sr)

Embed one audio clip -> `(dim,)` L2-normalized.

The clip is down-mixed to mono and resampled to 48 kHz (what CLAP expects)
via [`foley.audio`](foley.audio.html.md#module-foley.audio) before embedding.

* **Parameters:**
  * **wav** (`ndarray`) – A working-array clip (`float32`; mono or multichannel).
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The clip’s sample rate in Hz.
* **Return type:**
  `ndarray`

#### embed_text(text)

Embed one or more query strings -> `(n_texts, dim)` L2-normalized.

* **Return type:**
  `ndarray`

#### *property* prompt_match_threshold *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Cosine similarity under which a generated clip is flagged as not matching its prompt.

Calibrated per checkpoint on a labelled set ([`foley.eval.prompt_match`](foley.eval.prompt_match.html.md#module-foley.eval.prompt_match),
`foley/data/prompt_match/thresholds.json`); a checkpoint nobody has calibrated
gets `PROVISIONAL_PROMPT_MATCH_THRESHOLD`.

### *class* foley.index.ClapZeroShotTagger(, embedder=None, labels=None, prompt='this is a sound of {label}', threshold=0.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Zero-shot tagger: score a clip against a label set via CLAP cosine.

Reuses a [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder) (the same model the
Index uses), so the audio is embedded in the same joint space as the label
prompts and no extra weights load. The default label set is the UCS
subcategory names (foley’s own vocabulary), so tags land in-taxonomy.

#### *property* embedder

The CLAP embedder (injected or the process-wide default).

#### *property* labels *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

natural UCS `category subcategory` phrases).

Natural multi-word phrases (`"weather rain"`, `"glass break"`) are far
better CLAP prompts — and better BM25 tags / taxonomy-resolver input — than
bare abstract subcategory words (`"Break"`, `"Buzz"`), which are a known
zero-shot artifact (anomalously close to everything). Absolute tag-quality
calibration (thresholds, label curation) is an eval-harness concern (#10).

* **Type:**
  The label vocabulary ([*default*](foley.html.md#foley.Affordance.default)

#### tag(wav, sr, , taxonomy='custom', top_k=10)

Return the top-`k` `(label, cosine)` tags for the clip, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### tag_vector(audio_vec, , top_k=10)

Score a **precomputed** (L2-normalized) audio vector against the labels.

The efficiency seam (report 03 Part 2): the Index already embeds every
sound with this model, so on ingest the retrieval vector is reused here —
no second CLAP forward pass.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### *class* foley.index.Embedder(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

A joint text<->audio embedding space (CLAP by default).

One space serves both text->audio search (`embed_text` a query) and
audio<->audio similarity (`embed_audio` a clip). Implementations MUST
return **L2-normalized** `float32` arrays so a plain inner product is
cosine similarity, and MUST stamp `model_id`/`dim` so mixed-model
libraries stay coherent (each [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) records the
`embedding_model`/`embedding_dim` it was indexed under).

#### model_id

The checkpoint id (e.g. `'laion/larger_clap_general'`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### dim

The embedding dimensionality (e.g. `512`).

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### embed_audio(wav, sr)

Embed one audio clip.

* **Parameters:**
  * **wav** (`ndarray`) – A working-array clip (`float32`, mono preferred). CLAP expects
    48 kHz; implementations resample as needed.
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The clip’s sample rate in Hz.
* **Return type:**
  `ndarray`
* **Returns:**
  A 1-D `(dim,)` L2-normalized `float32` array.

#### embed_text(text)

Embed one or more query strings.

* **Parameters:**
  **text** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – A single string or a list of strings.
* **Return type:**
  `ndarray`
* **Returns:**
  A 2-D `(n_texts, dim)` L2-normalized `float32` array (`n_texts`
  is `1` for a single string) — always 2-D so callers can index
  `[0]` for the single-query case.

### *class* foley.index.FusedHit(id, rrf_score=None, clap_score=None, bm25_score=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One fused retrieval hit: an id plus the scores that produced it.

The raw component scores are carried through (not just the fused rank score)
so the façade can stamp them onto a [`Candidate`](foley.base.html.md#foley.base.Candidate)
(`clap_score` / `bm25_score` / `rrf_score`) for display and debugging.

#### id

The sound id.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### rrf_score

The fused RRF score (`None` for a pure-vector search).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### clap_score

Cosine similarity from the vector ranker (`None` if the id
appeared only in the keyword list).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### bm25_score

BM25 score from the keyword ranker (`None` if the id
appeared only in the vector list).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### *class* foley.index.IngestReport(root, results=list(), notes=list())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The rolled-up outcome of a folder ingest (JSON-serializable).

#### error(path, exc)

Record a per-file error without aborting the run.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* errored *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results that raised during ingest.

#### exception *= None*

The exception behind the last `error` result, kept so a raising façade can
chain it (`raise ... from`); a plain attribute, never serialized.

#### *property* ingested *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results that were added to the library (`pass` or `warn`).

#### *property* quarantined *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results rejected by the QC gate.

#### record(result)

Append one [`IngestResult`](#foley.index.IngestResult).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* rights_blocked *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results refused by the fail-closed AI-training/license rights gate.

#### *property* skipped *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results skipped as content-addressed duplicates.

#### summary()

A counts dict for a console/CLI summary.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.index.IngestResult(id, status, record=None, qc=None, notes=list(), error=None, cost_estimate_usd=None, cost_actual_usd=None, cache_key=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The outcome of ingesting one clip.

`status`: `'pass'`/`'warn'` (ingested), `'quarantined'` (QC-rejected,
not added), `'skipped_dup'` (content already in the library),
`'rights_blocked'` (license forbids AI training / embedding, refused before
embed — see [`ingest_one()`](#foley.index.ingest_one)), `'skipped_license'` (dropped by a
bootstrap commercial-use / fail-closed license filter), or `'error'`.
`record` is present only when the clip was ingested. `cache_key` is set by
[`foley.generate()`](foley.html.md#foley.generate) to the key its paid bytes were kept under in the generations
cache (`foley.generations.get(cache_key)`), whatever the outcome — a quarantined
generation is retrievable, since it was billed either way (#107). It is the
content key of the provider’s bytes as received (their sha256) — not `id` (the
decoded-PCM hash) nor `record.content_sha256` (the stored FLAC archive’s), and
not the request digest the notes name (which also resolves through `get`).

#### audio_bytes *= None*

what the
library would have served. A plain attribute, never serialized (like
`IngestReport.exception`), so `to_dict`/`to_json` stay byte-free.

* **Type:**
  The archive bytes of a clip assembled but not stored (`store=False`)

#### raw *= None*

What the provider returned besides the audio of a generation (#61; see
[`foley.sources.base.GeneratedClip.raw`](foley.sources.base.html.md#foley.sources.base.GeneratedClip.raw)). A plain attribute, never serialized.

### *class* foley.index.KeywordIndex(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

BM25 / full-text index over each sound’s tags + caption.

The default is LanceDB’s Tantivy FTS (report 04 §3.4); SQLite FTS5 is the
single-file fallback. Same `where` push-down contract as
[`VectorIndex`](#foley.index.VectorIndex).

#### bm25(query, k, , where=None)

Return the top-`k` BM25 matches for `query`, best first.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A natural-language / keyword query.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of matches to return.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata predicates for push-down filtering.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, bm25_score), ...]` in descending-score order.

#### index(id, text, meta)

Insert or replace the searchable text (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.index.LanceIndex(, uri, dim, table_name='sounds')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LanceDB-backed index: one table with a vector column + a native FTS index.

Writes are staged per id and flushed on the next read (or explicit
[`commit()`](#foley.index.LanceIndex.commit)), so a sound’s vector ([`upsert()`](#foley.index.LanceIndex.upsert)) and text ([`index()`](#foley.index.LanceIndex.index))
— which arrive as two separate protocol calls — are merged into one row and
written as an efficient batch. Vector search is exact cosine (no ANN index is
built at this tier; adding one is a scale-time optimization). Fusion is done
by [`foley.index.search`](foley.index.search.html.md#module-foley.index.search), not by LanceDB’s native hybrid reranker, so
ranking matches every other backend.

One-table constraint: the vector column is mandatory, so \*\*every indexed row
needs a vector\*\*. `SoundLibrary.add` enforces this (it raises without an
embedding source), so the façade path is safe; a bare `index()` with no
matching `upsert()` stages a text-only row that stays unflushed (never
keyword-searchable). For a keyword-only library with no embeddings, use
[`MemoryIndex`](#foley.index.MemoryIndex) or [`SqliteVecIndex`](#foley.index.SqliteVecIndex) (independent vector/text tables).

#### bm25(query, k, , where=None)

Native full-text (BM25) search; returns `[(id, score), ...]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### commit()

Flush all staged writes to the LanceDB table.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* db

The lazily-connected LanceDB database handle.

#### get_vector(id)

Return the stored vector for `id` (staged or persisted), else `None`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### index(id, text, meta)

Stage the searchable text for `id` (flushed on the next read/commit).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### knn(vector, k, , where=None)

Exact cosine KNN; returns `[(id, cosine_similarity), ...]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### *property* table

The lazily-opened (or created-empty) LanceDB table.

#### upsert(id, vector, meta)

Stage the vector for `id` (flushed on the next read/commit).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.index.MemoryIndex(, dim=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

In-memory vector + keyword index (numpy cosine + compact BM25).

Not persistent — everything lives in dicts, lost on process exit. It exists
so the full hybrid + façade path is testable and usable with only `numpy`
(no LanceDB, no torch), and as a genuine zero-config tier for small or
ephemeral libraries. The vector and text stores are independent dicts, so
[`upsert()`](#foley.index.MemoryIndex.upsert) and [`index()`](#foley.index.MemoryIndex.index) never contend.

#### bm25(query, k, , where=None)

Return the top-`k` BM25 matches for `query` (best first).

A compact Okapi BM25 (`k1=1.5`, `b=0.75`) recomputed per query — O(N)
in the corpus size, which is fine for the in-memory tier’s scale.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### commit()

No-op (writes are immediate); present for interface symmetry.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### get_vector(id)

Return the stored vector for `id` (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### index(id, text, meta)

Insert or replace the searchable text (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### knn(vector, k, , where=None)

Return the `k` cosine-nearest ids to `vector` (most-similar first).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### upsert(id, vector, meta)

Insert or replace the vector (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.index.PannsTagger(, device='cpu', threshold=0.1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

PANNs CNN14 supervised tagger over the 527 AudioSet classes (`foley[tag]`).

The checkpoint auto-downloads to `~/panns_data` (~327 MB) on the first
[`tag()`](#foley.index.PannsTagger.tag). PANNs expects 32 kHz mono; the clip is resampled via
[`foley.audio.to_working()`](foley.audio.html.md#foley.audio.to_working).

#### tag(wav, sr, , taxonomy='audioset', top_k=10)

Return the top-`k` `(AudioSet label, score)` tags, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### *class* foley.index.SoundLibrary(, sounds=None, meta=None, vindex=None, kindex=None, embedder=None, data_dir=None, candidate_k=50, rrf_k=60)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

A searchable, license-aware library of sounds (the foley INDEX façade).

Read it as a `Mapping` of `SoundRecord`s; search it with
:meth:`search` (text) / [`search_clip()`](#foley.index.SoundLibrary.search_clip) (a reference clip) / [`similar()`](#foley.index.SoundLibrary.similar)
(audio<->audio by id); browse it with [`filter()`](#foley.index.SoundLibrary.filter); grow it with [`add()`](#foley.index.SoundLibrary.add).

#### add(record, , data=None, vector=None)

Store a sound and index it (the ingest write path).

Persists bytes via [`store_sound()`](foley.stores.html.md#foley.stores.store_sound) (honouring the
by-value/by-reference license gate), upserts the CLAP vector into the
vector index, and indexes `caption``+``tags` into the keyword index.

A sound is retrieval-first, so it MUST carry an embedding: supply either
`data` (bytes to embed — note a by-reference sound is embedded from its
transient bytes even though they are not cached) or a precomputed
`vector`. Adding with neither raises, rather than silently indexing a
vectorless row (which the single-table [`LanceIndex`](#foley.index.LanceIndex) cannot persist,
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

Accepts the same facet keywords as [`search()`](foley.index.search.html.md#module-foley.index.search)’s filters
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

### *class* foley.index.SqliteVecIndex(, path, dim)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Single-file index: sqlite-vec `vec0` KNN + stdlib FTS5 keyword search.

The whole index is one SQLite file behind two virtual tables (independent, so
[`upsert()`](#foley.index.SqliteVecIndex.upsert) and [`index()`](#foley.index.SqliteVecIndex.index) never contend). \*\*Requires an interpreter
whose `sqlite3` permits loadable extensions\*\* — probe with
[`sqlite_vec_loadable()`](#foley.index.sqlite_vec_loadable) before constructing; the constructor raises a
clear error otherwise.

#### bm25(query, k, , where=None)

FTS5 BM25 search; returns `[(id, score), ...]` best-first.

FTS5’s `rank` is more-negative-is-better; it is negated so the returned
score is larger-is-better (consistent with the other backends).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### close()

Close the underlying SQLite connection.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### commit()

Commit any pending SQLite transaction (writes auto-commit already).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### get_vector(id)

Return the stored vector for `id` (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### index(id, text, meta)

Insert or replace the searchable text for `id` in the FTS5 table.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### knn(vector, k, , where=None)

KNN over `vec0` (cosine); returns `[(id, cosine_similarity), ...]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### upsert(id, vector, meta)

Insert or replace the vector for `id` in the `vec0` table.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.index.Tagger(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Map a clip to `(label, score)` pairs against a label vocabulary.

Used on ingest to auto-fill `SoundRecord.audioset_labels` (supervised) and
`tags` (zero-shot). The default supervised tagger is PANNs CNN14 over
AudioSet; the default zero-shot tagger scores a clip against a custom/UCS
label set via CLAP (report 03). BEATs/AST are drop-in upgrades. Consumes the
working array (`float32`, any sr — the impl resamples to its model’s rate).

#### tag(wav, sr, , taxonomy='audioset', top_k=10)

Return the top-`k` `(label, score)` tags for the clip, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### *class* foley.index.VectorIndex(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Approximate-nearest-neighbour store over embedding vectors.

The default is LanceDB (report 04 §2); Qdrant/pgvector/sqlite-vec bind the
same protocol behind the scenes. `where` is an optional metadata push-down
the façade may pass; a backend that cannot push filters down MAY ignore it
(the façade over-fetches and post-filters to stay correct either way).

#### get_vector(id)

Return the stored vector for `id` (or `None` if absent).

Needed by `SoundLibrary.similar` (fetch a sound’s own vector, then run
[`knn()`](#foley.index.VectorIndex.knn)) and by the optional CLAP rerank (score keyword-only hits).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### knn(vector, k, , where=None)

Return the `k` nearest ids to `vector`, most-similar first.

* **Parameters:**
  * **vector** (`ndarray`) – A `(dim,)` query vector (already L2-normalized).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of neighbours to return.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata predicates for push-down filtering.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, cosine_similarity), ...]` in descending-similarity order.

#### upsert(id, vector, meta)

Insert or replace the vector (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.index.default_embedder()

Return a process-wide default [`ClapEmbedder`](#foley.index.ClapEmbedder) (loaded once, reused).

Cached so repeated `foley.search()` calls share a single loaded model.

* **Return type:**
  [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder)

### foley.index.default_index(, data_dir, dim)

Build the best available persistent index for a library.

Degradation ladder: LanceDB (`foley[index]`) → sqlite-vec
(`foley[index-sqlite]`, if loadable) → an informative error. The
non-persistent [`MemoryIndex`](#foley.index.MemoryIndex) is never chosen automatically (a library
must survive restarts); inject it explicitly for tests/ephemeral use.

* **Parameters:**
  * **data_dir** – The library data root (a `pathlib.Path`-like).
  * **dim** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The embedding dimensionality from the active embedder.
* **Returns:**
  A ready index object (both `VectorIndex` and `KeywordIndex`).
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If no persistent backend is installed/usable.

### foley.index.default_library()

The process-wide default library (local stores + CLAP + best index).

* **Return type:**
  [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary)

### foley.index.default_tagger()

The default supervised tagger (PANNs CNN14; `foley[tag]`).

* **Return type:**
  [`PannsTagger`](foley.index.taggers.html.md#foley.index.taggers.PannsTagger)

### foley.index.default_zeroshot_tagger(embedder=None)

The default zero-shot tagger (CLAP vs UCS subcategories; `foley[clap]`).

Cached **per embedder** so the tagger is bound to the SAME embedder that
produced the audio vector it scores — otherwise (report seam) the cosine would
cross two unrelated embedding spaces. `embedder=None` uses the process-wide
default embedder.

* **Return type:**
  [`ClapZeroShotTagger`](foley.index.taggers.html.md#foley.index.taggers.ClapZeroShotTagger)

### foley.index.fuse_hits(vector_hits, keyword_hits, , k, rrf_k=60)

RRF-fuse a vector ranker’s hits with a keyword ranker’s hits.

* **Parameters:**
  * **vector_hits** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(id, cosine_similarity), ...]` best-first (from
    [`knn()`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex.knn)).
  * **keyword_hits** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(id, bm25_score), ...]` best-first (from
    [`bm25()`](foley.index.protocols.html.md#foley.index.protocols.KeywordIndex.bm25)).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of fused hits to return.
  * **rrf_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](foley.index.search.html.md#foley.index.search.FusedHit)]
* **Returns:**
  The top-`k` :class:

  ```
  `
  ```

  FusedHit\`s, each carrying its raw component scores.

### foley.index.hybrid_search(query, , embedder, vindex, kindex, k=10, candidate_k=50, rrf_k=60, where=None)

Embed `query`, run the vector + keyword rankers, and RRF-fuse them.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language query.
  * **embedder** ([`Embedder`](foley.index.protocols.html.md#foley.index.protocols.Embedder)) – Text<->audio embedder (its `embed_text` produces the query
    vector).
  * **vindex** ([`VectorIndex`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex)) – The vector index (CLAP KNN).
  * **kindex** ([`KeywordIndex`](foley.index.protocols.html.md#foley.index.protocols.KeywordIndex)) – The keyword index (BM25).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of fused results to return.
  * **candidate_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Shortlist depth pulled from each ranker before fusion.
  * **rrf_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata push-down passed to both rankers.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](foley.index.search.html.md#foley.index.search.FusedHit)]
* **Returns:**
  The top-`k` fused :class:

  ```
  `
  ```

  FusedHit\`s.

### foley.index.ingest_folder(path, , library=None, recursive=True, exts=('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.opus', '.m4a'), on_error='collect', \*\*ingest_one_kw)

Ingest every audio file under `path` and return an [`IngestReport`](#foley.index.IngestReport).

* **Parameters:**
  * **path** – A folder (walked) or a single audio file.
  * **library** – Target library (default: the process-wide default).
  * **recursive** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Recurse into sub-folders.
  * **exts** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – Audio extensions to ingest.
  * **on_error** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'collect'` records per-file errors and continues;
    `'raise'` re-raises the first error. Either way an
    [`EgressBlocked`](foley.runtime.html.md#foley.runtime.EgressBlocked) (offline, the embedder’s weights not
    cached) raises at once: every file would fail the same way.
  * **\*\*ingest_one_kw** – Forwarded to [`ingest_one()`](#foley.index.ingest_one) (license, taggers, QC
    flags, …).
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](#foley.index.IngestReport) (with `.summary()` counts and per-file results).

### foley.index.ingest_one(src, , library=None, sound_id=None, source_uri=None, license=None, tagger=None, zeroshot_tagger=None, captioner=None, do_qc=True, min_status=QCStatus.warn, do_supervised=True, do_zeroshot=True, do_caption=True, thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100), store=True, allow_ai_training_forbidden=False, seed_tags=None, commercial=None)

Ingest one clip into `library` and return an [`IngestResult`](#foley.index.IngestResult).

Pipeline: probe + decode-once -> content-address dedup -> QC gate -> embed
(once) -> supervised + zero-shot tags -> caption -> resolve UCS -> assemble
`SoundRecord` -> [`SoundLibrary.add()`](#foley.index.SoundLibrary.add).

* **Parameters:**
  * **src** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – A path, `bytes`, or file-like audio source.
  * **library** – Target [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the
    process-wide default library).
  * **sound_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional canonical id override. Defaults to `None` → the
    content-hash of the decoded PCM (the local-ingest identity, used as the
    record `id` and dedup key). A live source adapter passes a short,
    case-stable, source-native id (e.g. `'freesound:12345'`) so dedup keys
    on the stable id rather than on re-fetched (lossy, byte-varying) preview
    bytes; when it does, the PCM hash is computed only for the (skipped)
    default and is not persisted. Separately, `content_sha256` records the
    hash of the stored FLAC **archive** bytes (set by `store_sound`), which
    is a different byte source from this PCM hash.
  * **source_uri** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional by-reference fetchable URI override. Defaults to
    `None` → the resolved local path when `src` is path-like. A live
    adapter passes the stable source page URL (e.g.
    `'https://freesound.org/s/12345/'`) that [`foley.stores.store_sound()`](foley.stores.html.md#foley.stores.store_sound)
    requires for a by-reference sound.
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – Rights record, or a `license_id` string the caller asserts
    (`'user-owned'`), or `None` (default): rights **unknown**, so the clip
    is indexed but [`foley.keep()`](foley.html.md#foley.keep) refuses it (#55). See
    [`resolve_ingest_license()`](#foley.index.resolve_ingest_license).
  * **tagger** – Supervised [`Tagger`](foley.index.protocols.html.md#foley.index.protocols.Tagger) (default: PANNs
    via [`default_tagger()`](foley.index.taggers.html.md#foley.index.taggers.default_tagger)).
  * **zeroshot_tagger** – Zero-shot tagger (default: CLAP via
    [`default_zeroshot_tagger()`](foley.index.taggers.html.md#foley.index.taggers.default_zeroshot_tagger)).
  * **captioner** – Optional [`Captioner`](foley.index.protocols.html.md#foley.index.protocols.Captioner) (default:
    none — the caption stage is off unless one is injected).
  * **do_qc** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Run the Tier-0 QC gate.
  * **min_status** ([`QCStatus`](foley.qc.html.md#foley.qc.QCStatus)) – Admission floor — a QC status worse than this is quarantined
    (default `warn`: only `fail` clips are rejected).
  * **do_caption** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Toggle each enrichment stage.
  * **thresholds** ([`QCThresholds`](foley.qc.html.md#foley.qc.QCThresholds)) – QC thresholds.
  * **store** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `False`, assemble the record but do not add it to the library
    (probe/QC/enrich only — a preview). The result’s `audio_bytes` then
    carries the archive bytes the library would have stored, and an
    enrichment stage whose optional extra is absent (the `foley[clap]`
    embedder) is skipped with a note rather than failing: a preview is never
    indexed, so it never needs the vector (#107).
  * **seed_tags** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)]) – Optional caller-supplied tags (e.g. a corpus’s folder-path
    taxonomy) unioned into the record’s `tags` alongside the
    supervised/zero-shot tags — so they feed the BM25 keyword index.
  * **allow_ai_training_forbidden** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – The universal fail-closed rights gate. A
    sound whose license has `ai_training_ok=False` (e.g. Sonniss,
    BBC RemArc) is refused with status `'rights_blocked'` *before* it is
    embedded or stored — CLAP-embedding-and-persisting is itself a form of
    AI training on the corpus. Pass `True` to record explicit operator
    consent and admit it anyway (see `foley.bootstrap.bootstrap()`’s
    `accept_ai_restricted`). Protects every ingest path, not just
    bootstrap.
  * **commercial** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Whether the AI use is for a commercial purpose (decides a
    `nc_open_source_only` scope, #69). `None` (default) means
    [`DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE)’s (commercial).
* **Return type:**
  [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult)
* **Returns:**
  An [`IngestResult`](#foley.index.IngestResult); its `record` is `None` when quarantined, a
  duplicate, or rights-blocked.

### foley.index.lancedb_available()

True if `lancedb` is importable (the `foley[index]` extra is present).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.parse_ucs_filename(filename, , table=None)

Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.

Fail-quiet: returns `(None, None)` when the name is not UCS-conformant or
its CatID token is unknown (so a wrong subcategory is never emitted).

* **Parameters:**
  * **filename** – A path or filename (only the basename’s token 0 is used).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table to resolve against (defaults to
    `default_ucs_table()`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.index.reciprocal_rank_fusion(ranked_id_lists, , k=60)

Fuse several ranked id lists into one, by reciprocal rank.

* **Parameters:**
  * **ranked_id_lists** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Each element is a list of ids in descending-relevance
    order (best first). Lists may overlap and may differ in length.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant (default `RRF_K` = 60).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, fused_score), ...]` sorted by fused score descending, ties
  broken by `id` ascending (so the fusion is fully deterministic).

### foley.index.resolve_catid(, tags=(), caption=None, audioset_labels=(), filename=None, table=None, audioset_map=None)

Resolve inputs to a best UCS CatID by the staged precedence.

* **Parameters:**
  * **tags** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free tags on the sound.
  * **caption** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free-text caption/description.
  * **audioset_labels** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – AudioSet MIDs or names (e.g. from PANNs).
  * **filename** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional UCS-style filename/path (its token-0 CatID wins if
    recognized).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – UCS table (defaults to `default_ucs_table()`).
  * **audioset_map** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)]) – AudioSet->UCS map (defaults to
    [`default_audioset_ucs_map()`](foley.index.taxonomy.audioset.html.md#foley.index.taxonomy.audioset.default_audioset_ucs_map)).
* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)
* **Returns:**
  A [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution) (falsy when
  nothing resolved).

### foley.index.resolve_ingest_license(license, , source_url=None)

The rights record for a local ingest: fail-closed unless rights are asserted (#55).

* `None` (no licence given) → `license_id='unknown'`, `rights_verified=False`:
  [`foley.keep()`](foley.html.md#foley.keep) refuses it for every use. The bytes are still kept locally
  > (`cache_bytes_ok=True`: it is the user’s own disk, no terms of service apply),
  > so the clip is searchable and can be re-stamped later without re-ingesting.
* a `str` → that `license_id`, which must be a `LICENSE_FLAGS` row, with
  `rights_verified=True` (the caller is asserting it) and `verified_at` set —
  e.g. `'user-owned'` for the user’s own recordings.
* a [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) → used as given.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If a `str` licence id has no `LICENSE_FLAGS` row.
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.index.restamp_rights(library=None, , license='unknown', ids=None, where=None, select='legacy-user-owned', apply=False)

Re-stamp the licence of stored sounds; a dry run unless `apply=True`.

The migration for libraries built before #55 / #56. A re-ingest does not do it
(content-addressed dedup skips files already stored), so this rewrites the stored
records in place:

* `foley restamp-rights --apply` — every sound an older foley stamped
  `user-owned` without being told becomes `unknown` (fail closed);
* `foley restamp-rights --license user-owned --apply` — the same sounds, but you
  assert that you own them (now recorded with a `verified_at` timestamp);
* `foley restamp-rights --select legacy-elevenlabs --license elevenlabs-paid-plan
  --apply` — ElevenLabs generations made before the plan was explicit;
* `foley restamp-rights --select has-license-url --license from-url --apply` —
  every record that kept its source’s licence string (Freesound pulls) is
  re-derived by today’s mapper (CC versions, PDM, NC spellings);
* corpus clips (Clotho, FSD50K) are repaired by re-running `foley bootstrap`,
  which re-stamps already-stored clips from the corpus metadata.

* **Parameters:**
  * **library** – The [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the default one).
  * **license** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `license_id` to stamp (a `LICENSE_FLAGS` row; default
    `'unknown'`), or `FROM_LICENSE_URL` to re-derive each record from
    its own `license_url`.
  * **ids** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Re-stamp exactly these sound ids (overrides `where` / `select`).
  * **where** – A predicate `LicenseRecord -> bool` choosing the records (overrides
    `select`).
  * **select** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A `LEGACY_SELECTORS` name (default `'legacy-user-owned'`).
  * **apply** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Write the change. `False` (default) only reports what would change.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The ids that were (or, in a dry run, would be) re-stamped.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `license` or `select` is unknown.

### foley.index.sqlite_vec_loadable()

True if `sqlite_vec` is installed AND this interpreter can load it.

The macOS system / pyenv CPython builds frequently ship a `sqlite3` without
loadable-extension support (no `enable_load_extension`); on those,
sqlite-vec cannot be used even when 

```
``
```

pip install\`\`ed. This probes both.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.vector_search(qvec, , vindex, k=10, where=None)

Pure audio<->audio (or clip->library) vector search — no keyword leg.

Used by `SoundLibrary.similar` and by searching with a reference clip.
Hits keep their cosine similarity in `clap_score` and preserve the index’s
own descending-similarity order (`rrf_score` is left `None` — there is no
fusion).

* **Parameters:**
  * **qvec** (`ndarray`) – An already-L2-normalized `(dim,)` query vector.
  * **vindex** ([`VectorIndex`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex)) – The vector index.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of neighbours to return.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata push-down.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](foley.index.search.html.md#foley.index.search.FusedHit)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  FusedHit\`s in descending-similarity order.

### Modules

| [`taxonomy`](foley.index.taxonomy.html.md#module-foley.index.taxonomy)   | UCS + AudioSet taxonomy: the `tags -> UCS CatID` resolver for foley.                       |
|-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`embedders`](foley.index.embedders.html.md#module-foley.index.embedders) | Embedders — the joint text<->audio space that powers retrieval.                            |
| [`indexes`](foley.index.indexes.html.md#module-foley.index.indexes)     | Concrete vector + keyword index backends (the swappable retrieval engines).                |
| [`ingest`](foley.index.ingest.html.md#module-foley.index.ingest)       | The ingestion pipeline — turn any audio file into a searchable SoundRecord.                |
| [`library`](foley.index.library.html.md#module-foley.index.library)     | The `SoundLibrary` façade — one searchable, license-aware sound library.                   |
| [`onnx_clap`](foley.index.onnx_clap.html.md#module-foley.index.onnx_clap) | CLAP on a small host: the same checkpoint through ONNX Runtime, no torch, no transformers. |
| [`protocols`](foley.index.protocols.html.md#module-foley.index.protocols) | Structural contracts for the foley index (the retrieval boundary).                         |
| [`search`](foley.index.search.html.md#module-foley.index.search)       | Hybrid retrieval: reciprocal rank fusion over a vector list and a keyword list.            |
| [`taggers`](foley.index.taggers.html.md#module-foley.index.taggers)     | Taggers — auto-fill a sound's semantic labels on ingest (report 03).                       |
