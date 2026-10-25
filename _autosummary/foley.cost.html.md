# foley.cost

Cost: what a call will cost before it is made, and a cumulative cap on a run (#57).

Three pieces, each small:

* **Pricing as data.** Each source declares `SOURCE_CONFIG['pricing']` — the falaw
  convention (`unit`, `amount_usd`, plus the `source` and `seen` date the price
  was read from). [`estimate_call()`](#foley.cost.estimate_call) turns it into dollars for one call, and returns
  `None` — never `0.0` — when the cost cannot be known (no pricing, or a
  per-second price with no duration and no maximum).
* **A run-scoped budget.** [`spend_scope()`](#foley.cost.spend_scope) makes a
  [`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget) the active one for a `find` / `score` /
  > `generate` run; [`authorize()`](#foley.cost.authorize) is called before every paid call and refuses the
  > first one that would take the run past `max_usd` (default [`default_max_usd()`](#foley.cost.default_max_usd):

  [`DEFAULT_MAX_USD`](#foley.cost.DEFAULT_MAX_USD), $1 — maintainer decision on #57 — or, when the caller chose
  : a paid LLM for the SELECT rungs, [`DEFAULT_MAX_USD_BY_LLM`](#foley.cost.DEFAULT_MAX_USD_BY_LLM), #88), or whose cost
    is unknown unless the budget approves unknown costs.
* **Two errors.** [`BudgetExceeded`](#foley.cost.BudgetExceeded) and its subclass [`CostApprovalRequired`](#foley.cost.CostApprovalRequired).

Stdlib-only.

### Module Attributes

| [`DEFAULT_MAX_USD`](#foley.cost.DEFAULT_MAX_USD)          | The default cumulative cap for one run (a `find` / `score` / `generate` call).                                                                                                             |
|---------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DEFAULT_MAX_USD_BY_LLM`](#foley.cost.DEFAULT_MAX_USD_BY_LLM)   | The default cap of a [`foley.find()`](foley.html.md#foley.find) run whose LLM rungs the caller chose to pay for (`llm=` or `$FOLEY_LLM`), keyed by provider. |
| [`APPROVE_UNKNOWN_COST_ENV`](#foley.cost.APPROVE_UNKNOWN_COST_ENV) | Set to 1 to approve calls whose cost is unknown, for every run that does not say.                                                                                                          |

### Functions

| [`estimate_call`](#foley.cost.estimate_call)(config, \*\*affordances)   | The USD cost of one call to the source `config` declares, or `None` if unknown.                                                |
|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`spend_scope`](#foley.cost.spend_scope)([budget])                    | Put `budget` in force for the block; every enclosing budget stays in force too.                                                |
| [`scoped_iter`](#foley.cost.scoped_iter)(iterator_factory[, budget])  | Iterate `iterator_factory()` with `budget` in force only while it runs.                                                        |
| [`active_budget`](#foley.cost.active_budget)()                          | The innermost [`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget) of the current run, or `None`. |
| [`check`](#foley.cost.check)(estimate_usd, \*, what)            | Raise unless every budget in force can afford `estimate_usd` (reserves nothing).                                               |
| [`authorize`](#foley.cost.authorize)(estimate_usd, \*, what)        | Admit a paid call: every budget in force must afford it, and each reserves it.                                                 |
| [`settle`](#foley.cost.settle)(reserved_usd, actual_usd)         | Replace each budget's reservation with the actual cost (`None`: keep it).                                                      |
| [`release`](#foley.cost.release)(reserved_usd)                    | Undo a reservation for a call that was never sent.                                                                             |
| [`default_max_usd`](#foley.cost.default_max_usd)([llm])                   | The cap of a run given no budget: higher when the caller chose a paid LLM.                                                     |
| [`charge`](#foley.cost.charge)(usd)                              | Record `usd` against every budget in force (a no-op outside any run).                                                          |

### Exceptions

| [`BudgetExceeded`](#foley.cost.BudgetExceeded)       | Raised before a paid call that would take the run past its `max_usd` cap.          |
|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`CostApprovalRequired`](#foley.cost.CostApprovalRequired) | Raised before a call whose cost is unknown, when the budget has not approved that. |

### foley.cost.APPROVE_UNKNOWN_COST_ENV *= 'FOLEY_APPROVE_UNKNOWN_COST'*

Set to 1 to approve calls whose cost is unknown, for every run that does not say.

### *exception* foley.cost.BudgetExceeded

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised before a paid call that would take the run past its `max_usd` cap.

### *exception* foley.cost.CostApprovalRequired

Bases: [`BudgetExceeded`](#foley.cost.BudgetExceeded)

Raised before a call whose cost is unknown, when the budget has not approved that.

### foley.cost.DEFAULT_MAX_USD *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 1.0*

The default cumulative cap for one run (a `find` / `score` / `generate` call).

### foley.cost.DEFAULT_MAX_USD_BY_LLM *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]* *= {'anthropic': 3.0}*

The default cap of a [`foley.find()`](foley.html.md#foley.find) run whose LLM rungs the caller chose to pay
for (`llm=` or `$FOLEY_LLM`), keyed by provider. With the defaults (6 events,
`k=10`, `verify='listen'`) Claude’s upper bound is about $2.52, so the $1 cap
would refuse every such run before its first call; $3 lets it run and still caps
it. A run usually spends far less than its bound (#88). `Budget(max_usd=...)`
overrides it.

### foley.cost.active_budget()

The innermost [`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget) of the current run, or `None`.

### foley.cost.authorize(estimate_usd, , what)

Admit a paid call: every budget in force must afford it, and each reserves it.

The reservation is atomic per budget, so concurrent calls cannot all pass before
any is counted. Call [`settle()`](#foley.cost.settle) afterwards with the actual cost when known; a
call that fails after being sent keeps its reservation (it may have been billed);
one refused before sending is released with [`release()`](#foley.cost.release).

* **Raises:**
  * [**CostApprovalRequired**](#foley.cost.CostApprovalRequired) – If `estimate_usd` is `None` and a budget in force has
        not approved unknown costs (`Budget.approve_unknown_cost` /
        `$FOLEY_APPROVE_UNKNOWN_COST`).
  * [**BudgetExceeded**](#foley.cost.BudgetExceeded) – If a budget’s spend plus `estimate_usd` exceeds its `max_usd`.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.cost.charge(usd)

Record `usd` against every budget in force (a no-op outside any run).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.cost.check(estimate_usd, , what)

Raise unless every budget in force can afford `estimate_usd` (reserves nothing).

For a whole-run upper bound (`find`’s pre-flight).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.cost.default_max_usd(llm=None)

The cap of a run given no budget: higher when the caller chose a paid LLM.

The provider is the one named by `llm` or, failing that, `$FOLEY_LLM` (the
free default never resolves to a paid one); see [`DEFAULT_MAX_USD_BY_LLM`](#foley.cost.DEFAULT_MAX_USD_BY_LLM).

```pycon
>>> default_max_usd("fake")
1.0
>>> default_max_usd("anthropic")
3.0
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.cost.estimate_call(config, \*\*affordances)

The USD cost of one call to the source `config` declares, or `None` if unknown.

`config['pricing']` units:

* `'free'` (local inference, a free API tier) → `0.0`;
* `'per_call'` → `amount_usd`;
* `'per_second'` → `amount_usd` × the requested `duration`; when none is
  requested, × the `native_defaults['duration_default_s']` the adapter sends in
  its place, else × `native_defaults['duration_max_s']` (the duration is left to
  the backend: an upper bound), else `None`.

* **Parameters:**
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – A `SOURCE_CONFIG`.
  * **\*\*affordances** – The canonical affordances of the call (`duration`, …).
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.cost.release(reserved_usd)

Undo a reservation for a call that was never sent.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.cost.scoped_iter(iterator_factory, budget=None)

Iterate `iterator_factory()` with `budget` in force only while it runs.

A generator that holds a [`spend_scope()`](#foley.cost.spend_scope) across `yield` would leave its
budget active in the caller’s context between items (so the caller’s own calls, or
another interleaved stream, would charge it). This re-enters the scope for each
step and leaves it before handing the item out; closing the stream closes the
inner iterator inside the scope too.

### foley.cost.settle(reserved_usd, actual_usd)

Replace each budget’s reservation with the actual cost (`None`: keep it).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.cost.spend_scope(budget=None)

Put `budget` in force for the block; every enclosing budget stays in force too.

Budgets stack: a paid call must fit **every** budget in force (so an explicit,
stricter `budget` inside a `find` / `score` run still applies) and is charged
to each of them once. With no `budget`: inside a run, nothing changes; outside
one, a fresh default [`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget) is used ($1).

* **Yields:**
  The innermost budget in force.
