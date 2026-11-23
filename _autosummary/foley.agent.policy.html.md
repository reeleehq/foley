# foley.agent.policy

The SELECT policy: the fail-closed rights gate + the single generate-vs-retrieve branch.

Two load-bearing invariants live here as two **physically separate pure functions**, so
neither can bypass the other:

* [`gate_candidates()`](#foley.agent.policy.gate_candidates) — the rights gate of the SELECT loop. Runs the fail-closed
  [`foley.licensing.checked_refusal_reason()`](foley.licensing.html.md#foley.licensing.checked_refusal_reason) rule over the candidate set **before**
  > any verification/ranking (invariant #3), sets `Candidate.license_ok`, and drops
  > every non-`True` candidate. The same rule re-checks placed sounds where they are
  > used ([`foley.licensing.refusals()`](foley.licensing.html.md#foley.licensing.refusals), the MCP plan/weave verbs, #191).
* [`decide()`](#foley.agent.policy.decide) — the ONLY generate-vs-retrieve branch. A **pure** function of an
  already-gated+verified set; it never calls `keep`/`search`/`generate` (the
  [`foley.agent.tools`](foley.agent.tools.html.md#module-foley.agent.tools) loop owns all side effects).

[`Budget`](#foley.agent.policy.Budget) bounds the refine→re-retrieve and generate loops so a hard event can’t
run away. This module is stdlib-only (imports only [`foley.base`](foley.base.html.md#module-foley.base) /
[`foley.licensing`](foley.licensing.html.md#module-foley.licensing)) and does no I/O and no obs — the loop emits the audit Steps.

### Module Attributes

| [`SPEND_TOLERANCE_USD`](#foley.agent.policy.SPEND_TOLERANCE_USD)   | a run that lands on `max_usd` through float addition is within it, for the next call's check and for `overshoot_usd` alike (#316).   |
|------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`decide`](#foley.agent.policy.decide)(event, kept, verified, \*, ...)    | The single generate-vs-retrieve branch — a PURE function (report 05 §4).   |
|--------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`gate_candidates`](#foley.agent.policy.gate_candidates)(candidates, intended_use) | Fail-closed license gate — run BEFORE verification/ranking (invariant #3). |

### Classes

| [`Budget`](#foley.agent.policy.Budget)([max_refine_loops, max_generations, ...])   | Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).                                             |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`DecideAction`](#foley.agent.policy.DecideAction)(\*values)                             | What [`decide()`](#foley.agent.policy.decide) chose for one event (the single branch's outcomes).             |
| [`Decision`](#foley.agent.policy.Decision)(action[, candidate, reason])              | The tiny result of [`decide()`](#foley.agent.policy.decide); `reason` feeds the refine hint + the audit Step. |

### *class* foley.agent.policy.Budget(max_refine_loops=1, max_generations=1, allow_generate=True, max_usd=1.0, approve_unknown_cost=None, \_refines=0, \_gens=0, \_spent_usd=0.0, \_unknown_calls=0, \_lock=allocate_lock())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).

Two kinds of bound:

* **Per event** — `max_refine_loops` / `max_generations`: the loop calls
  [`refine_ok()`](#foley.agent.policy.Budget.refine_ok) / [`gen_ok()`](#foley.agent.policy.Budget.gen_ok) to test, then [`spend_refine()`](#foley.agent.policy.Budget.spend_refine) /
  [`spend_gen()`](#foley.agent.policy.Budget.spend_gen) to charge; [`reset()`](#foley.agent.policy.Budget.reset) zeroes them at each event.
* **Per run, cumulative** — `max_usd` (default $1): every paid call (generation,
  paid LLM rung) is checked with [`authorize()`](#foley.agent.policy.Budget.authorize) before it is made and recorded with [`charge()`](#foley.agent.policy.Budget.charge)
  after. [`reset()`](#foley.agent.policy.Budget.reset) never clears it, so the cap holds across the whole
  `find` / `score` run. A call whose cost is unknown (estimate `None`) is
  refused unless `approve_unknown_cost` (or `$FOLEY_APPROVE_UNKNOWN_COST=1`).

#### authorize(estimate_usd, , what)

Alias of [`check()`](#foley.agent.policy.Budget.check) (kept for callers that only test affordability).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### charge(usd)

Record a call’s cost (`None` = unknown: counted, not summed).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### check(estimate_usd, , what)

Raise if this run cannot afford `estimate_usd` (nothing is reserved).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### gen_ok()

Whether a generation fallback is allowed and within budget.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *property* overshoot_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Dollars spent above `max_usd` (`0.0` while within the cap) (#293).

The cap is checked before each call against its *estimate*; [`settle()`](#foley.agent.policy.Budget.settle)
then records the actual cost, which can be higher, so a run can end above the
cap. This is that excess, so a host can say “at most the cap, plus this” and
clamp a quote honestly. Once it is above zero every further paid call is refused
([`check()`](#foley.agent.policy.Budget.check) sees `spent_usd` over the cap).

```pycon
>>> b = Budget(max_usd=0.5)
>>> b.reserve(0.4, what="x"); b.settle(0.4, 0.7)
>>> round(b.overshoot_usd, 10), round(b.spent_usd, 10)
(0.2, 0.7)
```

#### refine_ok()

Whether another refine→re-retrieve pass is within budget.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### reserve(estimate_usd, , what)

Check, then count `estimate_usd` as spent at once (atomic under a lock).

Reserving before the call is what keeps concurrent calls on one budget (MCP
tools run in a threadpool) from all passing the check before any is charged.
[`settle()`](#foley.agent.policy.Budget.settle) later replaces the reservation with the actual cost, if known.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### reset()

Zero the spend counters so the caps apply *per event*, not per passage.

The `find` loop calls this at the top of each event so one hard event’s
refine/generate spend never starves later events (the documented per-event
semantics).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### settle(reserved_usd, actual_usd)

Replace a reservation with the actual cost (`None` actual: keep the reservation).

A reservation of unknown cost (`None` reserved, counted as an unknown call)
settled with a known actual becomes that actual: it is summed, and no longer
counted as unknown (#186: a source billed per compute second, priced after).
Settling a known reservation with an equal actual changes nothing. An actual
above the reservation can take the run over `max_usd`: it is still recorded
(never hidden), shows as [`overshoot_usd`](#foley.agent.policy.Budget.overshoot_usd), and the next paid call is refused.

```pycon
>>> b = Budget(approve_unknown_cost=True)
>>> b.reserve(None, what="x"); b.settle(None, 0.0425)
>>> b.spent_usd, b._unknown_calls
(0.0425, 0)
>>> b.reserve(0.1, what="y"); b.settle(0.1, 0.1)
>>> round(b.spent_usd, 10)
0.1425
```

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### spend_gen()

Charge one generation.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### spend_refine()

Charge one refine loop.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* spent_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Dollars charged so far this run (calls of unknown cost count as 0 here).

#### *property* unknown_cost_calls *: [int](https://docs.python.org/3/builtins/functions.html#int)*

How many calls this run made whose cost is still unknown (not in [`spent_usd`](#foley.agent.policy.Budget.spent_usd)).

Each one was approved (`approve_unknown_cost`); `spent_usd` is then a
lower bound, never the whole cost.

#### without_generation()

A fresh budget with these limits and the generation fallback off.

For a retrieval-only run (`foley.score(allow_generate=False)`). The copy’s
counters start at zero; spend made while it is in force is still charged to
every enclosing budget ([`foley.cost.spend_scope()`](foley.cost.html.md#foley.cost.spend_scope)), so this one’s cap holds.

* **Return type:**
  [`Budget`](#foley.agent.policy.Budget)

### *class* foley.agent.policy.DecideAction(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

What [`decide()`](#foley.agent.policy.decide) chose for one event (the single branch’s outcomes).

### *class* foley.agent.policy.Decision(action, candidate=None, reason='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The tiny result of [`decide()`](#foley.agent.policy.decide); `reason` feeds the refine hint + the audit Step.

### foley.agent.policy.SPEND_TOLERANCE_USD *= 1e-12*

a run that lands on `max_usd` through float
addition is within it, for the next call’s check and for `overshoot_usd` alike (#316).

* **Type:**
  Float noise allowed on the cap

### foley.agent.policy.decide(event, kept, verified, , tau_retrieve, budget, loop)

The single generate-vs-retrieve branch — a PURE function (report 05 §4).

Chooses among [`DecideAction`](#foley.agent.policy.DecideAction) from the already-gated (`kept`) and
already-verified (`verified`) sets. It performs no I/O and never calls
`keep`/`search`/`generate` — the [`foley.agent.tools`](foley.agent.tools.html.md#module-foley.agent.tools) loop acts on the
returned [`Decision`](#foley.agent.policy.Decision).

Policy (report 05 §4):

> * a verified clip clearing `tau_retrieve` → `USE` (the best one);
> * verified-but-low-confidence with refine budget → `REFINE` (feed the reason back);
> * a non-diegetic cue, or a diegetic gap with no verified match, with generate budget
>   → `GENERATE`;
> * otherwise → `DROP` (silence), unless a lower-confidence verified clip exists and
>   generation is off, in which case fall back to that best-effort pick.
* **Parameters:**
  * **event** ([`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)) – The event being resolved.
  * **kept** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The license-clean candidates (each `license_ok is True`).
  * **verified** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The subset of `kept` whose verdict matched.
  * **tau_retrieve** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The confidence threshold for auto-accepting a retrieved clip.
  * **budget** ([`Budget`](#foley.agent.policy.Budget)) – The per-event cost budget.
  * **loop** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The current refine-loop index (for the audit reason).
* **Return type:**
  [`Decision`](#foley.agent.policy.Decision)
* **Returns:**
  A [`Decision`](#foley.agent.policy.Decision).

### foley.agent.policy.gate_candidates(candidates, intended_use)

Fail-closed license gate — run BEFORE verification/ranking (invariant #3).

For each candidate: apply [`checked_refusal_reason()`](foley.licensing.html.md#foley.licensing.checked_refusal_reason) to its
sound’s licence (any error ⇒ refused, fail-closed), record whether it is kept on
`candidate.license_ok`, and keep ONLY where it is `True` — a `None` (never
gated) or `False` is dropped. [`verify_match()`](foley.agent.verify.html.md#foley.agent.verify.verify_match) asserts its
survivors are license-clean.

* **Parameters:**
  * **candidates** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The retrieved shortlist (`license_ok` typically `None`).
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared rights intent.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  The license-clean sublist (each with `license_ok is True`), order preserved.
