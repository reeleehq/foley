"""Concrete vector + keyword index backends (the swappable retrieval engines).

Each backend satisfies BOTH :class:`~foley.index.protocols.VectorIndex` and
:class:`~foley.index.protocols.KeywordIndex`, so one object serves as both
``vindex`` and ``kindex`` in :class:`~foley.index.library.SoundLibrary`. Three
tiers, same protocol (report 04 §6.2 — "small protocols, swapped stores"):

    * :class:`MemoryIndex`   — pure ``numpy`` cosine + a compact stdlib BM25. Zero
      persistence, zero optional-extra (just numpy). The always-available default
      for tests and small ephemeral libraries; it also exercises foley's own RRF.
    * :class:`LanceIndex`    — LanceDB: one table with a vector column + native
      full-text index (no ``tantivy`` needed). Local dir or ``s3://`` unchanged —
      the recommended persistent default (``foley[index]``).
    * :class:`SqliteVecIndex` — sqlite-vec (``vec0``) + stdlib FTS5 in one file
      (``foley[index-sqlite]``). Minimalist single-file option; **requires an
      interpreter whose ``sqlite3`` allows loadable extensions** (see
      :func:`sqlite_vec_loadable`).

All three lazy-import their heavy dependency inside methods, so importing this
module costs only the stdlib. Fusion is NOT done in-engine: :meth:`knn` and
:meth:`bm25` return raw ranked lists and :mod:`foley.index.search` fuses them via
one shared RRF, so ranking is identical across backends.
"""

from __future__ import annotations

import importlib.util
import math
from collections import Counter
from typing import TYPE_CHECKING, Optional

from ..analysis import tokenize

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

# BM25 free parameters (Robertson/Sparck-Jones); the standard defaults.
_BM25_K1: float = 1.5
_BM25_B: float = 0.75


def _fts5_or_match(query: str) -> "Optional[str]":
    """Build a crash-safe FTS5 ``MATCH`` string from a raw user query.

    Tokenizes with the shared analyzer (:func:`foley.analysis.tokenize`: only
    ``[a-z0-9]+`` survives) and double-quotes each token, so no FTS5 metacharacter — a colon, an unbalanced quote, a bare boolean
    word, parentheses — can reach the FTS5 parser and raise ``sqlite3.OperationalError``.
    Returns ``None`` when the query yields no usable token (the caller returns no hits).
    """
    tokens = tokenize(query)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def _sql_str(value: str) -> str:
    """Quote a Python string as a SQL string literal (single-quote escaped)."""
    return "'" + str(value).replace("'", "''") + "'"


def _where_to_sql(where: Optional[dict]) -> Optional[str]:
    """Translate a simple ``{col: value}`` equality dict into a SQL predicate.

    Only equality is supported (the façade does richer metadata filtering by
    post-filtering hydrated records); anything else should be passed as a raw SQL
    string instead of a dict.
    """
    if where is None:
        return None
    if isinstance(where, str):
        return where
    parts = []
    for col, val in where.items():
        lit = _sql_str(val) if isinstance(val, str) else repr(val)
        parts.append(f"{col} = {lit}")
    return " AND ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Capability checks (accompy-style: probe, don't assume)
# ---------------------------------------------------------------------------


def lancedb_available() -> bool:
    """True if ``lancedb`` is importable (the ``foley[index]`` extra is present)."""
    return importlib.util.find_spec("lancedb") is not None


def sqlite_vec_loadable() -> bool:
    """True if ``sqlite_vec`` is installed AND this interpreter can load it.

    The macOS system / pyenv CPython builds frequently ship a ``sqlite3`` without
    loadable-extension support (no ``enable_load_extension``); on those,
    sqlite-vec cannot be used even when ``pip install``ed. This probes both.
    """
    if importlib.util.find_spec("sqlite_vec") is None:
        return False
    import sqlite3

    con = sqlite3.connect(":memory:")
    try:
        return hasattr(con, "enable_load_extension")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# MemoryIndex — numpy cosine + stdlib BM25 (always available)
# ---------------------------------------------------------------------------


