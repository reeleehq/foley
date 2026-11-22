# foley.index.indexes

Concrete vector + keyword index backends (the swappable retrieval engines).

Each backend satisfies BOTH [`VectorIndex`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex) and
[`KeywordIndex`](foley.index.protocols.html.md#foley.index.protocols.KeywordIndex), so one object serves as both
`vindex` and `kindex` in [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary). Three
tiers, same protocol (report 04 §6.2 — “small protocols, swapped stores”):

> * [`MemoryIndex`](#foley.index.indexes.MemoryIndex)   — pure `numpy` cosine + a compact stdlib BM25. Zero
>   persistence, zero optional-extra (just numpy). The always-available default
>   for tests and small ephemeral libraries; it also exercises foley’s own RRF.
> * [`LanceIndex`](#foley.index.indexes.LanceIndex)    — LanceDB: one table with a vector column + native
>   full-text index (no `tantivy` needed). Local dir or `s3://` unchanged —
>   the recommended persistent default (`foley[index]`).
> * [`SqliteVecIndex`](#foley.index.indexes.SqliteVecIndex) — sqlite-vec (`vec0`) + stdlib FTS5 in one file
>   (`foley[index-sqlite]`). Minimalist single-file option; \*\*requires an
>   interpreter whose `sqlite3` allows loadable extensions\*\* (see
>   [`sqlite_vec_loadable()`](#foley.index.indexes.sqlite_vec_loadable)).

All three lazy-import their heavy dependency inside methods, so importing this
module costs only the stdlib. Fusion is NOT done in-engine: `knn()` and
`bm25()` return raw ranked lists and [`foley.index.search`](foley.index.search.html.md#module-foley.index.search) fuses them via
one shared RRF, so ranking is identical across backends.

### Functions

| [`bm25_idf`](#foley.index.indexes.bm25_idf)(n_docs, df)             | Okapi BM25's inverse document frequency of a term in `df` of `n_docs` documents (the `+1` form, so never negative).   |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`default_index`](#foley.index.indexes.default_index)(\*, data_dir, dim) | Build the best available persistent index for a library.                                                              |
| [`lancedb_available`](#foley.index.indexes.lancedb_available)()              | True if `lancedb` is importable (the `foley[index]` extra is present).                                                |
| [`sqlite_vec_loadable`](#foley.index.indexes.sqlite_vec_loadable)()            | True if `sqlite_vec` is installed AND this interpreter can load it.                                                   |

### Classes

| [`LanceIndex`](#foley.index.indexes.LanceIndex)(\*, uri, dim[, table_name])   | LanceDB-backed index: one table with a vector column + a native FTS index.   |
|-------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`MemoryIndex`](#foley.index.indexes.MemoryIndex)(\*[, dim])                   | In-memory vector + keyword index (numpy cosine + compact BM25).              |
| [`SqliteVecIndex`](#foley.index.indexes.SqliteVecIndex)(\*, path, dim)            | Single-file index: sqlite-vec `vec0` KNN + stdlib FTS5 keyword search.       |

### *class* foley.index.indexes.LanceIndex(, uri, dim, table_name='sounds')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LanceDB-backed index: one table with a vector column + a native FTS index.

Writes are staged per id and flushed on the next read (or explicit
[`commit()`](#foley.index.indexes.LanceIndex.commit)), so a sound’s vector ([`upsert()`](#foley.index.indexes.LanceIndex.upsert)) and text ([`index()`](#foley.index.indexes.LanceIndex.index))
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
[`MemoryIndex`](#foley.index.indexes.MemoryIndex) or [`SqliteVecIndex`](#foley.index.indexes.SqliteVecIndex) (independent vector/text tables).

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

### *class* foley.index.indexes.MemoryIndex(, dim=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

In-memory vector + keyword index (numpy cosine + compact BM25).

Not persistent — everything lives in dicts, lost on process exit. It exists
so the full hybrid + façade path is testable and usable with only `numpy`
(no LanceDB, no torch), and as a genuine zero-config tier for small or
ephemeral libraries. The vector and text stores are independent dicts, so
[`upsert()`](#foley.index.indexes.MemoryIndex.upsert) and [`index()`](#foley.index.indexes.MemoryIndex.index) never contend.

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

### *class* foley.index.indexes.SqliteVecIndex(, path, dim)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Single-file index: sqlite-vec `vec0` KNN + stdlib FTS5 keyword search.

The whole index is one SQLite file behind two virtual tables (independent, so
[`upsert()`](#foley.index.indexes.SqliteVecIndex.upsert) and [`index()`](#foley.index.indexes.SqliteVecIndex.index) never contend). \*\*Requires an interpreter
whose `sqlite3` permits loadable extensions\*\* — probe with
[`sqlite_vec_loadable()`](#foley.index.indexes.sqlite_vec_loadable) before constructing; the constructor raises a
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

### foley.index.indexes.bm25_idf(n_docs, df)

Okapi BM25’s inverse document frequency of a term in `df` of `n_docs`
documents (the `+1` form, so never negative). The one IDF of foley’s keyword
scoring: [`MemoryIndex`](#foley.index.indexes.MemoryIndex) ranks with it, and the UCS keyword stage can weigh
a shared synonym by it (`foley.index.taxonomy.resolver.idf_share`).

```pycon
>>> round(bm25_idf(753, 1), 3), round(bm25_idf(753, 32), 3)
(6.22, 3.144)
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.index.indexes.default_index(, data_dir, dim)

Build the best available persistent index for a library.

Degradation ladder: LanceDB (`foley[index]`) → sqlite-vec
(`foley[index-sqlite]`, if loadable) → an informative error. The
non-persistent [`MemoryIndex`](#foley.index.indexes.MemoryIndex) is never chosen automatically (a library
must survive restarts); inject it explicitly for tests/ephemeral use.

* **Parameters:**
  * **data_dir** – The library data root (a `pathlib.Path`-like).
  * **dim** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The embedding dimensionality from the active embedder.
* **Returns:**
  A ready index object (both `VectorIndex` and `KeywordIndex`).
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If no persistent backend is installed/usable.

### foley.index.indexes.lancedb_available()

True if `lancedb` is importable (the `foley[index]` extra is present).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.indexes.sqlite_vec_loadable()

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
