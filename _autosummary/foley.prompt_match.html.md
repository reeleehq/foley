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

| [`THRESHOLDS_PATH`](#foley.prompt_match.THRESHOLDS_PATH)   | Where the per-checkpoint calibrated thresholds live (package data, so they ship in the wheel).   |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [`MATCH`](#foley.prompt_match.MATCH)             | the clip matches its prompt, does not, or was not checked.                                       |
| [`MISMATCH`](#foley.prompt_match.MISMATCH)          | the clip matches its prompt, does not, or was not checked.                                       |
| [`UNCHECKED`](#foley.prompt_match.UNCHECKED)         | the clip matches its prompt, does not, or was not checked.                                       |

### Functions

| [`calibrated_threshold`](#foley.prompt_match.calibrated_threshold)(model_id[, override])      | An embedder's prompt-match threshold: its override, else the calibration, else `provisional`.             |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| [`load_thresholds`](#foley.prompt_match.load_thresholds)([path])                         | `{model_id: calibration dict}`; empty when nothing has been calibrated.                                   |
| [`note_for`](#foley.prompt_match.note_for)(result)                                | The one-line candidate note for a [`prompt_match()`](#foley.prompt_match.prompt_match) result. |
| [`prompt_match`](#foley.prompt_match.prompt_match)(prompt, audio_bytes, \*, embedder) | Score `audio_bytes` against `prompt` with `embedder`; never raises.                                       |
| [`threshold_for`](#foley.prompt_match.threshold_for)(model_id, \*[, path])             | The calibrated threshold of checkpoint `model_id`, or `None`.                                             |

### foley.prompt_match.MATCH *= 'match'*

the clip matches its prompt, does not, or was not checked.

* **Type:**
  `status` values

### foley.prompt_match.MISMATCH *= 'mismatch'*

the clip matches its prompt, does not, or was not checked.

* **Type:**
  `status` values

### foley.prompt_match.THRESHOLDS_PATH *= PosixPath('/home/runner/work/foley/foley/foley/data/prompt_match/thresholds.json')*

Where the per-checkpoint calibrated thresholds live (package data, so they ship in the
wheel). Written by [`foley.eval.prompt_match.save_threshold()`](foley.eval.prompt_match.html.md#foley.eval.prompt_match.save_threshold).

### foley.prompt_match.UNCHECKED *= 'unchecked'*

the clip matches its prompt, does not, or was not checked.

* **Type:**
  `status` values

### foley.prompt_match.calibrated_threshold(model_id, override=None, , provisional)

An embedder’s prompt-match threshold: its override, else the calibration, else `provisional`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.prompt_match.load_thresholds(path=PosixPath('/home/runner/work/foley/foley/foley/data/prompt_match/thresholds.json'))

`{model_id: calibration dict}`; empty when nothing has been calibrated.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.prompt_match.note_for(result)

The one-line candidate note for a [`prompt_match()`](#foley.prompt_match.prompt_match) result.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.prompt_match.prompt_match(prompt, audio_bytes, , embedder, fallback=None)

Score `audio_bytes` against `prompt` with `embedder`; never raises.

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The text the clip was generated from.
  * **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The clip (any format `soundfile` decodes).
  * **embedder** – A text-audio embedder (`embed_text` / `embed_audio`, L2-normalised
    vectors) carrying `prompt_match_threshold`; anything else is `unchecked`.
  * **fallback** – A callable returning a second embedder (or `None`), tried only when
    `embedder` was meant to check but could not run (it failed to load or
    embed: a small host without `transformers`). Its own threshold applies and
    its model is named in the result. The default `None` tries nothing else.
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

### foley.prompt_match.threshold_for(model_id, , path=PosixPath('/home/runner/work/foley/foley/foley/data/prompt_match/thresholds.json'))

The calibrated threshold of checkpoint `model_id`, or `None`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
