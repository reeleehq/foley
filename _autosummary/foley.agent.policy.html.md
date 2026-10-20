# foley.agent.policy

The SELECT policy: the fail-closed rights gate + the single generate-vs-retrieve branch.

Two load-bearing invariants live here as two **physically separate pure functions**, so
neither can bypass the other:

* [`gate_candidates()`](#foley.agent.policy.gate_candidates) — the ONLY rights-rejection point. Runs the fail-closed
  [`foley.licensing.keep_sound()`](foley.licensing.html.md#foley.licensing.keep_sound) gate over the candidate set **before** any
  > verification/ranking (invariant #3), sets `Candidate.license_ok`, and drops every
  > non-`True` candidate.
* [`decide()`](#foley.agent.policy.decide) — the ONLY generate-vs-retrieve branch. A **pure** function of an
  already-gated+verified set; it never calls `keep`/`search`/`generate` (the
  [`foley.agent.tools`](foley.agent.tools.html.md#module-foley.agent.tools) loop owns all side effects).

[`Budget`](#foley.agent.policy.Budget) bounds the refine→re-retrieve and generate loops so a hard event can’t
run away. This module is stdlib-only (imports only [`foley.base`](foley.base.html.md#module-foley.base) /
[`foley.licensing`](foley.licensing.html.md#module-foley.licensing)) and does no I/O and no obs — the loop emits the audit Steps.

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

### *class* foley.agent.policy.DecideAction(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

What [`decide()`](#foley.agent.policy.decide) chose for one event (the single branch’s outcomes).

### *class* foley.agent.policy.Decision(action, candidate=None, reason='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The tiny result of [`decide()`](#foley.agent.policy.decide); `reason` feeds the refine hint + the audit Step.

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

For each candidate: apply [`keep_sound()`](foley.licensing.html.md#foley.licensing.keep_sound) (any exception ⇒
`False`, fail-closed), record the result on `candidate.license_ok`, and keep
ONLY where it is `True` — a `None` (never gated) or `False` is dropped. This is
the single rights-rejection point; [`verify_match()`](foley.agent.verify.html.md#foley.agent.verify.verify_match) asserts
its survivors are license-clean.

* **Parameters:**
  * **candidates** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The retrieved shortlist (`license_ok` typically `None`).
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared rights intent.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  The license-clean sublist (each with `license_ok is True`), order preserved.
