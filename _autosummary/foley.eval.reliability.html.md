# foley.eval.reliability

Inter-rater reliability — Krippendorff’s α + the judge-vs-human calibration guardrail.

Whatever judges foley’s fit — humans or an LLM/audio-LM — you must \*\*quantify agreement
before trusting the scores\*\* (report 08 §2.3). This module is the numbers side of that
guardrail: one pure-numpy Krippendorff’s α (the most general reliability coefficient —
any number of raters, ordinal/graded labels, missing-data tolerant), reused for BOTH
human inter-rater reliability on the gold grades AND judge-vs-human calibration (the
model judge is just one more rater row). A model judge is only promoted to unattended
use once it reaches human-level agreement on a calibration slice.

Pure numpy / stdlib, deterministic — `numpy` is imported function-locally so importing
this module keeps `import foley` dol-only (the same discipline as
[`foley.eval.retrieval`](foley.eval.retrieval.html.md#module-foley.eval.retrieval)). No `scipy`, no external reliability toolkit (a PyPI
`krippendorff` oracle cross-check lives behind an opt-in test only).

### Module Attributes

| [`ALPHA_RELIABLE`](#foley.eval.reliability.ALPHA_RELIABLE)   | Krippendorff's benchmark bands for a reliability coefficient (report 08 §2.3).   |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------|

### Functions

| [`alpha_result`](#foley.eval.reliability.alpha_result)(reliability_data, \*[, level])     | An [`AlphaResult`](#foley.eval.reliability.AlphaResult) for any `(raters × units)` matrix (`nan` = missing).   |
|--------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| [`calibrate_judge_vs_human`](#foley.eval.reliability.calibrate_judge_vs_human)(human_grades, ...)     | Compute judge-vs-human agreement and the promotion verdict (report 08 §2.3).                                           |
| [`krippendorff_alpha`](#foley.eval.reliability.krippendorff_alpha)(reliability_data, \*[, ...]) | Krippendorff's α over `(raters × units)` ratings (`nan` = missing).                                                    |
| [`percent_agreement`](#foley.eval.reliability.percent_agreement)(reliability_data)             | Raw pairwise percent agreement, reported ALONGSIDE α (report 08 §2.3).                                                 |
| [`reliability_band`](#foley.eval.reliability.reliability_band)(alpha)                         | Map an α (or κ) to Krippendorff's benchmark band.                                                                      |

### Classes

| [`AlphaResult`](#foley.eval.reliability.AlphaResult)(alpha, level, n_units, n_raters, ...)   | A judge-vs-human calibration record (surfaced as `FitReport.calibration`).   |
|------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|

### foley.eval.reliability.ALPHA_RELIABLE *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.8*

Krippendorff’s benchmark bands for a reliability coefficient (report 08 §2.3).

### *class* foley.eval.reliability.AlphaResult(alpha, level, n_units, n_raters, percent_agreement, band, promoted)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A judge-vs-human calibration record (surfaced as `FitReport.calibration`).

Codifies the promotion rule in one legible object: a model judge is `promoted` to
unattended use only once its agreement with the human raters reaches the
[`ALPHA_RELIABLE`](#foley.eval.reliability.ALPHA_RELIABLE) band.

### foley.eval.reliability.alpha_result(reliability_data, , level='ordinal')

An [`AlphaResult`](#foley.eval.reliability.AlphaResult) for any `(raters × units)` matrix (`nan` = missing).

The one place α, its band and the promotion rule are put together: used for the
judge-vs-human matrix here and for human-only agreement in [`foley.eval.panel`](foley.eval.panel.html.md#module-foley.eval.panel).

* **Return type:**
  [`AlphaResult`](#foley.eval.reliability.AlphaResult)

### foley.eval.reliability.calibrate_judge_vs_human(human_grades, judge_grades, , level='ordinal')

Compute judge-vs-human agreement and the promotion verdict (report 08 §2.3).

Stacks the human rating row(s) and the model-judge row into one reliability matrix
and returns an [`AlphaResult`](#foley.eval.reliability.AlphaResult); `promoted` is `True` iff α reaches the
reliable band — the model judge may then be trusted unattended on that slice.

* **Parameters:**
  * **human_grades** – A 1-D per-unit human grade sequence, or a 2-D `(humans × units)`
    matrix (`nan` = missing).
  * **judge_grades** – The model judge’s 1-D per-unit grades (`nan` = missing).
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The measurement level (default `'ordinal'`).
* **Return type:**
  [`AlphaResult`](#foley.eval.reliability.AlphaResult)
* **Returns:**
  An [`AlphaResult`](#foley.eval.reliability.AlphaResult).

### foley.eval.reliability.krippendorff_alpha(reliability_data, , level='ordinal', value_domain=None)

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

### foley.eval.reliability.percent_agreement(reliability_data)

Raw pairwise percent agreement, reported ALONGSIDE α (report 08 §2.3).

On foley’s skewed ‘most candidates irrelevant’ label distribution a chance-corrected
α can look pessimistic, so the uncorrected agreement is co-reported for context.

* **Parameters:**
  **reliability_data** – A 2-D array-like `(raters × units)`; `nan` = missing.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The fraction of same-unit rater pairs that agree (`0.0` if no pairs).

### foley.eval.reliability.reliability_band(alpha)

Map an α (or κ) to Krippendorff’s benchmark band.

* **Parameters:**
  **alpha** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – A reliability coefficient in `(-∞, 1]`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  `'reliable'` (α ≥ 0.8), `'tentative'` (0.667 ≤ α < 0.8), else
  `'revise-rubric'`.
