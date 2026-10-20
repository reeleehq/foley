# foley.index.search

Hybrid retrieval: reciprocal rank fusion over a vector list and a keyword list.

Pure orchestration + fusion. This module depends only on the small index
protocols ([`foley.index.protocols`](foley.index.protocols.html.md#module-foley.index.protocols)) — never on `torch`/`lancedb`/
`sqlite_vec` — so the fusion rule is one SSOT exercised identically by every
backend and directly unit-testable.

Why rank fusion (report 04 §3.2): dense CLAP cosine lives in `[-1, 1]` while
BM25 scores are unbounded, so **averaging them lets one drown the other**.
**Reciprocal Rank Fusion** (RRF; Cormack, Clarke & Büttcher, SIGIR 2009) instead
fuses on *rank position*:

```default
score(d) = Σ_rankers  1 / (k + rank_r(d))          # k = 60 (standard)
```

A document ranked high by *either* the vector list or the BM25 list floats up;
`k=60` damps the long tail. It is one line, parameter-light, and robust — the
right first-stage fusion for a mix of semantic captions and terse literal tags.

The concrete backends (LanceDB, sqlite-vec) can fuse natively in-engine; foley
deliberately fuses here instead so the ranking is byte-identical across backends
and gated by the eval harness (report 08) rather than an engine’s internals.

### Module Attributes

| [`RRF_K`](#foley.index.search.RRF_K)               | Standard RRF damping constant (Cormack et al., SIGIR 2009).      |
|----------------------------------------------------------------------|------------------------------------------------------------------|
| [`DEFAULT_CANDIDATE_K`](#foley.index.search.DEFAULT_CANDIDATE_K) | Per-ranker shortlist depth pulled from each index before fusion. |

### Functions

| [`fuse_hits`](#foley.index.search.fuse_hits)(vector_hits, keyword_hits, \*, k[, ...])   | RRF-fuse a vector ranker's hits with a keyword ranker's hits.         |
|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`hybrid_search`](#foley.index.search.hybrid_search)(query, \*, embedder, vindex, kindex)   | Embed `query`, run the vector + keyword rankers, and RRF-fuse them.   |
| [`reciprocal_rank_fusion`](#foley.index.search.reciprocal_rank_fusion)(ranked_id_lists, \*[, k])     | Fuse several ranked id lists into one, by reciprocal rank.            |
| [`vector_search`](#foley.index.search.vector_search)(qvec, \*, vindex[, k, where])          | Pure audio<->audio (or clip->library) vector search — no keyword leg. |

### Classes

| [`FusedHit`](#foley.index.search.FusedHit)(id[, rrf_score, clap_score, bm25_score])   | One fused retrieval hit: an id plus the scores that produced it.   |
|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|

### foley.index.search.DEFAULT_CANDIDATE_K *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 50*

Per-ranker shortlist depth pulled from each index before fusion. Fusing deeper
lists than the requested `k` lets a doc ranked mid-list by one ranker but top
by the other still surface.

### *class* foley.index.search.FusedHit(id, rrf_score=None, clap_score=None, bm25_score=None)

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

### foley.index.search.RRF_K *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 60*

Standard RRF damping constant (Cormack et al., SIGIR 2009). Larger => flatter.

### foley.index.search.fuse_hits(vector_hits, keyword_hits, , k, rrf_k=60)

RRF-fuse a vector ranker’s hits with a keyword ranker’s hits.

* **Parameters:**
  * **vector_hits** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(id, cosine_similarity), ...]` best-first (from
    [`knn()`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex.knn)).
  * **keyword_hits** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(id, bm25_score), ...]` best-first (from
    [`bm25()`](foley.index.protocols.html.md#foley.index.protocols.KeywordIndex.bm25)).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of fused hits to return.
  * **rrf_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](#foley.index.search.FusedHit)]
* **Returns:**
  The top-`k` :class:

  ```
  `
  ```

  FusedHit\`s, each carrying its raw component scores.

### foley.index.search.hybrid_search(query, , embedder, vindex, kindex, k=10, candidate_k=50, rrf_k=60, where=None)

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
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](#foley.index.search.FusedHit)]
* **Returns:**
  The top-`k` fused :class:

  ```
  `
  ```

  FusedHit\`s.

### foley.index.search.reciprocal_rank_fusion(ranked_id_lists, , k=60)

Fuse several ranked id lists into one, by reciprocal rank.

* **Parameters:**
  * **ranked_id_lists** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Each element is a list of ids in descending-relevance
    order (best first). Lists may overlap and may differ in length.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant (default [`RRF_K`](#foley.index.search.RRF_K) = 60).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, fused_score), ...]` sorted by fused score descending, ties
  broken by `id` ascending (so the fusion is fully deterministic).

### foley.index.search.vector_search(qvec, , vindex, k=10, where=None)

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
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](#foley.index.search.FusedHit)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  FusedHit\`s in descending-similarity order.
