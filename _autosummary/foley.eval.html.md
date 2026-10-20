# foley.eval

Tier-1 retrieval evaluation — metrics, a frozen golden set, and the nDCG gate.

This subpackage answers “did we retrieve the right sound?” with TREC-style
ranking metrics (`nDCG@10` / `Recall@k` / `mAP@10` / `MRR@10`) over a
frozen golden set, and ships the **PR gate**: a pytest check that blocks a change
whose `nDCG@10` regresses by more than `0.02` on the Ring-0 golden set. Every
part is pure numpy/stdlib and deterministic — no `ranx`/`numba`, no CLAP, no
downloads — so the gate runs on every index/embedder/prompt PR in foley’s CI.

Tier-2 fit-judging (#10b) — “does this clip match the intent?” — lives alongside
in [`fit`](foley.eval.fit.html.md#module-foley.eval.fit) (the judge-based fit harness), [`reliability`](foley.eval.reliability.html.md#module-foley.eval.reliability)
(Krippendorff’s α + judge-vs-human calibration), and [`fidelity`](foley.eval.fidelity.html.md#module-foley.eval.fidelity)
(set-level FAD/KAD generation fidelity). Tier-2 is nightly/pre-release + cost-gated —
NOT a per-PR gate — and never touches the retrieval ranking. All numpy imports are
function-local so `import foley` stays dol-only.

### Functions

| [`ndcg_at_k`](#foley.eval.ndcg_at_k)(qrels_q, run_q[, k])                    | Normalized DCG at `k` with linear gains (0.0 when no graded answer).                                                                                     |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`recall_at_k`](#foley.eval.recall_at_k)(qrels_q, run_q[, k, rel_lvl])         | Fraction of ALL relevant docs (grade ≥ `rel_lvl`) retrieved in the top-`k`.                                                                              |
| [`precision_at_k`](#foley.eval.precision_at_k)(qrels_q, run_q[, k, rel_lvl])      | Fraction of the top-`k` that is relevant (denominator is literal `k`).                                                                                   |
| [`average_precision_at_k`](#foley.eval.average_precision_at_k)(qrels_q, run_q[, k, ...])  | Average precision (trec_eval `map`: divide by TOTAL relevant, not `min(R,k)`).                                                                           |
| [`mrr_at_k`](#foley.eval.mrr_at_k)(qrels_q, run_q[, k, rel_lvl])            | Reciprocal rank of the first relevant doc in the top-`k` (0.0 if none).                                                                                  |
| [`mean_over_queries`](#foley.eval.mean_over_queries)(values)                         | Macro-average of per-query metric values (0.0 for an empty list).                                                                                        |
| [`build_run`](#foley.eval.build_run)(candidates)                             | Turn an ordered `search()` result into a run row with distinct scores.                                                                                   |
| [`evaluate_run`](#foley.eval.evaluate_run)(run, qrels, \*[, k, metrics, ...])   | Score a `run` against `qrels`, returning a [`RetrievalReport`](#foley.eval.RetrievalReport).                                             |
| [`load_golden`](#foley.eval.load_golden)([path])                               | Load and validate the frozen golden set from `path` (JSON list).                                                                                         |
| [`to_qrels`](#foley.eval.to_qrels)(golden)                                  | Flatten the golden set into TREC qrels: `{query_id: {clip_id: grade}}`.                                                                                  |
| [`build_eval_library`](#foley.eval.build_eval_library)(\*[, embedder, manifest_path]) | Build the ephemeral Ring-0 eval library (stem ids + injected caption vectors).                                                                           |
| [`run_ring0_retrieval_eval`](#foley.eval.run_ring0_retrieval_eval)(\*[, k, ...])            | Score the golden set's queries against the Ring-0 library — the gate input.                                                                              |
| [`load_baseline`](#foley.eval.load_baseline)([path])                             | Load the committed baseline dict from `path`.                                                                                                            |
| [`write_baseline`](#foley.eval.write_baseline)(report, \*[, path, metric, ...])   | Write a fresh baseline from `report` (the `--update-baseline` action).                                                                                   |
| [`is_stale`](#foley.eval.is_stale)(baseline, \*, seed_path, manifest_path)  | True if the baseline's fixture stamps no longer match the fixtures on disk.                                                                              |
| [`run_fit_eval`](#foley.eval.run_fit_eval)(\*[, golden, golden_path, ...])      | Run the Tier-2 fit eval over a stratified golden sample → a [`FitReport`](#foley.eval.FitReport).                                  |
| [`fit_precision`](#foley.eval.fit_precision)(matches, relevants)                 | Fraction of judge-accepted candidates that are actually gold-relevant.                                                                                   |
| [`fit_recall`](#foley.eval.fit_recall)(matches, relevants)                    | `TP / (TP + FN)` — of the gold-relevant candidates, how many the judge confirmed.                                                                        |
| [`fit_f1`](#foley.eval.fit_f1)(matches, relevants)                        | The harmonic mean of [`fit_precision()`](#foley.eval.fit_precision) and [`fit_recall()`](#foley.eval.fit_recall). |
| [`stratified_sample`](#foley.eval.stratified_sample)(units, \*, strata_keys, ...)    | Deterministic seeded stratified draw over `units` — the cost gate.                                                                                       |
| [`krippendorff_alpha`](#foley.eval.krippendorff_alpha)(reliability_data, \*[, ...])   | Krippendorff's α over `(raters × units)` ratings (`nan` = missing).                                                                                      |
| [`percent_agreement`](#foley.eval.percent_agreement)(reliability_data)               | Raw pairwise percent agreement, reported ALONGSIDE α (report 08 §2.3).                                                                                   |
| [`reliability_band`](#foley.eval.reliability_band)(alpha)                           | Map an α (or κ) to Krippendorff's benchmark band.                                                                                                        |
| [`calibrate_judge_vs_human`](#foley.eval.calibrate_judge_vs_human)(human_grades, ...)       | Compute judge-vs-human agreement and the promotion verdict (report 08 §2.3).                                                                             |
| [`frechet_distance`](#foley.eval.frechet_distance)(x_ref, x_gen)                    | Fréchet distance between two embedding sets (the FAD formula).                                                                                           |
| [`kernel_audio_distance`](#foley.eval.kernel_audio_distance)(x_ref, x_gen, \*[, ...])    | Kernel Audio Distance — the unbiased RBF-MMD² between two embedding sets.                                                                                |
| [`generation_fidelity`](#foley.eval.generation_fidelity)(ref_wavs, gen_wavs, \*, ...)  | Embed two wav sets through an injected embedder and compute FAD or KAD.                                                                                  |

### Classes

| [`RetrievalReport`](#foley.eval.RetrievalReport)([per_query, mean, ranks, k])      | Per-query + mean Tier-1 metrics over a golden set (JSON-friendly).                             |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| [`GoldenItem`](#foley.eval.GoldenItem)(id, context, expected_events, ...)     | One frozen `(context → expected sounds)` judgment (report 08 §1.3).                            |
| [`HashingBowEmbedder`](#foley.eval.HashingBowEmbedder)(\*[, dim])                     | Deterministic hashing bag-of-words text embedder (L2-normalized).                              |
| [`FitReport`](#foley.eval.FitReport)([per_item, fit_precision, ...])         | Tier-2 fit metrics over a stratified golden sample (JSON-friendly, mirrors `RetrievalReport`). |
| [`AlphaResult`](#foley.eval.AlphaResult)(alpha, level, n_units, n_raters, ...) | A judge-vs-human calibration record (surfaced as `FitReport.calibration`).                     |
| [`FidelityStamp`](#foley.eval.FidelityStamp)(embedding, toolkit, version, ...)   | Mandatory provenance for a FAD/KAD score — it is meaningless without it.                       |
| [`FidelityResult`](#foley.eval.FidelityResult)(metric, value, stamp)              | A stamped set-level fidelity score (attached to `FitReport.fidelity`).                         |

### *class* foley.eval.AlphaResult(alpha, level, n_units, n_raters, percent_agreement, band, promoted)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A judge-vs-human calibration record (surfaced as `FitReport.calibration`).

Codifies the promotion rule in one legible object: a model judge is `promoted` to
unattended use only once its agreement with the human raters reaches the
`ALPHA_RELIABLE` band.

### *class* foley.eval.FidelityResult(metric, value, stamp)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A stamped set-level fidelity score (attached to `FitReport.fidelity`).

### *class* foley.eval.FidelityStamp(embedding, toolkit, version, n_ref, n_gen)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Mandatory provenance for a FAD/KAD score — it is meaningless without it.

FAD/KAD are not comparable across embeddings/toolkits/versions, so a bare number is
uninterpretable; this stamp makes the basis of comparison legible.

### *class* foley.eval.FitReport(per_item=dict(), fit_precision=0.0, fit_recall=0.0, fit_f1=0.0, fit_score=0.0, auto_accept_rate=0.0, n_accepted=0, n_confirmed=0, strata=dict(), calibration=None, fidelity=dict(), judge_model='', embedder_model_id='', seed=0, k=10, schema_version=1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Tier-2 fit metrics over a stratified golden sample (JSON-friendly, mirrors `RetrievalReport`).

The fit numbers are co-emitted with the judge-vs-human `calibration` (an
[`AlphaResult`](foley.eval.reliability.html.md#foley.eval.reliability.AlphaResult) dict) so the §5 human-calibration
guardrail is legible: a `fit_precision` is only trusted where α certifies the judge.
`fidelity` holds stamped FAD/KAD results for release-level backend comparison. Both
default empty on the pure-fake path (no human labels, no generated-set wavs).

#### format_regression_diff(baseline)

A human diff of `fit_precision` vs a committed baseline (trend reporting).

The committed fit-baseline stamp is deferred until real judges produce stable
numbers; this ships the trend path only.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### gate(min_fit_precision)

The Tier-2 gate — a NO-OP returning `True` unless a floor is supplied.

Structural guarantee that Tier-2 is never a silent per-PR gate: CI passes no
floor, so this is always `True`; only the nightly/pre-release runner sets one.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### *class* foley.eval.GoldenItem(id, context, expected_events, answer_clip_ids, grade, negatives=list(), labeler='llm+human', schema_version=1)

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

### *class* foley.eval.HashingBowEmbedder(, dim=64)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic hashing bag-of-words text embedder (L2-normalized).

Two texts sharing a token share a dimension, so cosine similarity tracks
lexical overlap — plausible *and* reproducible (a stable `hashlib` hash,
never the salted builtin `hash`). Suitable only for the eval gate /
offline retrieval regression; real retrieval uses CLAP.

#### embed_text(text)

Embed `text` (or a list of texts) -> a `(n, dim)` float32 array.

### *class* foley.eval.RetrievalReport(per_query=dict(), mean=dict(), ranks=dict(), k=10)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Per-query + mean Tier-1 metrics over a golden set (JSON-friendly).

#### format_regression_diff(baseline)

A human diff for a failing gate: mean vs baseline + the worst queries.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.eval.average_precision_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Average precision (trec_eval `map`: divide by TOTAL relevant, not `min(R,k)`).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.build_eval_library(, embedder=None, manifest_path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/corpus.json'))

Build the ephemeral Ring-0 eval library (stem ids + injected caption vectors).

Each manifest clip becomes a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) with id
`ring0:<stem>` and a vector = `embedder.embed_text(caption + tags)` — so
both the vector and BM25 legs carry the caption bag-of-words and the answer
clip lands at integer rank 1 (deterministic, cross-platform).

* **Parameters:**
  * **embedder** – A text embedder (default: [`HashingBowEmbedder`](#foley.eval.HashingBowEmbedder)).
  * **manifest_path** – The Ring-0 `manifest.json` (default: the bundled fixture).
* **Returns:**
  A populated in-memory [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary).

### foley.eval.build_run(candidates)

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

### foley.eval.calibrate_judge_vs_human(human_grades, judge_grades, , level='ordinal')

Compute judge-vs-human agreement and the promotion verdict (report 08 §2.3).

Stacks the human rating row(s) and the model-judge row into one reliability matrix
and returns an [`AlphaResult`](#foley.eval.AlphaResult); `promoted` is `True` iff α reaches the
reliable band — the model judge may then be trusted unattended on that slice.

* **Parameters:**
  * **human_grades** – A 1-D per-unit human grade sequence, or a 2-D `(humans × units)`
    matrix (`nan` = missing).
  * **judge_grades** – The model judge’s 1-D per-unit grades (`nan` = missing).
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The measurement level (default `'ordinal'`).
* **Return type:**
  [`AlphaResult`](foley.eval.reliability.html.md#foley.eval.reliability.AlphaResult)
* **Returns:**
  An [`AlphaResult`](#foley.eval.AlphaResult).

### foley.eval.evaluate_run(run, qrels, , k=10, metrics=('ndcg@10', 'recall@10', 'map@10', 'mrr@10'), rel_lvl=1)

Score a `run` against `qrels`, returning a [`RetrievalReport`](#foley.eval.RetrievalReport).

Only query ids present in `qrels` are scored (a run row without a
ground-truth judgment is ignored). `ranks` records, per query, the 1-based
rank of the highest-graded answer (for the failure diff).

* **Return type:**
  [`RetrievalReport`](foley.eval.retrieval.html.md#foley.eval.retrieval.RetrievalReport)

### foley.eval.fit_f1(matches, relevants)

The harmonic mean of [`fit_precision()`](#foley.eval.fit_precision) and [`fit_recall()`](#foley.eval.fit_recall).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.fit_precision(matches, relevants)

Fraction of judge-accepted candidates that are actually gold-relevant.

`TP / (TP + FP)` where a candidate is a positive iff the fit-judge said `match`
and gold-relevant iff its golden grade ≥ 1. This measures the JUDGE’s auto-accept
*purity* (a low value ⇒ the judge waves through wrong clips) — NOT the ranker. Pure,
closed-form, and the decisive correctness oracle (the Ring-0 + fake-judge plumbing
makes the end-to-end value tautological, so the metric math is tested in isolation).

* **Parameters:**
  * **matches** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Per-candidate fit-judge `match` booleans.
  * **relevants** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Per-candidate gold-relevance booleans (grade ≥ 1).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The fit precision in `[0, 1]` (`0.0` when nothing was accepted).

### foley.eval.fit_recall(matches, relevants)

`TP / (TP + FN)` — of the gold-relevant candidates, how many the judge confirmed.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.frechet_distance(x_ref, x_gen)

Fréchet distance between two embedding sets (the FAD formula).

`‖μ_r − μ_g‖² + Tr(Σ_r + Σ_g − 2(Σ_r Σ_g)^½)` — lower = the generated set’s
embedding distribution is closer to the reference. Feed PANNs Wavegram-Logmel
embeddings for “FAD-P”, or CLAP for a domain-matched FAD.

* **Parameters:**
  * **x_ref** – Reference embeddings `(n_ref, d)`.
  * **x_gen** – Generated embeddings `(n_gen, d)`.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The FAD as a `float` (`≥ 0` up to numerical round-off; `~0` for identical
  distributions).

### foley.eval.generation_fidelity(ref_wavs, gen_wavs, , embedder, sr=48000, metric='fad', toolkit='foley-numpy', version='1')

Embed two wav sets through an injected embedder and compute FAD or KAD.

The real fidelity path is a **zero-call-site-change embedder swap**: a fake /
hashing embedder in CI, PANNs / CLAP (`foley[fit]`) in prod. The embedder’s
`model_id` is stamped into the result.

* **Parameters:**
  * **ref_wavs** – An iterable of reference waveforms (1-D arrays).
  * **gen_wavs** – An iterable of generated waveforms (1-D arrays).
  * **embedder** – An object with `embed_audio(wav, sr) -> vector` and `model_id`.
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sample rate passed to `embed_audio`.
  * **metric** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'fad'` (default) or `'kad'`.
  * **toolkit** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance label for the stamp (default `'foley-numpy'`).
  * **version** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance version for the stamp.
* **Return type:**
  [`FidelityResult`](foley.eval.fidelity.html.md#foley.eval.fidelity.FidelityResult)
* **Returns:**
  A [`FidelityResult`](#foley.eval.FidelityResult) carrying the score and its [`FidelityStamp`](#foley.eval.FidelityStamp).

### foley.eval.is_stale(baseline, , seed_path, manifest_path)

True if the baseline’s fixture stamps no longer match the fixtures on disk.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.eval.kernel_audio_distance(x_ref, x_gen, , bandwidth=None)

Kernel Audio Distance — the unbiased RBF-MMD² between two embedding sets.

Distribution-free and small-sample-convergent; preferred over FAD for the small
reference/generated sets of early-stage eval. The diagonal (same-sample) kernel terms
are dropped (the unbiased estimator), so `KAD(X, X) ≈ 0` and can be slightly
negative.

* **Parameters:**
  * **x_ref** – Reference embeddings `(n_ref, d)`.
  * **x_gen** – Generated embeddings `(n_gen, d)`.
  * **bandwidth** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – RBF bandwidth σ (default: the median heuristic over the pooled set).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The unbiased MMD² as a `float`.

### foley.eval.krippendorff_alpha(reliability_data, , level='ordinal', value_domain=None)

Krippendorff’s α over `(raters × units)` ratings (`nan` = missing).

`α = 1 − D_o/D_e` — 1 is perfect agreement, ~0 is chance, negative is systematic
disagreement. Ordinal is the default (foley’s 0–3 grades); missing ratings are
tolerated (units with < 2 ratings are dropped, no imputation). Pure numpy.

* **Parameters:**
  * **reliability_data** – A 2-D array-like `(raters × units)`; `nan` = missing.
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'ordinal'` (default) | `'nominal'` | `'interval'`.
  * **value_domain** – Optional explicit value set (for a label unobserved by some rater).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  α as a bare `float` (`1.0` when there is no expected disagreement, `D_e = 0`).

### foley.eval.load_baseline(path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/baseline.json'))

Load the committed baseline dict from `path`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.load_golden(path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/seed.json'))

Load and validate the frozen golden set from `path` (JSON list).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`GoldenItem`](foley.eval.golden.html.md#foley.eval.golden.GoldenItem)]

### foley.eval.mean_over_queries(values)

Macro-average of per-query metric values (0.0 for an empty list).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.mrr_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Reciprocal rank of the first relevant doc in the top-`k` (0.0 if none).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.ndcg_at_k(qrels_q, run_q, k=10)

Normalized DCG at `k` with linear gains (0.0 when no graded answer).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.percent_agreement(reliability_data)

Raw pairwise percent agreement, reported ALONGSIDE α (report 08 §2.3).

On foley’s skewed ‘most candidates irrelevant’ label distribution a chance-corrected
α can look pessimistic, so the uncorrected agreement is co-reported for context.

* **Parameters:**
  **reliability_data** – A 2-D array-like `(raters × units)`; `nan` = missing.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The fraction of same-unit rater pairs that agree (`0.0` if no pairs).

### foley.eval.precision_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Fraction of the top-`k` that is relevant (denominator is literal `k`).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.recall_at_k(qrels_q, run_q, k=10, , rel_lvl=1)

Fraction of ALL relevant docs (grade ≥ `rel_lvl`) retrieved in the top-`k`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.reliability_band(alpha)

Map an α (or κ) to Krippendorff’s benchmark band.

* **Parameters:**
  **alpha** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – A reliability coefficient in `(-∞, 1]`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  `'reliable'` (α ≥ 0.8), `'tentative'` (0.667 ≤ α < 0.8), else
  `'revise-rubric'`.

### foley.eval.run_fit_eval(, golden=None, golden_path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/seed.json'), sample=None, strata_keys=('family', 'diegetic'), fit_judge=None, embedder=None, level=VerifyLevel.judge, seed=0, k=10, llm=None)

Run the Tier-2 fit eval over a stratified golden sample → a [`FitReport`](#foley.eval.FitReport).

Composes the Tier-1 golden builders + the #7 SELECT loop, applies the authoritative
fit-judge as an independent audit, and aggregates fit-precision/recall/F1 + fit-score

+ auto-accept-rate, with a per-stratum breakdown. Report-only unless
  `min_fit_precision` is supplied.

* **Parameters:**
  * **golden** – A pre-loaded golden list (default: load `golden_path`).
  * **golden_path** – The golden JSON (default: the bundled Ring-0 seed set).
  * **sample** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The stratified sample cap (default: the whole set — the cost gate).
  * **strata_keys** – The stratification axes (default `('family', 'diegetic')`).
  * **fit_judge** – The injected authoritative [`Judge`](foley.agent.protocols.html.md#foley.agent.protocols.Judge)
    (default: `foley.agent.verify._default_fit_judge()` for `llm` — the
    hermetic fake unless `llm` / `$FOLEY_LLM` opts in).
  * **embedder** – The Ring-0 text/​audio embedder (default: [`HashingBowEmbedder`](#foley.eval.HashingBowEmbedder)).
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`VerifyLevel`](foley.base.html.md#foley.base.VerifyLevel)) – The verify rung the fit-judge audits at — `'listen'` or `'judge'`
    (default `VerifyLevel.judge`). `'clap'` is rejected: it never invokes the
    fit-judge (it only re-runs the retrieval clap gate), so it cannot measure fit.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sampling RNG seed.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The retrieval shortlist depth per event.
* **Return type:**
  [`FitReport`](foley.eval.fit.html.md#foley.eval.fit.FitReport)
* **Returns:**
  A [`FitReport`](#foley.eval.FitReport). Gating is the caller’s job via [`FitReport.gate()`](#foley.eval.FitReport.gate).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `level` is `'clap'` (fit judging requires a listen/judge rung).

### foley.eval.run_ring0_retrieval_eval(, k=10, golden_path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/seed.json'), embedder=None)

Score the golden set’s queries against the Ring-0 library — the gate input.

Runs every golden `expected_events[].query` through the real
`SoundLibrary.search()` path (vector ⊕ BM25 ⊕ RRF) and evaluates the
resulting runs against the golden qrels.

* **Parameters:**
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Retrieval cutoff (and the metric `@k`).
  * **golden_path** – The golden set JSON.
  * **embedder** – The eval embedder (default: [`HashingBowEmbedder`](#foley.eval.HashingBowEmbedder)).
* **Return type:**
  [`RetrievalReport`](foley.eval.retrieval.html.md#foley.eval.retrieval.RetrievalReport)
* **Returns:**
  A [`RetrievalReport`](#foley.eval.RetrievalReport) (per-query + mean [nDCG@10](mailto:nDCG@10) / recall / mAP / MRR).

### foley.eval.stratified_sample(units, , strata_keys, sample, seed)

Deterministic seeded stratified draw over `units` — the cost gate.

Round-robins across strata (so an easy family cannot dominate a capped sample);
`sample=None` keeps the full set. Each unit is `(GoldenItem, event_index,
event_dict)`.

* **Parameters:**
  * **units** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – The full `(item, ev_idx, ev_dict)` unit list.
  * **strata_keys** – The stratification axes (e.g. `('family', 'diegetic')`).
  * **sample** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The total draw size, or `None` for all.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RNG seed (reproducibility).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### foley.eval.to_qrels(golden)

Flatten the golden set into TREC qrels: `{query_id: {clip_id: grade}}`.

One qrels row per `(item, event)` — `query_id = f"{item.id}::{event_idx}"`
— future-proofing multi-event items (seed items are single-event today). Each
clip in `answer_clip_ids` carries its `grade`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

### foley.eval.write_baseline(report, , path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/baseline.json'), metric='ndcg@10', tolerance=0.02, seed_path, manifest_path, embedder_model_id='foley-eval/hashing-bow-v1', dim=64, rrf_k=60, updated_at, n_items, revision='gld-v1')

Write a fresh baseline from `report` (the `--update-baseline` action).

Records the mean metric value plus sha256 stamps of the seed + manifest so a
later fixture edit is detected. `updated_at` is passed in (not read from the
clock) so the caller controls reproducibility. `revision` labels the golden-set
generation (bumped when the frozen set is regrown).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  The baseline dict that was written.

### Modules

| [`baseline`](foley.eval.baseline.html.md#module-foley.eval.baseline)       | The committed nDCG baseline — the PR gate's SSOT + staleness stamps.                           |
|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| [`embedder`](foley.eval.embedder.html.md#module-foley.eval.embedder)       | A deterministic, numpy-only text embedder for the retrieval eval gate.                         |
| [`fidelity`](foley.eval.fidelity.html.md#module-foley.eval.fidelity)       | Set-level generation-fidelity — Fréchet Audio Distance (FAD) + Kernel Audio Distance (KAD).    |
| [`fit`](foley.eval.fit.html.md#module-foley.eval.fit)                 | Tier-2 fit evaluation — "does the accepted clip actually match the intent?" (report 08 §2/§5). |
| [`golden`](foley.eval.golden.html.md#module-foley.eval.golden)           | The frozen golden set + the deterministic Ring-0 retrieval harness.                            |
| [`reliability`](foley.eval.reliability.html.md#module-foley.eval.reliability) | Inter-rater reliability — Krippendorff's α + the judge-vs-human calibration guardrail.         |
| [`retrieval`](foley.eval.retrieval.html.md#module-foley.eval.retrieval)     | Tier-1 retrieval metrics + run assembly — pure stdlib, CI-safe, ranx-exact.                    |
