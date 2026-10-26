# foley.eval.baseline

The committed nDCG baseline — the PR gate’s SSOT + staleness stamps.

The gate blocks a PR whose `ndcg@10` falls below `value - tolerance` (report
08 §5). The baseline is a committed **number** (not a frozen per-clip run, which
would be BLAS-drift-fragile across the CI matrix), stamped with the sha256 of the
golden seed + the Ring-0 manifest: if either fixture is edited, the stamp
mismatches and the harness warns “baseline stale — run `foley eval
--update-baseline`”, so a metric shift is attributable to the *system*, not a
silently-shifted corpus. Re-baselining is a deliberate, reviewable one-line diff.

### Module Attributes

| [`DEFAULT_BASELINE_PATH`](#foley.eval.baseline.DEFAULT_BASELINE_PATH)     | Package data dir (ships in the wheel); the baseline lives beside the seed.        |
|----------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`DEFAULT_FIT_BASELINE_PATH`](#foley.eval.baseline.DEFAULT_FIT_BASELINE_PATH) | The committed Tier-2 fit baseline, beside the nDCG one.                           |
| [`DEFAULT_TOLERANCE`](#foley.eval.baseline.DEFAULT_TOLERANCE)         | The regression tolerance from report 08 §5 (Δ [nDCG@10](mailto:nDCG@10) ≥ −0.02). |
| [`FIT_METRIC`](#foley.eval.baseline.FIT_METRIC)                | The fit metric the Tier-2 baseline gates.                                         |

### Functions

| [`check_fit_baseline`](#foley.eval.baseline.check_fit_baseline)(report, baseline, \*[, ...])    | Gate `report` against a committed fit baseline: `(passed, message)`.                                                          |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| [`is_stale`](#foley.eval.baseline.is_stale)(baseline, \*, seed_path, manifest_path)   | True if the baseline's fixture stamps no longer match the fixtures on disk.                                                   |
| [`load_baseline`](#foley.eval.baseline.load_baseline)([path])                              | Load the committed baseline dict from `path`.                                                                                 |
| [`write_baseline`](#foley.eval.baseline.write_baseline)(report, \*[, path, metric, ...])    | Write a fresh baseline from `report` (the `--update-baseline` action).                                                        |
| [`write_fit_baseline`](#foley.eval.baseline.write_fit_baseline)(report, \*[, path, level, ...]) | Write a fresh Tier-2 fit baseline from a [`FitReport`](foley.eval.fit.html.md#foley.eval.fit.FitReport). |

### foley.eval.baseline.DEFAULT_BASELINE_PATH *= PosixPath('/home/runner/work/foley/foley/foley/data/golden/baseline.json')*

Package data dir (ships in the wheel); the baseline lives beside the seed.

### foley.eval.baseline.DEFAULT_FIT_BASELINE_PATH *= PosixPath('/home/runner/work/foley/foley/foley/data/golden/fit_baseline.json')*

The committed Tier-2 fit baseline, beside the nDCG one.

### foley.eval.baseline.DEFAULT_TOLERANCE *= 0.02*

The regression tolerance from report 08 §5 (Δ [nDCG@10](mailto:nDCG@10) ≥ −0.02).

### foley.eval.baseline.FIT_METRIC *= 'fit_precision'*

The fit metric the Tier-2 baseline gates.

### foley.eval.baseline.check_fit_baseline(report, baseline, , level='judge', sample=None, seed_path=None, manifest_path=None)

Gate `report` against a committed fit baseline: `(passed, message)`.

Passes when `fit_precision >= value - tolerance`. A report measured under a different
judge, embedder, rung, sample, seed or `k` than the baseline’s `run` is not
comparable and **fails** with a message saying so (re-stamp with
`foley eval-fit --update-baseline`), never a silent pass. So does a golden set that
no longer matches the baseline’s stamp, when `seed_path` and `manifest_path` are given.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.eval.baseline.is_stale(baseline, , seed_path, manifest_path)

True if the baseline’s fixture stamps no longer match the fixtures on disk.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.eval.baseline.load_baseline(path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/baseline.json'))

Load the committed baseline dict from `path`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.baseline.write_baseline(report, , path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/baseline.json'), metric='ndcg@10', tolerance=0.02, seed_path, manifest_path, embedder_model_id='foley-eval/hashing-bow-v1', dim=64, rrf_k=60, updated_at, n_items, revision='gld-v1')

Write a fresh baseline from `report` (the `--update-baseline` action).

Records the mean metric value plus sha256 stamps of the seed + manifest so a
later fixture edit is detected. `updated_at` is passed in (not read from the
clock) so the caller controls reproducibility. `revision` labels the golden-set
generation (bumped when the frozen set is regrown).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  The baseline dict that was written.

### foley.eval.baseline.write_fit_baseline(report, , path=PosixPath('/home/runner/work/foley/foley/foley/data/golden/fit_baseline.json'), level='judge', sample=None, tolerance=0.02, seed_path, manifest_path, updated_at, n_items, revision='gld-v1')

Write a fresh Tier-2 fit baseline from a [`FitReport`](foley.eval.fit.html.md#foley.eval.fit.FitReport).

The sibling of [`write_baseline()`](#foley.eval.baseline.write_baseline): the committed number is `fit_precision` with the
same fixture stamps (so a golden-set edit is detected) plus the run it was measured
under (judge, embedder, rung, sample, seed, `k`). The committed file is stamped on the
hermetic path (the deterministic fake judge, no network); re-stamp it with a real judge
once its numbers are stable, which records that judge in `run`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
