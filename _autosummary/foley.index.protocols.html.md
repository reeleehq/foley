# foley.index.protocols

Structural contracts for the foley index (the retrieval boundary).

These three `Protocol``s are the small, swappable seams report 04 §6.2 calls for:
keep the boundary as *protocols*, give each a zero-config sensible default, and
let every piece be replaced by keyword injection. They are the SSOT for the
Index-stage contracts (report 10 §4.2) and are deliberately kept here, separate
from any concrete backend, so the façade (:mod:`foley.index.library`) and the
search logic (:mod:`foley.index.search`) depend only on the interface — never on
``torch` / `lancedb` / `sqlite_vec`.

> * [`Embedder`](#foley.index.protocols.Embedder)     — the joint text<->audio space (CLAP default).
> * [`VectorIndex`](#foley.index.protocols.VectorIndex)  — approximate-nearest-neighbour over embeddings.
> * [`KeywordIndex`](#foley.index.protocols.KeywordIndex) — BM25 / full-text over tags + caption.

A single backend object may satisfy *both* index protocols at once (LanceDB holds
the vector column and the FTS index in one table); the façade simply passes it as
both `vindex` and `kindex`.

This module is stdlib-only: `ndarray` appears solely in annotations, imported
under `TYPE_CHECKING` so `import foley.index.protocols` never pulls numpy.

### Classes

| [`Captioner`](#foley.index.protocols.Captioner)(\*args, \*\*kwargs)    | Produce one natural-language sentence describing a clip (report 03).   |
|-----------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`Embedder`](#foley.index.protocols.Embedder)(\*args, \*\*kwargs)     | A joint text<->audio embedding space (CLAP by default).                |
| [`KeywordIndex`](#foley.index.protocols.KeywordIndex)(\*args, \*\*kwargs) | BM25 / full-text index over each sound's tags + caption.               |
| [`Tagger`](#foley.index.protocols.Tagger)(\*args, \*\*kwargs)       | Map a clip to `(label, score)` pairs against a label vocabulary.       |
| [`VectorIndex`](#foley.index.protocols.VectorIndex)(\*args, \*\*kwargs)  | Approximate-nearest-neighbour store over embedding vectors.            |

### *class* foley.index.protocols.Captioner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Produce one natural-language sentence describing a clip (report 03).

The caption feeds the BM25 keyword index and human display. Default is a
dedicated AAC model (EnCLAP); Qwen2-Audio is a richer promptable upgrade.
Both are `foley[caption]` adapters plugged in behind this protocol.

#### caption(wav, sr)

Return a one-sentence caption for the clip.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* foley.index.protocols.Embedder(\*args, \*\*kwargs)

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

### *class* foley.index.protocols.KeywordIndex(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

BM25 / full-text index over each sound’s tags + caption.

The default is LanceDB’s Tantivy FTS (report 04 §3.4); SQLite FTS5 is the
single-file fallback. Same `where` push-down contract as
[`VectorIndex`](#foley.index.protocols.VectorIndex).

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

### *class* foley.index.protocols.Tagger(\*args, \*\*kwargs)

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

### *class* foley.index.protocols.VectorIndex(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Approximate-nearest-neighbour store over embedding vectors.

The default is LanceDB (report 04 §2); Qdrant/pgvector/sqlite-vec bind the
same protocol behind the scenes. `where` is an optional metadata push-down
the façade may pass; a backend that cannot push filters down MAY ignore it
(the façade over-fetches and post-filters to stay correct either way).

#### get_vector(id)

Return the stored vector for `id` (or `None` if absent).

Needed by `SoundLibrary.similar` (fetch a sound’s own vector, then run
[`knn()`](#foley.index.protocols.VectorIndex.knn)) and by the optional CLAP rerank (score keyword-only hits).

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
