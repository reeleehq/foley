# foley.eval.golden

The frozen golden set + the deterministic Ring-0 retrieval harness.

A [`GoldenItem`](#foley.eval.golden.GoldenItem) is one `(narrative context → expected sounds)` judgment;
its `answer_clip_ids` + `grade` become the TREC `qrels` the metrics score
against. [`build_eval_library()`](#foley.eval.golden.build_eval_library) stands up an ephemeral, in-memory library
over the bundled Ring-0 synthetic fixture with **injected caption vectors** (via
[`HashingBowEmbedder`](foley.eval.embedder.html.md#foley.eval.embedder.HashingBowEmbedder)), so retrieval is deterministic
and CLAP-free; [`run_ring0_retrieval_eval()`](#foley.eval.golden.run_ring0_retrieval_eval) runs every golden query through
the real `SoundLibrary.search` path and scores it.

The eval fixtures (`seed.json`, `baseline.json`) are **package data** under
`foley/data/golden/` — so they ship in the wheel and `foley.evaluate()` /
`foley eval` work on a bare `pip install` (not only from a source checkout).
`build_eval_library` builds records **directly** with stable
`ring0:<stem>` ids (not via `ingest_one`’s content-hash ids), so the run doc
ids join 1:1 with the qrels — no alias map, no content-hash keyspace trap. The
gate therefore does NOT exercise `ingest_one` (that path is covered by
`test_ingest`/`test_bootstrap`).

### Module Attributes

| [`RING0_MANIFEST_PATH`](#foley.eval.golden.RING0_MANIFEST_PATH)   | The tiny wav-backed demo fixture (6 clips) — decoded by `foley.bootstrap` / `demo`.   |
|------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`RING0_CORPUS_PATH`](#foley.eval.golden.RING0_CORPUS_PATH)     | The larger caption-only **eval** corpus (the 6 demo clips + ~150 synthetic clips).    |

### Functions

| [`build_eval_library`](#foley.eval.golden.build_eval_library)(\*[, embedder, manifest_path])   | Build the ephemeral Ring-0 eval library (stem ids + injected caption vectors).   |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`load_golden`](#foley.eval.golden.load_golden)([path])                                 | Load and validate the frozen golden set from `path` (JSON list).                 |
| [`run_ring0_retrieval_eval`](#foley.eval.golden.run_ring0_retrieval_eval)(\*[, k, ...])              | Score the golden set's queries against the Ring-0 library — the gate input.      |
| [`to_qrels`](#foley.eval.golden.to_qrels)(golden)                                    | Flatten the golden set into TREC qrels: `{query_id: {clip_id: grade}}`.          |

### Classes

| [`GoldenItem`](#foley.eval.golden.GoldenItem)(id, context, expected_events, ...)   | One frozen `(context → expected sounds)` judgment (report 08 §1.3).   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|

### *class* foley.eval.golden.GoldenItem(id, context, expected_events, answer_clip_ids, grade, negatives=list(), labeler='llm+human', schema_version=1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One frozen `(context → expected sounds)` judgment (report 08 §1.3).

#### id

Unique item id (e.g. `gld_0001`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### context

The narrative paragraph (the future SELECT input).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### expected_events

One or more `{query, ucs_catid, layer, diegetic,
salience, ...}` dicts; `query` is the string fed to `search`.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

#### answer_clip_ids

`{ucs_catid: [clip_id, ...]}` — the acceptable clips.

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### grade

`{clip_id: grade}` (2 ideal / 1 acceptable / 0 wrong).

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### negatives

Free-text distractors (unused by scoring; documentation).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

#### labeler

Provenance of the labels (`llm+human` etc.).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### schema_version

The GoldenItem schema version.

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.eval.golden.RING0_CORPUS_PATH *= PosixPath('/home/runner/work/foley/foley/foley/data/golden/corpus.json')*

The larger caption-only **eval** corpus (the 6 demo clips + ~150 synthetic clips). The
retrieval eval needs only captions/tags/vectors — never decoded PCM — so this corpus
ships without wav files, decoupling the nDCG gate’s scale from the demo fixture’s size.

### foley.eval.golden.RING0_MANIFEST_PATH *= PosixPath('/home/runner/work/foley/foley/foley/data/ring0/manifest.json')*

The tiny wav-backed demo fixture (6 clips) — decoded by `foley.bootstrap` / `demo`.

### foley.eval.golden.build_eval_library(, embedder=None, manifest_path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/corpus.json'))

Build the ephemeral Ring-0 eval library (stem ids + injected caption vectors).

Each manifest clip becomes a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) with id
`ring0:<stem>` and a vector = `embedder.embed_text(caption + tags)` — so
both the vector and BM25 legs carry the caption bag-of-words and the answer
clip lands at integer rank 1 (deterministic, cross-platform).

* **Parameters:**
  * **embedder** – A text embedder (default: `HashingBowEmbedder`).
  * **manifest_path** – The Ring-0 `manifest.json` (default: the bundled fixture).
* **Returns:**
  A populated in-memory [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary).

### foley.eval.golden.load_golden(path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/seed.json'))

Load and validate the frozen golden set from `path` (JSON list).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`GoldenItem`](#foley.eval.golden.GoldenItem)]

### foley.eval.golden.run_ring0_retrieval_eval(, k=10, golden_path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/seed.json'), embedder=None)

Score the golden set’s queries against the Ring-0 library — the gate input.

Runs every golden `expected_events[].query` through the real
`SoundLibrary.search()` path (vector ⊕ BM25 ⊕ RRF) and evaluates the
resulting runs against the golden qrels.

* **Parameters:**
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Retrieval cutoff (and the metric `@k`).
  * **golden_path** – The golden set JSON.
  * **embedder** – The eval embedder (default: `HashingBowEmbedder`).
* **Return type:**
  [`RetrievalReport`](foley.eval.retrieval.html.md#foley.eval.retrieval.RetrievalReport)
* **Returns:**
  A `RetrievalReport` (per-query + mean [nDCG@10](mailto:nDCG@10) / recall / mAP / MRR).

### foley.eval.golden.to_qrels(golden)

Flatten the golden set into TREC qrels: `{query_id: {clip_id: grade}}`.

One qrels row per `(item, event)` — `query_id = f"{item.id}::{event_idx}"`
— future-proofing multi-event items (seed items are single-event today). Each
clip in `answer_clip_ids` carries its `grade`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]
