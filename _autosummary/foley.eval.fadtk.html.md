# foley.eval.fadtk

Reference FAD from Microsoft’s `fadtk`, run in its own interpreter (#48).

[`foley.eval.fidelity.frechet_distance()`](foley.eval.fidelity.html.md#foley.eval.fidelity.frechet_distance) is the FAD math in pure numpy, fed by any
embedder. To report a number comparable with published ones, use the reference
toolkit, [fadtk](https://github.com/microsoft/fadtk): its embedding models, its
audio loading and resampling, its statistics. fadtk 1.1 pins `numpy<2` and pulls
torch, torchvision and two CLAP packages, so it cannot share foley’s environment.
[`FadtkFidelity`](#foley.eval.fadtk.FadtkFidelity) runs it through [`ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity)
(temporary wav sets, [`foley.eval.toolkit_driver`](foley.eval.toolkit_driver.html.md#module-foley.eval.toolkit_driver) in fadtk’s interpreter, a
[`FidelityResult`](foley.eval.fidelity.html.md#foley.eval.fidelity.FidelityResult) stamped `toolkit='fadtk'`). Nothing
from fadtk is imported here.

```default
fad = FadtkFidelity(python="~/venvs/fadtk/bin/python")
result = fad(reference_wavs, generated_wavs, sr=48000)
result.value, result.stamp  # FAD, FidelityStamp(embedding='encodec-emb', toolkit='fadtk', ...)
```

fadtk’s FAD is over embedding **frames** (every frame of every clip), not one vector
per clip as [`generation_fidelity()`](foley.eval.fidelity.html.md#foley.eval.fidelity.generation_fidelity) takes, so the two numbers
differ unless fed the same frames. Install and model choice: `misc/docs/fidelity.md`.

### Module Attributes

| [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS)   | fadtk embedding models by fadtk's name → (loader class in `fadtk.model_loader`, its constructor args).   |
|-----------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|

### Classes

| [`FadtkFidelity`](#foley.eval.fadtk.FadtkFidelity)(\*[, model, models, workers])   | Set-level FAD computed by `fadtk` in a separate interpreter.   |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------|

### foley.eval.fadtk.FADTK_MODELS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)]]* *= {'clap-2023': ('CLAPModel', ('2023',)), 'clap-laion-audio': ('CLAPLaionModel', ('audio',)), 'clap-laion-music': ('CLAPLaionModel', ('music',)), 'encodec-emb': ('EncodecEmbModel', ('24k',)), 'encodec-emb-48k': ('EncodecEmbModel', ('48k',)), 'vggish': ('VGGishModel', ())}*

fadtk embedding models by fadtk’s name → (loader class in `fadtk.model_loader`,
its constructor args). Extend with `FadtkFidelity(models={...})`. The default,
`encodec-emb`, downloads the smallest weights (EnCodec 24 kHz, about 90 MB).

### *class* foley.eval.fadtk.FadtkFidelity(, model=None, models=None, workers=1, \*\*kwargs)

Bases: [`ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity)

Set-level FAD computed by `fadtk` in a separate interpreter.

:param those of [`ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity); `model`:
:param is a key of [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS):
:type is a key of [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS): default `DEFAULT_FADTK_MODEL`

#### frames_needed(dim)

More frames than dimensions, or the covariance is singular and FAD meaningless.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
