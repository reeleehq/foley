# foley.eval.retrieval

Tier-1 retrieval metrics + run assembly — pure stdlib, CI-safe, ranx-exact.

The metrics (`nDCG@10`, `Recall@k`, `Precision@k`, `mAP@10`, `MRR@10`)
are hand-rolled in stdlib (no `ranx`/`numba`) so the nDCG PR gate runs in
foley’s numpy-only CI with zero heavy deps — yet they are \*\*numerically
identical\*\* to `ranx`/`pytrec_eval` (guarded by the opt-in
`tests/eval/test_metrics_vs_ranx.py` oracle). nDCG uses the **linear** Järvelin
gain `Σ grade_i / log2(rank+1)` — the definition `ranx`’s `"ndcg@10"` and
`pytrec_eval`’s `ndcg_cut_10` actually implement (report 08 §1.1’s
`2^grade−1` is a doc bug).

Vocabulary (TREC-style):

> * **qrels** — `{query_id: {clip_id: grade}}` — the ground-truth relevance
>   grades (0 = wrong, 1 = acceptable, 2 = ideal); the raw grade is the gain,
>   so the metrics are grade-scale-agnostic.
> * **run** — `{query_id: {clip_id: score}}` — the system’s scored results.

[`build_run()`](#foley.eval.retrieval.build_run) assigns strictly-descending integer scores in the search order,
so a run has **no score ties** and its ranking reproduces `search()`’s
(already id-tiebroken) order exactly — the source of cross-platform determinism.

### Module Attributes

| [`DEFAULT_METRICS`](#foley.eval.retrieval.DEFAULT_METRICS)   | The metrics reported by [`evaluate_run()`](#foley.eval.retrieval.evaluate_run) ([nDCG@10](mailto:nDCG@10) is the sole PR gate).   |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`average_precision_at_k`](#foley.eval.retrieval.average_precision_at_k)(qrels_q, run_q[, k, ...])   | Average precision (trec_eval `map`: divide by TOTAL relevant, not `min(R,k)`).                               |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`build_run`](#foley.eval.retrieval.build_run)(candidates)                              | Turn an ordered `search()` result into a run row with distinct scores.                                       |
| [`evaluate_run`](#foley.eval.retrieval.evaluate_run)(run, qrels, \*[, k, metrics, ...])    | Score a `run` against `qrels`, returning a [`RetrievalReport`](#foley.eval.retrieval.RetrievalReport). |
| [`mean_over_queries`](#foley.eval.retrieval.mean_over_queries)(values)                          | Macro-average of per-query metric values (0.0 for an empty list).                                            |
| [`mrr_at_k`](#foley.eval.retrieval.mrr_at_k)(qrels_q, run_q[, k, rel_lvl])             | Reciprocal rank of the first relevant doc in the top-`k` (0.0 if none).                                      |
| [`ndcg_at_k`](#foley.eval.retrieval.ndcg_at_k)(qrels_q, run_q[, k])                     | Normalized DCG at `k` with linear gains (0.0 when no graded answer).                                         |
| [`precision_at_k`](#foley.eval.retrieval.precision_at_k)(qrels_q, run_q[, k, rel_lvl])       | Fraction of the top-`k` that is relevant (denominator is literal `k`).                                       |
| [`recall_at_k`](#foley.eval.retrieval.recall_at_k)(qrels_q, run_q[, k, rel_lvl])          | Fraction of ALL relevant docs (grade ≥ `rel_lvl`) retrieved in the top-`k`.                                  |

### Classes

| [`RetrievalReport`](#foley.eval.retrieval.RetrievalReport)([per_query, mean, ranks, k])   | Per-query + mean Tier-1 metrics over a golden set (JSON-friendly).   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|

### foley.eval.retrieval.DEFAULT_METRICS *= ('ndcg@10', 'recall@10', 'map@10', 'mrr@10')*

The metrics reported by [`evaluate_run()`](#foley.eval.retrieval.evaluate_run) ([nDCG@10](mailto:nDCG@10) is the sole PR gate).

### *class* foley.eval.retrieval.RetrievalReport(per_query=dict(), mean=dict(), ranks=dict(), k=10)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Per-query + mean Tier-1 metrics over a golden set (JSON-friendly).

#### format_regression_diff(baseline)

A human diff for a failing gate: mean vs baseline + the worst queries.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.eval.retrieval.average_precision_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Average precision (trec_eval `map`: divide by TOTAL relevant, not `min(R,k)`).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.retrieval.build_run(candidates)

Turn an ordered `search()` result into a run row with distinct scores.

Assigns each candidate a strictly-descending integer score
(`len - rank`) in the order returned, so the run carries \*\*no score
ties\*\* and `_ranked_ids()` reproduces the search ranking exactly — the
determinism the gate relies on. The doc id is `candidate.sound.id`.

* **Parameters:**
  **candidates** – An ordered `list[Candidate]` from
  [`foley.index.library.SoundLibrary.search()`](foley.index.library.html.md#foley.index.library.SoundLibrary.search) (best first).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]
* **Returns:**
  `{clip_id: score}` with distinct descending scores.

### foley.eval.retrieval.evaluate_run(run, qrels, , k=10, metrics=('ndcg@10', 'recall@10', 'map@10', 'mrr@10'), rel_lvl=1)

Score a `run` against `qrels`, returning a [`RetrievalReport`](#foley.eval.retrieval.RetrievalReport).

Only query ids present in `qrels` are scored (a run row without a
ground-truth judgment is ignored). `ranks` records, per query, the 1-based
rank of the highest-graded answer (for the failure diff).

* **Return type:**
  [`RetrievalReport`](#foley.eval.retrieval.RetrievalReport)

### foley.eval.retrieval.mean_over_queries(values)

Macro-average of per-query metric values (0.0 for an empty list).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.retrieval.mrr_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Reciprocal rank of the first relevant doc in the top-`k` (0.0 if none).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.retrieval.ndcg_at_k(qrels_q, run_q, k=10)

Normalized DCG at `k` with linear gains (0.0 when no graded answer).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.retrieval.precision_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Fraction of the top-`k` that is relevant (denominator is literal `k`).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.retrieval.recall_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Fraction of ALL relevant docs (grade ≥ `rel_lvl`) retrieved in the top-`k`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
