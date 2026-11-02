# foley.agent.verify

`verify_match` — the retrieve→verify ladder (clap → listen → judge) + `Judge` impls.

Retrieval gives a ranked shortlist; verification confirms the *intent* before a clip is
accepted (report 05 §3). Three rungs, cheapest first:

* `clap` — [`ClapJudge`](#foley.agent.verify.ClapJudge), the zero-config gate on the retrieval cosine (no ML).
* `listen` — an audio-LM “does this contain {event}?” check; **#7 ships the
  deterministic :class:\`StringOverlapJudge\`** here (caption/tag overlap); the real
  Qwen2-Audio [`AudioLMJudge`](#foley.agent.verify.AudioLMJudge) (`foley[fit]`) is a
  [`Judge`](foley.agent.protocols.html.md#foley.agent.protocols.Judge) behind this same `VerifyLevel` seam.
* `judge` — [`AnthropicJudge`](#foley.agent.verify.AnthropicJudge), an LLM arbiter (ties + scene consistency),
  `foley[agent]`; `anthropic` imported lazily.

The ladder is AND-confirming: the `clap` gate must pass before a higher rung is asked
to confirm. \*\*This module is the extension point #10b (the Tier-2 fit-judge) plugs
into\*\* — a new `Judge` bound at `level=judge` via the `judge=` keyword, with its
own fit-precision metric; it does not touch retrieval ranking (the [nDCG@10](mailto:nDCG@10) gate).

### Module Attributes

| [`AQA_ANSWER_WORDS`](#foley.agent.verify.AQA_ANSWER_WORDS)       | (yes-words, no-words).                                                                                                                                  |
|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`AUDIOLM_LOAD_KWARGS`](#foley.agent.verify.AUDIOLM_LOAD_KWARGS)    | the checkpoint's own dtype (bf16 for Qwen2-Audio, ~15 GB) placed by `accelerate` across what devices there are.                                         |
| [`MODEL_ONLY_LOAD_KWARGS`](#foley.agent.verify.MODEL_ONLY_LOAD_KWARGS) | `load_kwargs` that only the model takes; the rest (`revision`, `cache_dir`, `token`, ...) also go to the processor so both come from the same snapshot. |

### Functions

| [`aqa_conversation`](#foley.agent.verify.aqa_conversation)(prompt)                          | The one-turn chat the audio-LM sees: the clip as an audio part, then `prompt`.   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`qwen2_audio_pipeline`](#foley.agent.verify.qwen2_audio_pipeline)(processor, model, \*[, ...]) | The `(prompt, wav, sr) -> {'p_yes', 'p_no'}` pipeline over a loaded Qwen2-Audio. |
| [`verify_match`](#foley.agent.verify.verify_match)(event, candidate, \*[, level, ...])  | Verify `candidate` against `event` up to rung `level` (AND-confirming ladder).   |

### Classes

| [`AnthropicJudge`](#foley.agent.verify.AnthropicJudge)(\*[, client, model, max_tokens])   | LLM arbiter for the `judge` rung (`foley[agent]`): Claude → a `Verdict`.             |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`AudioLMJudge`](#foley.agent.verify.AudioLMJudge)(\*[, pipeline, model, ...])          | The audio-LM `listen` rung (`foley[fit]`): Qwen2-Audio "does this contain {event}?". |
| [`ClapJudge`](#foley.agent.verify.ClapJudge)()                                       | The zero-config `clap` rung: gate on the retrieval cosine (no ML, no network).       |
| [`StringOverlapJudge`](#foley.agent.verify.StringOverlapJudge)(\*[, threshold])               | Deterministic stand-in for the `listen`/`judge` rungs (the hermetic CI fake).        |

### foley.agent.verify.AQA_ANSWER_WORDS *= (('Yes', 'yes'), ('No', 'no'))*

(yes-words, no-words). Each must be
a single token; P(yes) is the softmax mass on the yes-group over both groups.

* **Type:**
  The answer spellings AQAScore reads P(yes) from

### foley.agent.verify.AUDIOLM_LOAD_KWARGS *= {'device_map': 'auto', 'dtype': 'auto'}*

the checkpoint’s own dtype (bf16 for
Qwen2-Audio, ~15 GB) placed by `accelerate` across what devices there are.

* **Type:**
  `from_pretrained` options for the audio-LM

### *class* foley.agent.verify.AnthropicJudge(, client=None, model='claude-opus-4-8', max_tokens=500)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LLM arbiter for the `judge` rung (`foley[agent]`): Claude → a `Verdict`.

`anthropic` imported lazily inside [`judge()`](#foley.agent.verify.AnthropicJudge.judge). Stashes the `Message` on
`self.last_response` for the GenAI span.

#### judge(event, candidate, , level=VerifyLevel.judge)

Call Claude to arbitrate the match; returns a `Verdict` at `level`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### *class* foley.agent.verify.AudioLMJudge(, pipeline=None, model='Qwen/Qwen2-Audio-7B-Instruct', max_tokens=300, tau=0.5, load_kwargs=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The audio-LM `listen` rung (`foley[fit]`): Qwen2-Audio “does this contain {event}?”.

With no `pipeline`, the first [`judge()`](#foley.agent.verify.AudioLMJudge.judge) loads `model` (`transformers`,
`torch`, imported lazily; the 7B weights download on first use) and reads
P(yes) from one forward pass ([`qwen2_audio_pipeline()`](#foley.agent.verify.qwen2_audio_pipeline)); later calls reuse it.
An injected `pipeline` (the test seam, mirroring the Stable-Audio fake-pipeline
seam) drives the whole byte-decode → prompt → P(yes) → `Verdict` path with
no torch. Stashes `self.model` + `self.last_response` so `verify_match`’s
GenAI span stays informative (same getattr contract [`AnthropicJudge`](#foley.agent.verify.AnthropicJudge) uses).

* **Parameters:**
  * **pipeline** – `(prompt, wav, sr) -> {'p_yes': float}` or yes/no text.
  * **model** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The Hugging Face checkpoint to load when no pipeline is given.
  * **max_tokens** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Kept for the GenAI span contract (the read-out generates none).
  * **tau** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The P(yes) threshold for a match.
  * **load_kwargs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – `from_pretrained` options (default [`AUDIOLM_LOAD_KWARGS`](#foley.agent.verify.AUDIOLM_LOAD_KWARGS)).

#### judge(event, candidate, , level=VerifyLevel.listen)

Listen to the clip and return the AQAScore `Verdict` (`P(yes) ≥ tau`).

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### *class* foley.agent.verify.ClapJudge

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The zero-config `clap` rung: gate on the retrieval cosine (no ML, no network).

`match` iff the candidate’s `clap_score` clears `tau_clap`; `confidence` is
the score clamped to `0..1` so it is comparable to the higher rungs’ 0..1 scores.

#### judge(event, candidate, , level=VerifyLevel.clap, tau_clap=0.35)

Return the `clap`-rung `Verdict` for `candidate`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### foley.agent.verify.MODEL_ONLY_LOAD_KWARGS *= frozenset({'attn_implementation', 'device_map', 'dtype', 'low_cpu_mem_usage', 'max_memory', 'quantization_config', 'torch_dtype'})*

`load_kwargs` that only the model takes; the rest (`revision`, `cache_dir`,
`token`, …) also go to the processor so both come from the same snapshot.

### *class* foley.agent.verify.StringOverlapJudge(, threshold=0.3)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic stand-in for the `listen`/`judge` rungs (the hermetic CI fake).

Jaccard token overlap of the event query vs the candidate’s caption + tags. Lets the
full ladder + [`decide()`](foley.agent.policy.html.md#foley.agent.policy.decide) branch run with zero ML/network. The
returned `Verdict` echoes back the requested `level`.

#### judge(event, candidate, , level=VerifyLevel.listen)

Return the token-overlap `Verdict` at the requested `level`.

* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### foley.agent.verify.aqa_conversation(prompt)

The one-turn chat the audio-LM sees: the clip as an audio part, then `prompt`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.agent.verify.qwen2_audio_pipeline(processor, model, , answers=(('Yes', 'yes'), ('No', 'no')))

The `(prompt, wav, sr) -> {'p_yes', 'p_no'}` pipeline over a loaded Qwen2-Audio.

One forward pass, no generation: the clip (mono, resampled to the processor’s
rate) and the question go through the chat template with the assistant turn
opened, and P(yes) is the next-token softmax mass on the yes-spellings, over the
yes- and no-spellings together (the AQAScore read-out, report 08 §2.1). A clip
longer than the feature extractor’s window (Whisper’s 30 s) is truncated by it,
so that is warned about.

### foley.agent.verify.verify_match(event, candidate, , level=VerifyLevel.clap, judge=None, tau_clap=0.35, \_span=None)

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
