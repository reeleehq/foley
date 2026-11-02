# foley.eval.fadtk

Reference FAD from Microsoft’s `fadtk`, run in its own interpreter (#48).

[`foley.eval.fidelity.frechet_distance()`](foley.eval.fidelity.html.md#foley.eval.fidelity.frechet_distance) is the FAD math in pure numpy, fed by any
embedder. To report a number comparable with published ones, use the reference
toolkit, [fadtk](https://github.com/microsoft/fadtk): its embedding models, its
audio loading and resampling, its statistics. fadtk 1.1 pins `numpy<2` and pulls
torch, torchvision and two CLAP packages, so it cannot share foley’s environment.
[`FadtkFidelity`](#foley.eval.fadtk.FadtkFidelity) runs it the way [`foley.weave.cli_aligners`](foley.weave.cli_aligners.html.md#module-foley.weave.cli_aligners) runs MFA and
aeneas: the two wav sets are written to a temporary directory, the interpreter of a
virtualenv holding fadtk runs [`foley.eval.fadtk_driver`](foley.eval.fadtk_driver.html.md#module-foley.eval.fadtk_driver) on them, and its JSON
answer becomes a [`FidelityResult`](foley.eval.fidelity.html.md#foley.eval.fidelity.FidelityResult) stamped
`toolkit='fadtk'`. Nothing from fadtk is imported here.

```default
fad = FadtkFidelity(python="~/venvs/fadtk/bin/python")
result = fad(reference_wavs, generated_wavs, sr=48000)
result.value, result.stamp  # FAD, FidelityStamp(embedding='encodec-emb', toolkit='fadtk', ...)
```

fadtk’s FAD is over embedding **frames** (every frame of every clip), not one vector
per clip as [`generation_fidelity()`](foley.eval.fidelity.html.md#foley.eval.fidelity.generation_fidelity) takes, so the two numbers
differ unless fed the same frames. Install and model choice: `misc/docs/fidelity.md`.

### Module Attributes

| [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS)        | fadtk embedding models by fadtk's name → (loader class in `fadtk.model_loader`, its constructor args).          |
|----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| [`DEFAULT_FADTK_MODEL`](#foley.eval.fadtk.DEFAULT_FADTK_MODEL) | The default fadtk model (lightest download; see [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS)). |
| [`DRIVER`](#foley.eval.fadtk.DRIVER)              | The script run inside fadtk's interpreter.                                                                      |
| [`FADTK_PYTHON_ENV`](#foley.eval.fadtk.FADTK_PYTHON_ENV)    | The environment variable naming fadtk's interpreter when `python=` is not given.                                |
| [`FADTK_INSTALL`](#foley.eval.fadtk.FADTK_INSTALL)       | Install hint, printed when the interpreter is missing or lacks fadtk.                                           |
| [`MAX_CHANNELS`](#foley.eval.fadtk.MAX_CHANNELS)        | The most channels a clip may have.                                                                              |

### Classes

| [`FadtkFidelity`](#foley.eval.fadtk.FadtkFidelity)(\*[, python, model, models, ...])   | Set-level FAD computed by `fadtk` in a separate interpreter.   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------|

### foley.eval.fadtk.DEFAULT_FADTK_MODEL *= 'encodec-emb'*

The default fadtk model (lightest download; see [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS)).

### foley.eval.fadtk.DRIVER *= PosixPath('/home/runner/work/foley/foley/foley/eval/fadtk_driver.py')*

The script run inside fadtk’s interpreter.

### foley.eval.fadtk.FADTK_INSTALL *= "uv venv ~/venvs/fadtk --python 3.11 && uv pip install --python ~/venvs/fadtk/bin/python fadtk torchcodec; then FadtkFidelity(python='~/venvs/fadtk/bin/python') or set FOLEY_FADTK_PYTHON"*

Install hint, printed when the interpreter is missing or lacks fadtk.

### foley.eval.fadtk.FADTK_MODELS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)]]* *= {'clap-2023': ('CLAPModel', ('2023',)), 'clap-laion-audio': ('CLAPLaionModel', ('audio',)), 'clap-laion-music': ('CLAPLaionModel', ('music',)), 'encodec-emb': ('EncodecEmbModel', ('24k',)), 'encodec-emb-48k': ('EncodecEmbModel', ('48k',)), 'vggish': ('VGGishModel', ())}*

fadtk embedding models by fadtk’s name → (loader class in `fadtk.model_loader`,
its constructor args). Extend with `FadtkFidelity(models={...})`. The default,
`encodec-emb`, downloads the smallest weights (EnCodec 24 kHz, about 90 MB).

### foley.eval.fadtk.FADTK_PYTHON_ENV *= 'FOLEY_FADTK_PYTHON'*

The environment variable naming fadtk’s interpreter when `python=` is not given.

### *class* foley.eval.fadtk.FadtkFidelity(\*, python=None, model='encodec-emb', models=None, workers=1, env=None, timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Set-level FAD computed by `fadtk` in a separate interpreter.

* **Parameters:**
  * **python** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An interpreter with `fadtk` installed, usually in its own venv
    (default: `$FOLEY_FADTK_PYTHON`; neither set raises with the install).
  * **model** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A key of `models` (default [`DEFAULT_FADTK_MODEL`](#foley.eval.fadtk.DEFAULT_FADTK_MODEL)).
  * **models** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)]]]) – fadtk name → (loader class, args) (default [`FADTK_MODELS`](#foley.eval.fadtk.FADTK_MODELS)).
  * **workers** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – fadtk’s embedding worker processes (each loads the model).
  * **env** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – The program’s environment (default: this process’s), e.g. to set
    `TORCH_HOME` where the weights are cached.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

### foley.eval.fadtk.MAX_CHANNELS *= 8*

The most channels a clip may have. A 2-D array with at most this many rows and more
columns than that is channel-first, and is refused (`_as_frames_channels()`).
