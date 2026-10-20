# foley.eval.fit

Tier-2 fit evaluation — “does the accepted clip actually match the intent?” (report 08 §2/§5).

The judge-based sibling of [`foley.eval.retrieval`](foley.eval.retrieval.html.md#module-foley.eval.retrieval). Where Tier-1 asks \*did we rank the
right sound?\* (a per-PR nDCG gate), Tier-2 asks \*does the clip the pipeline accepted
genuinely depict the event?\* — audited over a **seeded stratified sample** of the golden
set by the authoritative fit-judge (report 08 §2). It is \*\*nightly / pre-release and
cost-gated, never a silent per-PR gate\*\*: [`FitReport.gate()`](#foley.eval.fit.FitReport.gate) is a no-op unless the
caller passes an explicit `min_fit_precision` floor, and `foley eval-fit` is
deliberately off the CI command path.

Discipline: it **reuses** the Tier-1 golden builders (`load_golden` /
`build_eval_library`) and the #7 SELECT tools (`search_sounds` / `gate_candidates`
/ `verify_match`), but it **never** imports `build_run` / `evaluate_run` /
`to_qrels` — the three symbols that construct or score the retrieval run — so it
structurally cannot compute or perturb the [nDCG@10](mailto:nDCG@10) gate. Metrics are pure numpy/stdlib;
the fit-judge is injected (a deterministic fake in CI, an audio-LM / LLM behind
`foley[fit]` / `foley[agent]` in prod). Fit judging runs strictly AFTER the
fail-closed license gate (`verify_match` asserts `candidate.license_ok` is `True`).

### Functions

| [`fit_f1`](#foley.eval.fit.fit_f1)(matches, relevants)                     | The harmonic mean of [`fit_precision()`](#foley.eval.fit.fit_precision) and [`fit_recall()`](#foley.eval.fit.fit_recall).   |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`fit_precision`](#foley.eval.fit.fit_precision)(matches, relevants)              | Fraction of judge-accepted candidates that are actually gold-relevant.                                                                                     |
| [`fit_recall`](#foley.eval.fit.fit_recall)(matches, relevants)                 | `TP / (TP + FN)` — of the gold-relevant candidates, how many the judge confirmed.                                                                          |
| [`run_fit_eval`](#foley.eval.fit.run_fit_eval)(\*[, golden, golden_path, ...])   | Run the Tier-2 fit eval over a stratified golden sample → a [`FitReport`](#foley.eval.fit.FitReport).                                    |
| [`stratified_sample`](#foley.eval.fit.stratified_sample)(units, \*, strata_keys, ...) | Deterministic seeded stratified draw over `units` — the cost gate.                                                                                         |

### Classes

| [`FitReport`](#foley.eval.fit.FitReport)([per_item, fit_precision, ...])   | Tier-2 fit metrics over a stratified golden sample (JSON-friendly, mirrors `RetrievalReport`).   |
|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|

### *class* foley.eval.fit.FitReport(per_item=dict(), fit_precision=0.0, fit_recall=0.0, fit_f1=0.0, fit_score=0.0, auto_accept_rate=0.0, n_accepted=0, n_confirmed=0, strata=dict(), calibration=None, fidelity=dict(), judge_model='', embedder_model_id='', seed=0, k=10, schema_version=1)

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

### foley.eval.fit.fit_f1(matches, relevants)

The harmonic mean of [`fit_precision()`](#foley.eval.fit.fit_precision) and [`fit_recall()`](#foley.eval.fit.fit_recall).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.fit.fit_precision(matches, relevants)

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

### foley.eval.fit.fit_recall(matches, relevants)

`TP / (TP + FN)` — of the gold-relevant candidates, how many the judge confirmed.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.eval.fit.run_fit_eval(, golden=None, golden_path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/seed.json'), sample=None, strata_keys=('family', 'diegetic'), fit_judge=None, embedder=None, level=VerifyLevel.judge, seed=0, k=10, llm=None)

Run the Tier-2 fit eval over a stratified golden sample → a [`FitReport`](#foley.eval.fit.FitReport).

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
  * **embedder** – The Ring-0 text/​audio embedder (default: `HashingBowEmbedder`).
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`VerifyLevel`](foley.base.html.md#foley.base.VerifyLevel)) – The verify rung the fit-judge audits at — `'listen'` or `'judge'`
    (default `VerifyLevel.judge`). `'clap'` is rejected: it never invokes the
    fit-judge (it only re-runs the retrieval clap gate), so it cannot measure fit.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sampling RNG seed.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The retrieval shortlist depth per event.
* **Return type:**
  [`FitReport`](#foley.eval.fit.FitReport)
* **Returns:**
  A [`FitReport`](#foley.eval.fit.FitReport). Gating is the caller’s job via [`FitReport.gate()`](#foley.eval.fit.FitReport.gate).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `level` is `'clap'` (fit judging requires a listen/judge rung).

### foley.eval.fit.stratified_sample(units, , strata_keys, sample, seed)

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