class MemoryIndex:
    """In-memory vector + keyword index (numpy cosine + compact BM25).

    Not persistent — everything lives in dicts, lost on process exit. It exists
    so the full hybrid + façade path is testable and usable with only ``numpy``
    (no LanceDB, no torch), and as a genuine zero-config tier for small or
    ephemeral libraries. The vector and text stores are independent dicts, so
    :meth:`upsert` and :meth:`index` never contend.
    """

    def __init__(self, *, dim: Optional[int] = None):
        """Create an empty index.

        Args:
            dim: Optional expected embedding dimensionality (inferred from the
                first :meth:`upsert` when omitted; used only for a sanity check).
        """
        self.dim = dim
        self._vectors: dict[str, "ndarray"] = {}
        self._texts: dict[str, str] = {}
        self._meta: dict[str, dict] = {}

    # -- VectorIndex --------------------------------------------------------

    def upsert(self, id: str, vector: "ndarray", meta: dict) -> None:
        """Insert or replace the vector (and light metadata) for ``id``."""
        import numpy as np

        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        if self.dim is None:
            self.dim = int(vec.shape[0])
        elif vec.shape[0] != self.dim:
            raise ValueError(
                f"vector dim {vec.shape[0]} != index dim {self.dim} for id {id!r}"
            )
        self._vectors[id] = vec
        if meta:
            self._meta[id] = dict(meta)

    def knn(
        self, vector: "ndarray", k: int, *, where: Optional[dict] = None
    ) -> "list[tuple[str, float]]":
        """Return the ``k`` cosine-nearest ids to ``vector`` (most-similar first)."""
        import numpy as np

        if not self._vectors:
            return []
        ids = list(self._vectors)
        mat = np.stack([self._vectors[i] for i in ids])  # (n, dim)
        q = np.asarray(vector, dtype=np.float32).reshape(-1)
        mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12)
        q_n = q / (np.linalg.norm(q) + 1e-12)
        sims = mat_n @ q_n
        # Deterministic: similarity desc, ties broken by id asc — matches bm25 and
        # the other backends so fused ranking is identical even for tied vectors.
        order = sorted(range(len(ids)), key=lambda j: (-float(sims[j]), ids[j]))
        return [(ids[j], float(sims[j])) for j in order[: max(k, 0)]]

    def get_vector(self, id: str) -> "Optional[ndarray]":
        """Return the stored vector for ``id`` (or ``None``)."""
        return self._vectors.get(id)

    # -- KeywordIndex -------------------------------------------------------

    def index(self, id: str, text: str, meta: dict) -> None:
        """Insert or replace the searchable text (and light metadata) for ``id``."""
        self._texts[id] = text or ""
        if meta:
            self._meta[id] = dict(meta)

    def bm25(
        self, query: str, k: int, *, where: Optional[dict] = None
    ) -> "list[tuple[str, float]]":
        """Return the top-``k`` BM25 matches for ``query`` (best first).

        A compact Okapi BM25 (``k1=1.5``, ``b=0.75``) recomputed per query — O(N)
        in the corpus size, which is fine for the in-memory tier's scale.
        """
        docs = self._texts
        if not docs:
            return []
        tokenized = {i: tokenize(t) for i, t in docs.items()}
        n_docs = len(tokenized)
        avgdl = sum(len(t) for t in tokenized.values()) / n_docs or 1.0
        df: Counter = Counter()
        for toks in tokenized.values():
            df.update(set(toks))
        q_terms = tokenize(query)
        scores: dict[str, float] = {}
        for id_, toks in tokenized.items():
            tf = Counter(toks)
            dlen = len(toks)
            score = 0.0
            for term in q_terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * dlen / avgdl)
                score += idf * (freq * (_BM25_K1 + 1)) / denom
            if score > 0:
                scores[id_] = score
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:k]

    def commit(self) -> None:
        """No-op (writes are immediate); present for interface symmetry."""

    def __len__(self) -> int:
        return len(set(self._vectors) | set(self._texts))


# ---------------------------------------------------------------------------
# LanceIndex — LanceDB one-table (vector column + native FTS)
# ---------------------------------------------------------------------------


