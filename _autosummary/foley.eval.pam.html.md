# foley.eval.pam

Per-clip, reference-free audio quality from PAM, run in an `msclap` interpreter (#262).

PAM (Deshmukh et al., “PAM: Prompting Audio-Language Models for Audio Quality
Assessment”, Interspeech 2024, arXiv:2402.00282, [soham97/PAM](https://github.com/soham97/PAM)) scores one clip with no reference set: it asks
Microsoft’s CLAP 2023 audio-language model which of two antonym prompts fits the clip
better, and the score is the softmax probability of the first one,
`"the sound is clear and clean."` against `"the sound is noisy and with artifacts."`
([`PAM_PROMPTS`](#foley.eval.pam.PAM_PROMPTS)). So it is in `[0, 1]`, higher is cleaner. Clips are scored in
7 s windows at 44.1 kHz (the model’s own config); a clip’s score is its windows’ mean.

PAM is a research repository, not a package; its model is the one the `msclap`
package ships (MIT, on PyPI, maintained by Microsoft). `msclap` pins `numpy<2` and
brings its own torch, so [`Pam`](#foley.eval.pam.Pam) is an
[`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit): [`foley.eval.toolkit_driver`](foley.eval.toolkit_driver.html.md#module-foley.eval.toolkit_driver)
runs its `pam` task in msclap’s interpreter, as it runs fadtk, kadtk and Audiobox
Aesthetics:

```default
pam = Pam(python="~/venvs/pam/bin/python")  # or $FOLEY_PAM_PYTHON
tone, noise = pam([tone_wav, noise_wav], sr=48000)
tone.score      # 0.68 (a 3 s 440 Hz sine); noise.score 0.04 (white noise)
```

It is an eval-side scorer for any set of clips; it is not wired into `generate` (as
`generate(aesthetics=)` is) yet. It raises rather than storing anything, so no
failure text of its own reaches a record.

Licences: PAM’s and msclap’s code are MIT; the CLAP weights
(`microsoft/msclap`, `CLAP_weights_2023.pth`, 690 MB) are tagged MS-PL on Hugging
Face; the GPT-2 tokenizer files it fetches (3 MB) are MIT. The scores are metadata about
a clip, so they do not change its licence.

### Module Attributes

| [`PAM_PROMPTS`](#foley.eval.pam.PAM_PROMPTS)    | PAM's antonym prompts; the score is the probability of the first.                 |
|-----------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`PAM_PYTHON_ENV`](#foley.eval.pam.PAM_PYTHON_ENV) | The environment variable naming msclap's interpreter when `python=` is not given. |

### Classes

| [`Pam`](#foley.eval.pam.Pam)(\*[, checkpoint, prompts, batch_size, device])   | Per-clip PAM scores computed by `msclap` in a separate interpreter.             |
|-------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`PamScore`](#foley.eval.pam.PamScore)(score, segments, model, version[, ...])     | One clip's PAM score, its per-window scores, and the model and toolkit version. |

### foley.eval.pam.PAM_PROMPTS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('the sound is clear and clean.', 'the sound is noisy and with artifacts.')*

PAM’s antonym prompts; the score is the probability of the first.

### foley.eval.pam.PAM_PYTHON_ENV *= 'FOLEY_PAM_PYTHON'*

The environment variable naming msclap’s interpreter when `python=` is not given.

### *class* foley.eval.pam.Pam(, checkpoint=None, prompts=('the sound is clear and clean.', 'the sound is noisy and with artifacts.'), batch_size=10, device='cpu', \*\*kwargs)

Bases: [`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit)

Per-clip PAM scores computed by `msclap` in a separate interpreter.

:param those of [`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit) (`python`:
:param :
:param default `$FOLEY_PAM_PYTHON`; `env`:
:param e.g. `{"HF_HOME": ...}` to choose where:
:param the weights go; `timeout`; `runner`):
:param plus:
:type checkpoint: [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
:param checkpoint: A local `CLAP_weights_2023.pth` (default: downloaded once into the

> interpreter’s `HF_HOME`).
* **Parameters:**
  * **prompts** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The prompts, the clean one first (default [`PAM_PROMPTS`](#foley.eval.pam.PAM_PROMPTS); others
    give a PAM-style score, not PAM’s).
  * **batch_size** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Windows a forward pass.
  * **device** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Where the model runs (`'cpu'`, `'cuda'`, `'mps'`).

#### check_clip(clip, , sr, name)

Refuse an empty clip, or one with a NaN or infinite sample.

A short clip is scored: PAM tiles it to one 7 s window.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### isolation_reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'it pins numpy<2 and brings its own torch'*

Why the toolkit cannot live in foley’s environment (said when no interpreter).

### *class* foley.eval.pam.PamScore(score, segments, model, version, toolkit='msclap')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One clip’s PAM score, its per-window scores, and the model and toolkit version.

#### to_dict()

The score, the window scores and the stamp as one JSON-safe dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
