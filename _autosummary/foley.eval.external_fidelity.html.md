# foley.eval.external_fidelity

Set-level fidelity from a reference toolkit run in its own interpreter (#48, #262).

[`foley.eval.fidelity`](foley.eval.fidelity.html.md#module-foley.eval.fidelity) has the FAD and KAD math in pure numpy. For numbers
comparable with published ones, the reference toolkits (`fadtk` for FAD, `kadtk`
for KAD) must do the embedding, the audio loading and the statistics, and both pin
`numpy<2` and an old torch, so neither can share foley’s environment.
[`ExternalFidelity`](#foley.eval.external_fidelity.ExternalFidelity) is the part they share, the way [`foley.external`](foley.external.html.md#module-foley.external) is for
MFA and aeneas: the two wav sets are written as mono 16-bit WAVs to a temporary
directory, the toolkit’s interpreter runs [`foley.eval.toolkit_driver`](foley.eval.toolkit_driver.html.md#module-foley.eval.toolkit_driver) on them, and
its JSON answer becomes a [`FidelityResult`](foley.eval.fidelity.html.md#foley.eval.fidelity.FidelityResult) stamped with
the toolkit and its version. Nothing from either toolkit is imported here.

A toolkit is a subclass that sets the class attributes (its name, metric, model table,
interpreter variable, install line) and says how many embedding frames each set needs
([`ExternalFidelity.frames_needed()`](#foley.eval.external_fidelity.ExternalFidelity.frames_needed)); see [`foley.eval.fadtk`](foley.eval.fadtk.html.md#module-foley.eval.fadtk) and
[`foley.eval.kadtk`](foley.eval.kadtk.html.md#module-foley.eval.kadtk).

### Module Attributes

| [`DRIVER`](#foley.eval.external_fidelity.DRIVER)       | The script run inside a toolkit's interpreter.   |
|---------------------------------------------------------------|--------------------------------------------------|
| [`MAX_CHANNELS`](#foley.eval.external_fidelity.MAX_CHANNELS) | The most channels a clip may have.               |

### Functions

| [`as_frames_channels`](#foley.eval.external_fidelity.as_frames_channels)(wav)                          | `wav` as foley's `(frames,)` / `(frames, channels)`; refuse other layouts.        |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`write_set`](#foley.eval.external_fidelity.write_set)(wavs, sr, folder, \*, prefix[, check]) | Write each waveform in `wavs` as a mono 16-bit WAV in `folder`; return the count. |

### Classes

| [`ExternalFidelity`](#foley.eval.external_fidelity.ExternalFidelity)(\*[, python, model, models, ...])   | A set-level fidelity score computed by a toolkit in a separate interpreter.   |
|-------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### foley.eval.external_fidelity.DRIVER *= PosixPath('/home/runner/work/foley/foley/foley/eval/toolkit_driver.py')*

The script run inside a toolkit’s interpreter.

### *class* foley.eval.external_fidelity.ExternalFidelity(\*, python=None, model=None, models=None, workers=1, env=None, timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A set-level fidelity score computed by a toolkit in a separate interpreter.

Subclasses set `toolkit`, `metric`, `default_models`,
`default_model`, `python_env`, `install` (and optionally
[`failure_hints`](#foley.eval.external_fidelity.ExternalFidelity.failure_hints)), and implement [`frames_needed()`](#foley.eval.external_fidelity.ExternalFidelity.frames_needed); [`options()`](#foley.eval.external_fidelity.ExternalFidelity.options) adds
toolkit-specific entries to the driver’s spec, and [`check_clip()`](#foley.eval.external_fidelity.ExternalFidelity.check_clip) refuses a clip
the toolkit cannot embed before anything runs.

* **Parameters:**
  * **python** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An interpreter with the toolkit installed, usually in its own venv
    (default: `$<python_env>`; neither set raises with the install line).
  * **model** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A key of `models` (default `default_model`).
  * **models** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)]]]) – Model name → (loader class in `<toolkit>.model_loader`, its args)
    (default `default_models`).
  * **workers** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The toolkit’s embedding worker processes (each loads the model).
  * **env** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Variables added to this process’s environment for the program, e.g.
    `{"TORCH_HOME": ...}` to choose where the weights are cached.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

#### check_clip(clip, , sr, name)

Raise [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError) if the toolkit cannot embed `clip` (default: accept).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### failure_hints *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {}*

A substring of a failed run’s output → what to do about it.

#### frames_needed(dim)

The fewest embedding frames a set may have for a `dim`-dim embedding, and why.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### options()

Toolkit-specific entries for the driver’s spec (default: none).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### warn_frames *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[int](https://docs.python.org/3/builtins/functions.html#int)]* *= None*

Below this many embedding frames in a set, warn that the score is mostly noise
(`None`: never). The hard floor is [`frames_needed()`](#foley.eval.external_fidelity.ExternalFidelity.frames_needed).

### foley.eval.external_fidelity.MAX_CHANNELS *= 8*

The most channels a clip may have. A 2-D array with at most this many rows and more
columns than that is channel-first, and is refused ([`as_frames_channels()`](#foley.eval.external_fidelity.as_frames_channels)).

### foley.eval.external_fidelity.as_frames_channels(wav)

`wav` as foley’s `(frames,)` / `(frames, channels)`; refuse other layouts.

A channel-first `(2, N)` array would otherwise be read as two-sample clips.

* **Return type:**
  `ndarray`

### foley.eval.external_fidelity.write_set(wavs, sr, folder, , prefix, check=None)

Write each waveform in `wavs` as a mono 16-bit WAV in `folder`; return the count.

`check(clip, sr=, name=)`, if given, sees each `(frames[, channels])` clip first
and raises to refuse it.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)
