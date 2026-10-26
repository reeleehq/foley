# foley.eval.bradley_terry

Bradley-Terry ranking from pairwise preferences (2AFC human panels; #49).

A 2AFC panel (“which of these two clips fits the prompt better?”) gives win counts between
pairs of systems (a backend, a judge, a prompt style). Bradley-Terry turns them into one
strength per item: `P(i beats j) = s_i / (s_i + s_j)`. Strengths are reported on the log
scale, centred on 0, so a difference of `d` means odds `e**d` that the higher one wins.

With comparisons that fall into disconnected groups the strengths of different groups are not
comparable (`connected` is `False`), whatever the prior. Bootstrap intervals resample single
judgements, ignoring that one rater’s judgements are correlated; treat them as optimistic.

Fitted by the MM (minorise-maximise) iteration of Hunter (2004). A small `prior` of virtual
games (one half-win each way against every other item) keeps the estimate finite when an item
never wins or never loses, which a small panel often produces; set `prior=0` for the plain
maximum-likelihood fit (it can diverge on such data). Pure numpy, deterministic; bootstrap
intervals take an explicit `seed`.

### Module Attributes

| [`DEFAULT_PRIOR`](#foley.eval.bradley_terry.DEFAULT_PRIOR)   | Virtual half-wins each way between every pair of items (the Bayesian regulariser).   |
|------------------------------------------------------------------|--------------------------------------------------------------------------------------|

### Functions

| [`fit`](#foley.eval.bradley_terry.fit)(comparisons, \*[, prior, max_iter, tol, ...])   | Fit Bradley-Terry strengths to `(winner, loser)` comparisons.                |
|------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`win_matrix`](#foley.eval.bradley_terry.win_matrix)(comparisons)                             | `(items, wins)` from `(winner, loser)` pairs; `wins[i][j]` = times i beat j. |

### Classes

| [`BradleyTerry`](#foley.eval.bradley_terry.BradleyTerry)(items, scores, n_comparisons, ...)   | Fitted strengths: `items[i]` has log-strength `scores[i]` (mean 0).   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|

### *class* foley.eval.bradley_terry.BradleyTerry(items, scores, n_comparisons, converged, connected, ci=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Fitted strengths: `items[i]` has log-strength `scores[i]` (mean 0).

#### p_win(a, b)

The fitted probability that `a` beats `b`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### ranking()

Items from strongest to weakest.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.eval.bradley_terry.DEFAULT_PRIOR *= 0.5*

Virtual half-wins each way between every pair of items (the Bayesian regulariser).

### foley.eval.bradley_terry.fit(comparisons, , prior=0.5, max_iter=1000, tol=1e-10, bootstrap=0, ci=0.95, seed=0)

Fit Bradley-Terry strengths to `(winner, loser)` comparisons.

* **Parameters:**
  * **comparisons** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – One `(winner, loser)` pair per judgement (ties are left out).
  * **prior** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Virtual half-wins each way between every pair (see the module docstring).
  * **max_iter** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – MM iteration cap.
  * **tol** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Stop when the largest log-strength change is under this.
  * **bootstrap** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – If positive, resample the judgements this many times (seeded) and add
    percentile intervals at level `ci` to the result.
  * **ci** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The interval level.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The bootstrap RNG seed.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – With fewer than two distinct items, or a comparison of an item with itself.
* **Return type:**
  [`BradleyTerry`](#foley.eval.bradley_terry.BradleyTerry)

### foley.eval.bradley_terry.win_matrix(comparisons)

`(items, wins)` from `(winner, loser)` pairs; `wins[i][j]` = times i beat j.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]]
