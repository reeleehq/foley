# foley.agent.protocols

The structural DI seams of the SELECT stage — `Decomposer` / `Judge` / `Refiner`.

Three `@runtime_checkable` [`typing.Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)s (PEP 544), each a
behaviour-free, open-closed contract that every implementation (the deterministic
fake *and* the Anthropic-backed real impl) satisfies. They are dependency-injected
into [`foley.agent.find()`](foley.agent.html.md#foley.agent.find) by keyword (`decomposer=` / `judge=` / `refiner=`),
defaulting to a hermetic fake when `anthropic` (the `foley[agent]` extra) is absent.

Stdlib-only: the `base` shapes are imported under `TYPE_CHECKING` only (mirroring
[`foley.index.protocols`](foley.index.protocols.html.md#module-foley.index.protocols)), so importing this module pulls no heavy dependency and
keeps `import foley` dol-only.

### Classes

| [`Decomposer`](#foley.agent.protocols.Decomposer)(\*args, \*\*kwargs)   | Narrative context → a sparse, salience-ranked, diegetic-tagged event list.             |
|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| [`Judge`](#foley.agent.protocols.Judge)(\*args, \*\*kwargs)        | One rung of the verify ladder: does this candidate match this event? (report 10 §4.2). |
| [`Refiner`](#foley.agent.protocols.Refiner)(\*args, \*\*kwargs)      | One event query → 2–4 paraphrases/expansions (query-expansion for retrieval).          |

### *class* foley.agent.protocols.Decomposer(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Narrative context → a sparse, salience-ranked, diegetic-tagged event list.

Turns a story/commentary passage into `<= max_events` `SoundEvent`s,
enforcing the salience/density budget and the anachronism (`era_place`) guard.
The default is the deterministic [`KeywordDecomposer`](foley.agent.decompose.html.md#foley.agent.decompose.KeywordDecomposer);
[`AnthropicDecomposer`](foley.agent.decompose.html.md#foley.agent.decompose.AnthropicDecomposer) is the LLM-backed impl.

#### decompose(context, , max_events=6, seconds=None)

Decompose `context` into at most `max_events` sound events.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)]

### *class* foley.agent.protocols.Judge(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One rung of the verify ladder: does this candidate match this event? (report 10 §4.2).

`level` selects the rung — `clap` (cheap score gate),
`listen` (audio-LM), `judge` (LLM arbitration + scene consistency). The
returned `Verdict` carries `level` == the rung that produced it. Only the
`judge` rung’s real impl calls the LLM.

#### judge(event, candidate, , level=Ellipsis)

Judge whether `candidate` matches `event` at verify rung `level`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### *class* foley.agent.protocols.Refiner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One event query → 2–4 paraphrases/expansions (query-expansion for retrieval).

`hint` carries the verify-failure reason so the re-retrieval loop can steer the
next paraphrases. v1 feeds the list into a multi-query RRF search (embedding-fusion
is a later drop-in behind this same seam). The default is the deterministic
[`KeywordRefiner`](foley.agent.refine.html.md#foley.agent.refine.KeywordRefiner).

#### refine(query, , n=3, hint=None)

Return `n` paraphrases of `query`, steered by `hint` when given.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
