# foley.agent

The SELECT stage — the search-agent that finds the right sound for a context (#7).

The headline capability: a narrative *context* → verified, license-clean sound
candidates, and the sparse plan that places them. The loop (report 05 §5):

> decompose_context → (per event) refine_query / search_sounds
> : → gate_candidates (fail-closed license gate, FIRST)
>   → verify_match (clap → listen → judge ladder)
>   → decide (retrieve-vs-generate, the single branch)
>   → place_in_timeline → a sparse SoundDesignTimeline

Design discipline (mirrors `foley.index`): this package is **dol-only at import** —
the LLM rungs sit behind the [`Decomposer`](#foley.agent.Decomposer) / [`Judge`](#foley.agent.Judge) / [`Refiner`](#foley.agent.Refiner)
protocols with deterministic fakes as defaults, and `anthropic` (the `foley[agent]`
extra) is imported lazily inside the real impls only. So `foley.find("a paragraph")`
works out of the box and the whole loop is exercisable in CI with no network / key /
heavy dependency. Every `find()` opens one `foley.obs` run scope, so search +
verify + generate aggregate into a single reproducible run-manifest.

### Functions

| [`find`](#foley.agent.find)(context, \*[, max_events, seconds, ...])       | The headline: a narrative context → verified, license-clean sound candidates.             |
|------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`plan`](#foley.agent.plan)(candidates, \*[, transcript])                  | Fold verified candidates into the SPARSE `SoundDesignTimeline` (the SELECT→WEAVE bridge). |
| [`decompose_context`](#foley.agent.decompose_context)(context, \*[, max_events, ...])   | Decompose a passage into `<= max_events` sparse `SoundEvent`s.                            |
| [`refine_query`](#foley.agent.refine_query)(query, \*[, n, hint, refiner, \_span]) | Expand `query` into up to `n` paraphrases for multi-query retrieval.                      |
| [`search_sounds`](#foley.agent.search_sounds)(queries, \*[, k, library, filters])   | Hybrid search for one query, or a multi-query RRF-merge (the SELECT retrieval tool).      |
| [`verify_match`](#foley.agent.verify_match)(event, candidate, \*[, level, ...])    | Verify `candidate` against `event` up to rung `level` (AND-confirming ladder).            |
| [`gate_candidates`](#foley.agent.gate_candidates)(candidates, intended_use)           | Fail-closed license gate — run BEFORE verification/ranking (invariant #3).                |
| [`decide`](#foley.agent.decide)(event, kept, verified, \*, ...)              | The single generate-vs-retrieve branch — a PURE function (report 05 §4).                  |
| [`generate_sound`](#foley.agent.generate_sound)(query, \*[, backend, library, ...])  | Generate a clip for `query` (the fallback tool) — a thin wrapper over `foley.generate`.   |
| [`place_in_timeline`](#foley.agent.place_in_timeline)(clip, \*[, onset, gain, ...])     | Emit the SPARSE per-item plan subset (`clip_ref·onset·gain·layer·loop`) — no more.        |

### Classes

| [`Decomposer`](#foley.agent.Decomposer)(\*args, \*\*kwargs)                    | Narrative context → a sparse, salience-ranked, diegetic-tagged event list.                                                     |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`Judge`](#foley.agent.Judge)(\*args, \*\*kwargs)                         | One rung of the verify ladder: does this candidate match this event? (report 10 §4.2).                                         |
| [`Refiner`](#foley.agent.Refiner)(\*args, \*\*kwargs)                       | One event query → 2–4 paraphrases/expansions (query-expansion for retrieval).                                                  |
| [`Budget`](#foley.agent.Budget)([max_refine_loops, max_generations, ...])  | Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).                                             |
| [`Decision`](#foley.agent.Decision)(action[, candidate, reason])             | The tiny result of [`decide()`](#foley.agent.decide); `reason` feeds the refine hint + the audit Step. |
| [`DecideAction`](#foley.agent.DecideAction)(\*values)                            | What [`decide()`](#foley.agent.decide) chose for one event (the single branch's outcomes).             |
| [`KeywordDecomposer`](#foley.agent.KeywordDecomposer)()                               | Deterministic cue-lexicon decomposer — the zero-dependency default and CI fake.                                                |
| [`AnthropicDecomposer`](#foley.agent.AnthropicDecomposer)(\*[, client, model, ...])     | LLM-backed decomposer (`foley[agent]`): Claude → a structured event list.                                                      |
| [`KeywordRefiner`](#foley.agent.KeywordRefiner)()                                  | Deterministic template-expansion refiner — the default and CI fake.                                                            |
| [`AnthropicRefiner`](#foley.agent.AnthropicRefiner)(\*[, client, model, max_tokens]) | LLM-backed refiner (`foley[agent]`): Claude → a paraphrase list.                                                               |
| [`ClapJudge`](#foley.agent.ClapJudge)()                                       | The zero-config `clap` rung: gate on the retrieval cosine (no ML, no network).                                                 |
| [`StringOverlapJudge`](#foley.agent.StringOverlapJudge)(\*[, threshold])               | Deterministic stand-in for the `listen`/`judge` rungs (the hermetic CI fake).                                                  |
| [`AnthropicJudge`](#foley.agent.AnthropicJudge)(\*[, client, model, max_tokens])   | LLM arbiter for the `judge` rung (`foley[agent]`): Claude → a `Verdict`.                                                       |
| [`AudioLMJudge`](#foley.agent.AudioLMJudge)(\*[, pipeline, model, ...])          | The audio-LM `listen` rung (`foley[fit]`): Qwen2-Audio "does this contain {event}?".                                           |

### *class* foley.agent.AnthropicDecomposer(, client=None, model='claude-opus-4-8', max_tokens=2000)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LLM-backed decomposer (`foley[agent]`): Claude → a structured event list.

`anthropic` is imported lazily inside [`decompose()`](foley.agent.decompose.html.md#module-foley.agent.decompose) so `import foley` stays
dol-only. Stashes the returned `Message` on `self.last_response` so
[`decompose_context()`](#foley.agent.decompose_context) can record the GenAI span (token usage / model /
stop_reason). Model, thinking, and structured-output shape follow the `claude-api`
conventions (`claude-opus-4-8`, adaptive thinking — never `budget_tokens`).

#### decompose(context, , max_events=6, seconds=None)

Call Claude and round-trip each event through `SoundEvent.from_dict()`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)]

### *class* foley.agent.AnthropicJudge(, client=None, model='claude-opus-4-8', max_tokens=500)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LLM arbiter for the `judge` rung (`foley[agent]`): Claude → a `Verdict`.

`anthropic` imported lazily inside [`judge()`](#foley.agent.AnthropicJudge.judge). Stashes the `Message` on
`self.last_response` for the GenAI span.

#### judge(event, candidate, , level=VerifyLevel.judge)

Call Claude to arbitrate the match; returns a `Verdict` at `level`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### *class* foley.agent.AnthropicRefiner(, client=None, model='claude-opus-4-8', max_tokens=500)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LLM-backed refiner (`foley[agent]`): Claude → a paraphrase list.

`anthropic` imported lazily inside [`refine()`](foley.agent.refine.html.md#module-foley.agent.refine). Stashes the `Message` on
`self.last_response` for the GenAI span.

#### refine(query, , n=3, hint=None)

Call Claude for `n` paraphrases; the original `query` is always first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.agent.AudioLMJudge(, pipeline=None, model='Qwen/Qwen2-Audio-7B-Instruct', max_tokens=300, tau=0.5)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The audio-LM `listen` rung (`foley[fit]`): Qwen2-Audio “does this contain {event}?”.

`transformers`/`torch` are imported lazily inside [`judge()`](#foley.agent.AudioLMJudge.judge); an injected
`pipeline` (the test seam, mirroring the Stable-Audio fake-pipeline seam) drives the
whole byte-decode → prompt → P(yes) → `Verdict` path with no torch. Stashes
`self.model` + `self.last_response` so `verify_match`’s GenAI span stays
informative (same getattr contract [`AnthropicJudge`](#foley.agent.AnthropicJudge) uses).

#### judge(event, candidate, , level=VerifyLevel.listen)

Listen to the clip and return the AQAScore `Verdict` (`P(yes) ≥ tau`).

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### *class* foley.agent.Budget(max_refine_loops=1, max_generations=1, allow_generate=True, max_usd=1.0, approve_unknown_cost=None, \_refines=0, \_gens=0, \_spent_usd=0.0, \_unknown_calls=0, \_lock=allocate_lock())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).

Two kinds of bound:

* **Per event** — `max_refine_loops` / `max_generations`: the loop calls
  [`refine_ok()`](#foley.agent.Budget.refine_ok) / [`gen_ok()`](#foley.agent.Budget.gen_ok) to test, then [`spend_refine()`](#foley.agent.Budget.spend_refine) /
  [`spend_gen()`](#foley.agent.Budget.spend_gen) to charge; [`reset()`](#foley.agent.Budget.reset) zeroes them at each event.
* **Per run, cumulative** — `max_usd` (default $1): every paid call (generation,
  paid LLM rung) is checked with [`authorize()`](#foley.agent.Budget.authorize) before it is made and recorded with [`charge()`](#foley.agent.Budget.charge)
  after. [`reset()`](#foley.agent.Budget.reset) never clears it, so the cap holds across the whole
  `find` / `score` run. A call whose cost is unknown (estimate `None`) is
  refused unless `approve_unknown_cost` (or `$FOLEY_APPROVE_UNKNOWN_COST=1`).

#### authorize(estimate_usd, , what)

Alias of [`check()`](#foley.agent.Budget.check) (kept for callers that only test affordability).

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
[`settle()`](#foley.agent.Budget.settle) later replaces the reservation with the actual cost, if known.

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

### *class* foley.agent.ClapJudge

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The zero-config `clap` rung: gate on the retrieval cosine (no ML, no network).

`match` iff the candidate’s `clap_score` clears `tau_clap`; `confidence` is
the score clamped to `0..1` so it is comparable to the higher rungs’ 0..1 scores.

#### judge(event, candidate, , level=VerifyLevel.clap, tau_clap=0.35)

Return the `clap`-rung `Verdict` for `candidate`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### *class* foley.agent.DecideAction(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

What [`decide()`](#foley.agent.decide) chose for one event (the single branch’s outcomes).

### *class* foley.agent.Decision(action, candidate=None, reason='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The tiny result of [`decide()`](#foley.agent.decide); `reason` feeds the refine hint + the audit Step.

### *class* foley.agent.Decomposer(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Narrative context → a sparse, salience-ranked, diegetic-tagged event list.

Turns a story/commentary passage into `<= max_events` `SoundEvent`s,
enforcing the salience/density budget and the anachronism (`era_place`) guard.
The default is the deterministic [`KeywordDecomposer`](foley.agent.decompose.html.md#foley.agent.decompose.KeywordDecomposer);
[`AnthropicDecomposer`](foley.agent.decompose.html.md#foley.agent.decompose.AnthropicDecomposer) is the LLM-backed impl.

### *class* foley.agent.Judge(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One rung of the verify ladder: does this candidate match this event? (report 10 §4.2).

`level` selects the rung — `clap` (cheap score gate),
`listen` (audio-LM), `judge` (LLM arbitration + scene consistency). The
returned `Verdict` carries `level` == the rung that produced it. Only the
`judge` rung’s real impl calls the LLM.

### *class* foley.agent.KeywordDecomposer

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic cue-lexicon decomposer — the zero-dependency default and CI fake.

Scans the passage against `_CUE_LEXICON`, emits one `SoundEvent` per
matched cue in first-appearance order (so salience descends with reading order),
dedupes by canonical query, and truncates to `max_events` (the sparse density
budget). No RNG, no network, no `anthropic` — same passage → identical list.

#### decompose(context, , max_events=6, seconds=None)

Return `<= max_events` deterministic `SoundEvent`s for `context`.

* **Parameters:**
  * **context** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The narrative passage.
  * **max_events** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sparse density cap (the salience budget).
  * **seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Accepted for signature parity (the per-second density window is a
    later refinement); ignored here.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)]

### *class* foley.agent.KeywordRefiner

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic template-expansion refiner — the default and CI fake.

Expands a query into `n` distinct paraphrases via fixed descriptor templates; a
verify-failure `hint` nudges one extra variant. No RNG, no `anthropic` — same
query → identical paraphrase list.

#### refine(query, , n=3, hint=None)

Return up to `n` distinct paraphrases of `query` (the first is `query`).

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The event query to expand.
  * **n** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many paraphrases to return (2–4 is typical).
  * **hint** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional verify-failure reason to steer re-retrieval.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.agent.Refiner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One event query → 2–4 paraphrases/expansions (query-expansion for retrieval).

`hint` carries the verify-failure reason so the re-retrieval loop can steer the
next paraphrases. v1 feeds the list into a multi-query RRF search (embedding-fusion
is a later drop-in behind this same seam). The default is the deterministic
[`KeywordRefiner`](foley.agent.refine.html.md#foley.agent.refine.KeywordRefiner).

### *class* foley.agent.StringOverlapJudge(, threshold=0.3)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic stand-in for the `listen`/`judge` rungs (the hermetic CI fake).

Jaccard token overlap of the event query vs the candidate’s caption + tags. Lets the
full ladder + [`decide()`](foley.agent.policy.html.md#foley.agent.policy.decide) branch run with zero ML/network. The
returned `Verdict` echoes back the requested `level`.

#### judge(event, candidate, , level=VerifyLevel.listen)

Return the token-overlap `Verdict` at the requested `level`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### foley.agent.decide(event, kept, verified, , tau_retrieve, budget, loop)

The single generate-vs-retrieve branch — a PURE function (report 05 §4).

Chooses among [`DecideAction`](#foley.agent.DecideAction) from the already-gated (`kept`) and
already-verified (`verified`) sets. It performs no I/O and never calls
`keep`/`search`/`generate` — the [`foley.agent.tools`](foley.agent.tools.html.md#module-foley.agent.tools) loop acts on the
returned [`Decision`](#foley.agent.Decision).

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
  * **budget** ([`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget)) – The per-event cost budget.
  * **loop** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The current refine-loop index (for the audit reason).
* **Return type:**
  [`Decision`](foley.agent.policy.html.md#foley.agent.policy.Decision)
* **Returns:**
  A [`Decision`](#foley.agent.Decision).

### foley.agent.decompose_context(context, , max_events=6, seconds=None, decomposer=None, \_span=None)

Decompose a passage into `<= max_events` sparse `SoundEvent`s.

The pure SELECT tool (Python-API == agent == future-MCP surface): resolves the
default decomposer when `decomposer` is `None`, calls it, and records the GenAI
span on the real path (the fake’s `last_response` is `None` → no-op).

* **Parameters:**
  * **context** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The narrative passage.
  * **max_events** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sparse density cap.
  * **seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Optional passage duration (density-window hint; forwarded, else ignored).
  * **decomposer** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Decomposer`](foley.agent.protocols.html.md#foley.agent.protocols.Decomposer)]) – An injected [`Decomposer`](foley.agent.protocols.html.md#foley.agent.protocols.Decomposer) (the DI seam);
    defaults to `_default_decomposer()`.
  * **\_span** – Internal — the obs span handle `find()` opens for GenAI recording.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)]

### foley.agent.find(context, , max_events=6, seconds=None, intended_use=None, backend='auto', verify='listen', stream=False, k=10, tau_retrieve=0.5, tau_clap=0.35, max_refine_loops=1, budget=None, library=None, decomposer=None, judge=None, refiner=None, llm=None)

The headline: a narrative context → verified, license-clean sound candidates.

`decompose → (per event) refine/search → verify_match ladder → decide (with the
fail-closed license gate FIRST) → place` (report 05 §5). Works out of the box —
`foley.find("She pushed open the heavy oak door; rain hammered outside.")` — with
deterministic defaults; every model / threshold / seam is an optional keyword.

* **Parameters:**
  * **context** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The narrative passage.
  * **max_events** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sparse density cap on decomposed events.
  * **seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Optional passage duration (density-window hint; forwarded).
  * **intended_use** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)]) – The caller’s rights intent (default:
    [`foley.licensing.DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE) — commercial publishing;
    NC / SA material is refused unless you pass a different intent).
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Generation backend for the fallback (`'auto'` → `foley.generate`’s default).
  * **verify** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`VerifyLevel`](foley.base.html.md#foley.base.VerifyLevel)]) – The max verify rung — `'clap'` | `'listen'` | `'judge'`.
  * **stream** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, return a generator yielding one `Candidate` per
    resolved event; else return the collected `list`.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Retrieval shortlist depth per query.
  * **tau_retrieve** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Confidence threshold to auto-accept a retrieved clip.
  * **tau_clap** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The `clap`-rung gate threshold.
  * **max_refine_loops** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max refine→re-retrieve passes per event (also the default
    [`Budget`](#foley.agent.Budget)).
  * **budget** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget)]) – An explicit [`Budget`](#foley.agent.Budget) (overrides `max_refine_loops`). It is
    also the run’s spend cap: `Budget(max_usd=...)` (default $1; $3 when
    `llm='anthropic'` or `$FOLEY_LLM=anthropic`, whose default run is
    bounded at about $2.52 — [`foley.cost.DEFAULT_MAX_USD_BY_LLM`](foley.cost.html.md#foley.cost.DEFAULT_MAX_USD_BY_LLM)) bounds
    every paid call the run makes — generations and paid LLM rungs —
    cumulatively, and a call of unknown cost needs
    `Budget(approve_unknown_cost=True)` (#57).
  * **library** – Target `SoundLibrary` (default: the process-wide default).
  * **refiner** (*decomposer / judge /*) – Injected DI seams
    ([`Decomposer`](foley.agent.protocols.html.md#foley.agent.protocols.Decomposer) / `Judge` / `Refiner`);
    each defaults to the `llm` provider’s implementation.
  * **llm** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Which LLM the decompose / refine / judge rungs use when not injected —
    `'fake'` | `'local'` | `'anthropic'`. `None` reads `$FOLEY_LLM`,
    then falls back to the free default (a configured local endpoint, else the
    deterministic fake). A key being present never opts in to paid calls.
* **Return type:**
  [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)], [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]]
* **Returns:**
  `list[Candidate]` (`stream=False`) or an `Iterator[Candidate]`
  (`stream=True`) — one verified, license-clean candidate per resolved event.

### foley.agent.gate_candidates(candidates, intended_use)

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

### foley.agent.generate_sound(query, , backend='auto', library=None, intended_use=None)

Generate a clip for `query` (the fallback tool) — a thin wrapper over `foley.generate`.

`backend='auto'` walks the generation order, passing over backends whose licence
cannot serve `intended_use` (default: commercial) before anything is paid for.
Returns a `Candidate` (`origin=generated`); raises the `GenerationError`
hierarchy on refusal / no-result (caught fail-closed by `_generate_and_reverify()`).

* **Return type:**
  [`Candidate`](foley.base.html.md#foley.base.Candidate)

### foley.agent.place_in_timeline(clip, , onset=None, gain=0.0, layer=Layer.sfx_fg, loop=False)

Emit the SPARSE per-item plan subset (`clip_ref·onset·gain·layer·loop`) — no more.

`onset` stays a SYMBOLIC anchor string (never a resolved offset); mix / processing /
alignment / mastering are WEAVE’s (#8) job, not SELECT’s.

* **Return type:**
  [`TimelineItem`](foley.base.html.md#foley.base.TimelineItem)

### foley.agent.plan(candidates, , transcript=None)

Fold verified candidates into the SPARSE `SoundDesignTimeline` (the SELECT→WEAVE bridge).

One `TimelineItem` per candidate (`onset·gain·layer·loop` only, from its
`SoundEvent`), joined to the run-artifact via `run_manifest_ref` — the
reserved #8 `plan_ref` slot is filled when called inside an active `foley.obs`
run scope (`None`-safe otherwise).

* **Parameters:**
  * **candidates** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The candidates returned by [`find()`](#foley.agent.find).
  * **transcript** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional narration transcript (WEAVE resolves the reference).
* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.agent.refine_query(query, , n=3, hint=None, refiner=None, \_span=None)

Expand `query` into up to `n` paraphrases for multi-query retrieval.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The event query to expand.
  * **n** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of paraphrases.
  * **hint** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional verify-failure reason to steer re-retrieval.
  * **refiner** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Refiner`](foley.agent.protocols.html.md#foley.agent.protocols.Refiner)]) – An injected [`Refiner`](foley.agent.protocols.html.md#foley.agent.protocols.Refiner) (the DI seam);
    defaults to `_default_refiner()`.
  * **\_span** – Internal — the obs span handle for GenAI recording.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.agent.search_sounds(queries, , k=10, library=None, filters=None)

Hybrid search for one query, or a multi-query RRF-merge (the SELECT retrieval tool).

Delegates a single query VERBATIM to `SoundLibrary.search()` (so the retrieval
ranking the [nDCG@10](mailto:nDCG@10) gate measures is untouched); a multi-query list runs each query
and RRF-merges (`k=RRF_K`) — the query-expansion recall lever, exercised only on a
refine pass.

* **Parameters:**
  * **queries** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – One query string, or a list of paraphrases to merge.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of results.
  * **library** – Target library (default: the process-wide default).
  * **filters** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Extra `SoundLibrary.search()` kwargs (e.g. the license prefilter).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

### foley.agent.verify_match(event, candidate, , level=VerifyLevel.clap, judge=None, tau_clap=0.35, \_span=None)

Verify `candidate` against `event` up to rung `level` (AND-confirming ladder).

Runs the `clap` gate always; if `level` is higher **and** the clap gate passed,
escalates to the injected/​default judge for that rung and returns *its* verdict
(`Verdict.level` == the producing rung).

* **Parameters:**
  * **event** ([`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)) – The wanted `SoundEvent`.
  * **candidate** ([`Candidate`](foley.base.html.md#foley.base.Candidate)) – A **license-clean** `Candidate` — this MUST run after the
    [`gate_candidates()`](foley.agent.policy.html.md#foley.agent.policy.gate_candidates) gate (asserted).
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`VerifyLevel`](foley.base.html.md#foley.base.VerifyLevel)) – The max rung to climb (`clap` | `listen` | `judge`).
  * **judge** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Judge`](foley.agent.protocols.html.md#foley.agent.protocols.Judge)]) – An injected [`Judge`](foley.agent.protocols.html.md#foley.agent.protocols.Judge) for the higher rungs
    (the DI seam; defaults per `_default_judge()`).
  * **tau_clap** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The clap-gate threshold.
  * **\_span** – Internal — the obs span handle for GenAI recording on the LLM rung.
* **Raises:**
  [**AssertionError**](https://docs.python.org/3/builtins/exceptions.html#AssertionError) – If `candidate.license_ok` is not `True` (verify-before-gate
      is a bug — the license gate is the fail-closed first pass).
* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### Modules

| [`decompose`](foley.agent.decompose.html.md#module-foley.agent.decompose)   | `decompose_context` — narrative passage → a sparse, salience-ranked event list.           |
|-------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`llm`](foley.agent.llm.html.md#module-foley.agent.llm)               | Which LLM the SELECT rungs use — one explicit, spend-safe resolver (the `llm=` seam).     |
| [`local_llm`](foley.agent.local_llm.html.md#module-foley.agent.local_llm)   | Offline / local-LLM SELECT rungs — OpenAI-compatible `Decomposer` / `Judge` / `Refiner`.  |
| [`mcp`](foley.agent.mcp.html.md#module-foley.agent.mcp)               | The MCP surface — foley's façade as agent-callable tools (py2mcp, #12, report 05/10).     |
| [`policy`](foley.agent.policy.html.md#module-foley.agent.policy)         | The SELECT policy: the fail-closed rights gate + the single generate-vs-retrieve branch.  |
| [`preview`](foley.agent.preview.html.md#module-foley.agent.preview)       | Audition UX — preview a sound, find similar ones, and refine by relevance feedback (#12). |
| [`protocols`](foley.agent.protocols.html.md#module-foley.agent.protocols)   | The structural DI seams of the SELECT stage — `Decomposer` / `Judge` / `Refiner`.         |
| [`refine`](foley.agent.refine.html.md#module-foley.agent.refine)         | `refine_query` — one event query → 2–4 paraphrases for multi-query retrieval.             |
| [`session`](foley.agent.session.html.md#module-foley.agent.session)       | Session-scoped audition state — cached candidates, picks, and rejects (#12).              |
| [`tools`](foley.agent.tools.html.md#module-foley.agent.tools)           | The SELECT orchestration: `find()` / `plan()` + the small pure tool wrappers.             |
| [`verbs`](foley.agent.verbs.html.md#module-foley.agent.verbs)           | foley's JSON-safe verbs: the one table the MCP server and the CLI are built from (#62).   |
| [`verify`](foley.agent.verify.html.md#module-foley.agent.verify)         | `verify_match` — the retrieve→verify ladder (clap → listen → judge) + `Judge` impls.      |
