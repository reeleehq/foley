# foley.eval.aesthetics

Per-clip generation quality from Meta’s Audiobox Aesthetics, run in its own interpreter (#262).

[Audiobox Aesthetics](https://github.com/facebookresearch/audiobox-aesthetics)
(Tjandra et al. 2025, arXiv:2502.05139) predicts four scores, each on about 1 to 10,
for one clip of speech, music or sound: **CE** content enjoyment, **CU** content
usefulness, **PC** production complexity, **PQ** production quality
([`AES_AXES`](#foley.eval.aesthetics.AES_AXES)). It is a WavLM encoder with four regression heads, so it scores a
clip on its own, with no reference set and no prompt: a per-sample signal, where FAD
and KAD ([`foley.eval.fadtk`](foley.eval.fadtk.html.md#module-foley.eval.fadtk), [`foley.eval.kadtk`](foley.eval.kadtk.html.md#module-foley.eval.kadtk)) are set-level.

The package pulls a recent torch and torchaudio foley does not depend on, so
[`AudioboxAesthetics`](#foley.eval.aesthetics.AudioboxAesthetics) runs it through the same mechanism as fadtk and kadtk
([`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit): temporary mono WAVs,
[`foley.eval.toolkit_driver`](foley.eval.toolkit_driver.html.md#module-foley.eval.toolkit_driver) in the toolkit’s interpreter, JSON back):

```default
aes = AudioboxAesthetics(python="~/venvs/aes/bin/python")  # or $FOLEY_AES_PYTHON
[score] = aes([wav], sr=48000)
score.axes  # {'CE': 2.48, 'CU': 5.79, 'PC': 1.74, 'PQ': 6.03}
```

[`aesthetics_verdict()`](#foley.eval.aesthetics.aesthetics_verdict) turns a score into the JSON-safe dict `foley.generate`
records as `qc['aesthetics']` when asked (`generate(..., aesthetics=True)`). It is
a record, not a gate: with no `AudioboxAesthetics.floors` its status is
`'scored'`; with floors, `'low'` flags the clip in the notes, and it is still
stored. The model is not a fault detector: digital silence scored PQ 7.0, above a
clean tone (6.0) and white noise (4.8), so Tier-0 QC ([`foley.qc`](foley.qc.html.md#module-foley.qc)) stays the gate
for broken audio, and no floor is calibrated for SFX yet.

Licences: the code is CC-BY-4.0, with parts from microsoft/unilm under MIT. Meta’s
README states no separate licence for the weights; the Hugging Face repo that holds
them (`facebook/audiobox-aesthetics`, about 415 MB) is tagged `cc-by-4.0`.

### Module Attributes

| [`AES_AXES`](#foley.eval.aesthetics.AES_AXES)       | The four axes, in the toolkit's order, → what each one rates.                          |
|-----------------------------------------------------------------|----------------------------------------------------------------------------------------|
| [`AES_PYTHON_ENV`](#foley.eval.aesthetics.AES_PYTHON_ENV) | The environment variable naming the toolkit's interpreter when `python=` is not given. |

### Functions

| [`aesthetics_verdict`](#foley.eval.aesthetics.aesthetics_verdict)(audio_bytes, \*, scorer)   | Score `audio_bytes` with `scorer` and compare with its `floors`; never raises.                                                                                                                           |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`note_for`](#foley.eval.aesthetics.note_for)(result)                              | The one-line candidate note for an [`aesthetics_verdict()`](#foley.eval.aesthetics.aesthetics_verdict) result.                                                                                         |
| [`resolve_aesthetics`](#foley.eval.aesthetics.resolve_aesthetics)(aesthetics)                | `generate(aesthetics=)` as a scorer: `None`/`False` none, `True` the default [`AudioboxAesthetics`](#foley.eval.aesthetics.AudioboxAesthetics), a scorer (`(wavs, *, sr) -> [AestheticsScore]`) as is. |

### Classes

| [`AestheticsScore`](#foley.eval.aesthetics.AestheticsScore)(axes, model, version[, toolkit])   | One clip's Audiobox Aesthetics scores, stamped with the model and toolkit version.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`AudioboxAesthetics`](#foley.eval.aesthetics.AudioboxAesthetics)(\*[, checkpoint, ...])          | Per-clip Audiobox Aesthetics scores computed in a separate interpreter.              |

### foley.eval.aesthetics.AES_AXES *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {'CE': 'content enjoyment', 'CU': 'content usefulness', 'PC': 'production complexity', 'PQ': 'production quality'}*

The four axes, in the toolkit’s order, → what each one rates.

### foley.eval.aesthetics.AES_PYTHON_ENV *= 'FOLEY_AES_PYTHON'*

The environment variable naming the toolkit’s interpreter when `python=` is not given.

### *class* foley.eval.aesthetics.AestheticsScore(axes, model, version, toolkit='audiobox_aesthetics')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One clip’s Audiobox Aesthetics scores, stamped with the model and toolkit version.

#### to_dict()

The axes and the stamp as one flat JSON-safe dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.eval.aesthetics.AudioboxAesthetics(, checkpoint=None, batch_size=10, min_seconds=0.025, floors=None, timeout=300.0, \*\*kwargs)

Bases: [`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit)

Per-clip Audiobox Aesthetics scores computed in a separate interpreter.

:param those of [`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit) (`python`:
:param :
:param `env`:
:param `timeout`:
:param `runner`):
:param plus:
:type checkpoint: [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
:param checkpoint: A local `checkpoint.pt` (default: the Hugging Face weights,

> downloaded once into the toolkit’s `HF_HOME`; pass
> `env={"HF_HOME": ...}` to choose where).
* **Parameters:**
  * **batch_size** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Clips a forward pass.
  * **min_seconds** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The shortest clip scored (default `AES_MIN_SECONDS`).
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before a run is abandoned (default `AES_TIMEOUT_S`;
    `None` waits forever).
  * **floors** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Axis → the lowest acceptable score, read by
    [`aesthetics_verdict()`](#foley.eval.aesthetics.aesthetics_verdict) (default none: the verdict only records).

#### check_clip(clip, , sr, name)

Refuse a clip shorter than `min_seconds`, or with a NaN or infinite sample.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### failure_hints *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {"No module named 'requests'": "audiobox_aesthetics imports requests without declaring it. Install: uv venv ~/venvs/aes --python 3.11 && uv pip install --python ~/venvs/aes/bin/python audiobox_aesthetics requests; then AudioboxAesthetics(python='~/venvs/aes/bin/python') or set FOLEY_AES_PYTHON"}*

A substring of a failed run’s output → what to do about it.

#### isolation_reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'it brings its own torch and torchaudio, which foley does not depend on'*

Why the toolkit cannot live in foley’s environment (said when no interpreter).

### foley.eval.aesthetics.aesthetics_verdict(audio_bytes, , scorer)

Score `audio_bytes` with `scorer` and compare with its `floors`; never raises.

* **Returns:**
  `status` (`scored` | `ok` | `low` | `unchecked`),
  and the four axes (`None` for a non-finite one), `model`, `toolkit` and
  `version` when scored, plus `floors` and the axes `below` them when the
  scorer has floors; or a short `reason` (`_reason()`: no paths, no program
  output) when not scored: no interpreter, a clip too short, a timeout, a crash,
  a scorer answering anything but one well-formed score.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> import numpy as np
>>> from foley.audio import encode
>>> clip = encode(np.zeros(1600), 16000)
>>> aesthetics_verdict(clip, scorer=lambda wavs, *, sr: [])["reason"]
'ValueError: the scorer returned 0 scores for 1 clip'
```

### foley.eval.aesthetics.note_for(result)

The one-line candidate note for an [`aesthetics_verdict()`](#foley.eval.aesthetics.aesthetics_verdict) result.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.eval.aesthetics.resolve_aesthetics(aesthetics)

`generate(aesthetics=)` as a scorer: `None`/`False` none, `True` the default
[`AudioboxAesthetics`](#foley.eval.aesthetics.AudioboxAesthetics), a scorer (`(wavs, *, sr) -> [AestheticsScore]`) as is.

An external-toolkit scorer’s interpreter is resolved here, so an explicit opt-in
without one fails before anything is paid for (as `watermark=True` does).

* **Raises:**
  * [**FileNotFoundError**](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) – If the scorer’s interpreter is not given or not found.
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – For any other value.