class LanceIndex:
    """LanceDB-backed index: one table with a vector column + a native FTS index.

    Writes are staged per id and flushed on the next read (or explicit
    :meth:`commit`), so a sound's vector (:meth:`upsert`) and text (:meth:`index`)
    — which arrive as two separate protocol calls — are merged into one row and
    written as an efficient batch. Vector search is exact cosine (no ANN index is
    built at this tier; adding one is a scale-time optimization). Fusion is done
    by :mod:`foley.index.search`, not by LanceDB's native hybrid reranker, so
    ranking matches every other backend.

    One-table constraint: the vector column is mandatory, so **every indexed row
    needs a vector**. ``SoundLibrary.add`` enforces this (it raises without an
    embedding source), so the façade path is safe; a bare ``index()`` with no
    matching ``upsert()`` stages a text-only row that stays unflushed (never
    keyword-searchable). For a keyword-only library with no embeddings, use
    :class:`MemoryIndex` or :class:`SqliteVecIndex` (independent vector/text tables).
    """

    #: The LanceDB score field for a full-text query in this version.
    _FTS_SCORE_FIELDS = ("_score", "_relevance_score")

    def __init__(self, *, uri, dim: int, table_name: str = "sounds"):
        """Open (or lazily create) a LanceDB table for the index.

        Args:
            uri: A local directory path or ``s3://…`` URI for the LanceDB dataset.
            dim: The embedding dimensionality (fixes the vector column width).
            table_name: The table name within the dataset.
        """
        self.uri = str(uri)
        self.dim = int(dim)
        self.table_name = table_name
        self._db = None
        self._table = None
        self._pending: dict[str, dict] = {}
        self._fts_built = False
        self._fts_dirty = False

    @property
    def db(self):
        """The lazily-connected LanceDB database handle."""
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self.uri)
        return self._db

    def _schema(self):
        import pyarrow as pa

        return pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self.dim)),
            ]
        )

    def _existing_tables(self):
        # list_tables() (newer) returns a paged object with a .tables list;
        # table_names() (older, now deprecated) returns a plain list.
        lister = getattr(self.db, "list_tables", None)
        if lister is not None:
            result = lister()
            return getattr(result, "tables", result)
        return self.db.table_names()

    @property
    def table(self):
        """The lazily-opened (or created-empty) LanceDB table."""
        if self._table is None:
            if self.table_name in self._existing_tables():
                self._table = self.db.open_table(self.table_name)
            else:
                self._table = self.db.create_table(
                    self.table_name, schema=self._schema()
                )
        return self._table

    # -- staged writes ------------------------------------------------------

    def upsert(self, id: str, vector: "ndarray", meta: dict) -> None:
        """Stage the vector for ``id`` (flushed on the next read/commit)."""
        import numpy as np

        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vec.shape[0] != self.dim:
            raise ValueError(
                f"vector dim {vec.shape[0]} != index dim {self.dim} for id {id!r}"
            )
        self._pending.setdefault(id, {})["vector"] = vec.tolist()

    def index(self, id: str, text: str, meta: dict) -> None:
        """Stage the searchable text for ``id`` (flushed on the next read/commit)."""
        self._pending.setdefault(id, {})["text"] = text or ""

    def _flush(self) -> None:
        if not self._pending:
            return
        rows = []
        for id_, staged in self._pending.items():
            vec = staged.get("vector")
            if vec is None:
                # text-only staged row: the vector column is mandatory, so keep it
                # pending until its vector arrives (the façade always adds one).
                continue
            rows.append({"id": id_, "text": staged.get("text") or "", "vector": vec})
        if not rows:
            return
        (
            self.table.merge_insert("id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(rows)
        )
        for row in rows:
            self._pending.pop(row["id"], None)
        self._fts_dirty = True

    def commit(self) -> None:
        """Flush all staged writes to the LanceDB table."""
        self._flush()

    def _ensure_fts(self) -> None:
        if self._fts_built and not self._fts_dirty:
            return
        # Only ever called on a non-empty table (bm25 returns early on _count()==0),
        # so a genuine FTS-build failure is surfaced, not swallowed — a silent
        # keyword-leg outage would degrade hybrid search to vector-only unnoticed.
        self.table.create_fts_index("text", use_tantivy=False, replace=True)
        self._fts_built = True
        self._fts_dirty = False

    def _count(self) -> int:
        try:
            return self.table.count_rows()
        except Exception:  # pragma: no cover - version-dependent fallback
            return len(self.table)

    # -- reads --------------------------------------------------------------

    def knn(
        self, vector: "ndarray", k: int, *, where: Optional[dict] = None
    ) -> "list[tuple[str, float]]":
        """Exact cosine KNN; returns ``[(id, cosine_similarity), ...]``."""
        import numpy as np

        self._flush()
        if self._count() == 0:
            return []
        q = np.asarray(vector, dtype=np.float32).reshape(-1)
        builder = self.table.search(q).metric("cosine").limit(k)
        sql = _where_to_sql(where)
        if sql:
            builder = builder.where(sql)
        return [(h["id"], 1.0 - float(h["_distance"])) for h in builder.to_list()]

    def get_vector(self, id: str) -> "Optional[ndarray]":
        """Return the stored vector for ``id`` (staged or persisted), else ``None``."""
        import numpy as np

        staged = self._pending.get(id, {}).get("vector")
        if staged is not None:
            return np.asarray(staged, dtype=np.float32)
        self._flush()
        if self._count() == 0:
            return None
        # Filter-only query (no query vector, no pylance): returns the row's cols.
        rows = self.table.search().where(f"id = {_sql_str(id)}").limit(1).to_list()
        if not rows:
            return None
        return np.asarray(rows[0]["vector"], dtype=np.float32)

    def bm25(
        self, query: str, k: int, *, where: Optional[dict] = None
    ) -> "list[tuple[str, float]]":
        """Native full-text (BM25) search; returns ``[(id, score), ...]``."""
        if not query.strip():
            return []
        self._flush()
        if self._count() == 0:
            return []
        self._ensure_fts()
        if not self._fts_built:
            return []
        builder = self.table.search(query, query_type="fts").limit(k)
        sql = _where_to_sql(where)
        if sql:
            builder = builder.where(sql)
        out = []
        for h in builder.to_list():
            score = next(
                (h[f] for f in self._FTS_SCORE_FIELDS if f in h and h[f] is not None),
                0.0,
            )
            out.append((h["id"], float(score)))
        return out


# ---------------------------------------------------------------------------
# SqliteVecIndex — sqlite-vec (vec0) + stdlib FTS5, one file
# ---------------------------------------------------------------------------


class SqliteVecIndex:
    """Single-file index: sqlite-vec ``vec0`` KNN + stdlib FTS5 keyword search.

    The whole index is one SQLite file behind two virtual tables (independent, so
    :meth:`upsert` and :meth:`index` never contend). **Requires an interpreter
    whose ``sqlite3`` permits loadable extensions** — probe with
    :func:`sqlite_vec_loadable` before constructing; the constructor raises a
    clear error otherwise.
    """

    def __init__(self, *, path, dim: int):
        """Open (creating if needed) the SQLite file and load sqlite-vec.

        Args:
            path: Filesystem path for the ``.db`` file (or ``":memory:"``).
            dim: The embedding dimensionality (fixes the ``vec0`` column width).

        Raises:
            RuntimeError: If ``sqlite_vec`` is unavailable or this interpreter
                cannot load SQLite extensions (see :func:`sqlite_vec_loadable`).
        """
        if not sqlite_vec_loadable():
            raise RuntimeError(
                "SqliteVecIndex needs the 'sqlite-vec' package AND a Python whose "
                "sqlite3 allows loadable extensions. Install 'foley[index-sqlite]', "
                "and use an interpreter built with --enable-loadable-sqlite-extensions "
                "(e.g. Homebrew python or pysqlite3-binary). Prefer LanceDB "
                "('foley[index]') otherwise."
            )
        import sqlite3

        import sqlite_vec

        self.dim = int(dim)
        self._con = sqlite3.connect(str(path))
        self._con.enable_load_extension(True)
        sqlite_vec.load(self._con)
        self._con.enable_load_extension(False)
        self._con.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_items "
            f"USING vec0(id TEXT PRIMARY KEY, embedding float[{self.dim}] distance_metric=cosine)"
        )
        self._con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts_items USING fts5(id UNINDEXED, text)"
        )
        self._con.commit()

    @staticmethod
    def _pack(vector) -> bytes:
        import struct

        vals = [float(x) for x in vector]
        return struct.pack(f"{len(vals)}f", *vals)

    def upsert(self, id: str, vector: "ndarray", meta: dict) -> None:
        """Insert or replace the vector for ``id`` in the ``vec0`` table."""
        import numpy as np

        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vec.shape[0] != self.dim:
            raise ValueError(
                f"vector dim {vec.shape[0]} != index dim {self.dim} for id {id!r}"
            )
        self._con.execute("DELETE FROM vec_items WHERE id = ?", (id,))
        self._con.execute(
            "INSERT INTO vec_items(id, embedding) VALUES (?, ?)",
            (id, self._pack(vec)),
        )
        self._con.commit()

    def knn(
        self, vector: "ndarray", k: int, *, where: Optional[dict] = None
    ) -> "list[tuple[str, float]]":
        """KNN over ``vec0`` (cosine); returns ``[(id, cosine_similarity), ...]``."""
        import numpy as np

        q = np.asarray(vector, dtype=np.float32).reshape(-1)
        rows = self._con.execute(
            "SELECT id, distance FROM vec_items "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (self._pack(q), int(k)),
        ).fetchall()
        # vec0 cosine 'distance' = 1 - cosine_similarity
        return [(id_, 1.0 - float(dist)) for id_, dist in rows]

    def get_vector(self, id: str) -> "Optional[ndarray]":
        """Return the stored vector for ``id`` (or ``None``)."""
        import struct

        import numpy as np

        row = self._con.execute(
            "SELECT embedding FROM vec_items WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        blob = row[0]
        vals = struct.unpack(f"{len(blob) // 4}f", blob)
        return np.asarray(vals, dtype=np.float32)

    def index(self, id: str, text: str, meta: dict) -> None:
        """Insert or replace the searchable text for ``id`` in the FTS5 table."""
        self._con.execute("DELETE FROM fts_items WHERE id = ?", (id,))
        self._con.execute(
            "INSERT INTO fts_items(id, text) VALUES (?, ?)", (id, text or "")
        )
        self._con.commit()

    def bm25(
        self, query: str, k: int, *, where: Optional[dict] = None
    ) -> "list[tuple[str, float]]":
        """FTS5 BM25 search; returns ``[(id, score), ...]`` best-first.

        FTS5's ``rank`` is more-negative-is-better; it is negated so the returned
        score is larger-is-better (consistent with the other backends).
        """
        # Build a crash-safe MATCH from the shared analyzer instead of the raw query: FTS5
        # metacharacters (a colon, an unbalanced quote, a bare boolean word, parentheses)
        # would otherwise raise sqlite3.OperationalError and abort the whole search(). This
        # mirrors MemoryIndex's tolerant behavior (cross-backend parity).
        match = _fts5_or_match(query)
        if match is None:
            return []
        rows = self._con.execute(
            "SELECT id, rank FROM fts_items WHERE fts_items MATCH ? "
            "ORDER BY rank LIMIT ?",
            (match, int(k)),
        ).fetchall()
        return [(id_, -float(rank)) for id_, rank in rows]

    def commit(self) -> None:
        """Commit any pending SQLite transaction (writes auto-commit already)."""
        self._con.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._con.close()


# ---------------------------------------------------------------------------
# Default backend selection (progressive disclosure + graceful degradation)
# ---------------------------------------------------------------------------


def default_index(*, data_dir, dim: int):
    """Build the best available persistent index for a library.

    Degradation ladder: LanceDB (``foley[index]``) → sqlite-vec
    (``foley[index-sqlite]``, if loadable) → an informative error. The
    non-persistent :class:`MemoryIndex` is never chosen automatically (a library
    must survive restarts); inject it explicitly for tests/ephemeral use.

    Args:
        data_dir: The library data root (a ``pathlib.Path``-like).
        dim: The embedding dimensionality from the active embedder.

    Returns:
        A ready index object (both ``VectorIndex`` and ``KeywordIndex``).

    Raises:
        RuntimeError: If no persistent backend is installed/usable.
    """
    from pathlib import Path

    data_dir = Path(data_dir)
    if lancedb_available():
        return LanceIndex(uri=data_dir / "lancedb", dim=dim)
    if sqlite_vec_loadable():
        return SqliteVecIndex(path=data_dir / "index.db", dim=dim)
    raise RuntimeError(
        "No persistent index backend available. Install 'foley[index]' (LanceDB, "
        "recommended) or 'foley[index-sqlite]' (sqlite-vec, needs an interpreter "
        "with loadable SQLite extensions). For a non-persistent in-memory index, "
        "inject foley.index.MemoryIndex() explicitly."
    )
