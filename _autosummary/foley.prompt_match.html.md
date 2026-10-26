# foley.prompt_match

Does a generated clip sound like what was asked for? A text-audio check, or an honest “unchecked”.

Tier-0 QC ([`foley.qc`](foley.qc.html.md#module-foley.qc)) catches broken audio: clipping, silence, NaN. It cannot
catch a clean, well-levelled clip of the wrong thing, and a text-to-audio model
produces those: asked for “a flintlock musket placed into a hand”, Stable Audio 3
returned a sound that had nothing to do with it, and it went through unflagged. That
is the job here: score the clip against its own prompt in a joint text-audio
embedding space (CLAP), and flag it when the score is under the embedder’s threshold.

An embedder takes part only when it says its two spaces are comparable, by carrying a
`prompt_match_threshold` ([`foley.index.embedders.ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder) does). Anything
else, a test’s bag-of-words fake, no embedder at all, an embedder whose model cannot
load on this host, gives `status='unchecked'` with the reason: never a silent pass.

The verdict is a flag, not a quarantine: the clip is kept (it was paid for) and the
candidate’s notes and `record.qc['prompt_match']` say it does not match, so a person
or the SELECT agent listens before using it.

Zero-dependency import: `numpy` and the embedder’s own stack load inside.

### Module Attributes

| [`MATCH`](#foley.prompt_match.MATCH)     | the clip matches its prompt, does not, or was not checked.   |
|------------------------------------------------------------|--------------------------------------------------------------|
| [`MISMATCH`](#foley.prompt_match.MISMATCH)  | the clip matches its prompt, does not, or was not checked.   |
| [`UNCHECKED`](#foley.prompt_match.UNCHECKED) | the clip matches its prompt, does not, or was not checked.   |

### Functions

| [`note_for`](#foley.prompt_match.note_for)(result)                                | The one-line candidate note for a [`prompt_match()`](#foley.prompt_match.prompt_match) result.   |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| [`prompt_match`](#foley.prompt_match.prompt_match)(prompt, audio_bytes, \*, embedder) | Score `audio_bytes` against `prompt` with `embedder`; never raises.                                         |

### foley.prompt_match.MATCH *= 'match'*

the clip matches its prompt, does not, or was not checked.

* **Type:**
  `status` values

### foley.prompt_match.MISMATCH *= 'mismatch'*

the clip matches its prompt, does not, or was not checked.

* **Type:**
  `status` values

### foley.prompt_match.UNCHECKED *= 'unchecked'*

the clip matches its prompt, does not, or was not checked.

* **Type:**
  `status` values

### foley.prompt_match.note_for(result)

The one-line candidate note for a [`prompt_match()`](#foley.prompt_match.prompt_match) result.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.prompt_match.prompt_match(prompt, audio_bytes, , embedder)

Score `audio_bytes` against `prompt` with `embedder`; never raises.

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The text the clip was generated from.
  * **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The clip (any format `soundfile` decodes).
  * **embedder** – A text-audio embedder (`embed_text` / `embed_audio`, L2-normalised
    vectors) carrying `prompt_match_threshold`; anything else is `unchecked`.
* **Returns:**
  `status` (`match` | `mismatch` | `unchecked`), and
  `score` (cosine similarity), `threshold` and `model` when checked, or
  `reason` when not.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> prompt_match("a door creak", b"", embedder=None)["status"]
'unchecked'
```
