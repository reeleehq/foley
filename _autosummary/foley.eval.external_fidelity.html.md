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
the toolkit and its version. Nothing from either toolkit is imported here. The
interpreter, the run and the failure hints are [`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit)’s,
shared with the per-clip [`AudioboxAesthetics`](foley.eval.aesthetics.html.md#foley.eval.aesthetics.AudioboxAesthetics).

A toolkit is a subclass that sets the class attributes (its name, metric, model table,
interpreter variable, install line) and says how many embedding frames each set needs
([`ExternalFidelity.frames_needed()`](#foley.eval.external_fidelity.ExternalFidelity.frames_needed)); see [`foley.eval.fadtk`](foley.eval.fadtk.html.md#module-foley.eval.fadtk) and
[`foley.eval.kadtk`](foley.eval.kadtk.html.md#module-foley.eval.kadtk).

### Classes

| [`ExternalFidelity`](#foley.eval.external_fidelity.ExternalFidelity)(\*[, model, models, workers])   | A set-level fidelity score computed by a toolkit in a separate interpreter.   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### *class* foley.eval.external_fidelity.ExternalFidelity(, model=None, models=None, workers=1, \*\*kwargs)

Bases: [`ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit)

A set-level fidelity score computed by a toolkit in a separate interpreter.

Subclasses set `toolkit`, `metric`, `default_models`,
`default_model`, `python_env`, `install` (and optionally
`failure_hints`), and implement [`frames_needed()`](#foley.eval.external_fidelity.ExternalFidelity.frames_needed); [`options()`](#foley.eval.external_fidelity.ExternalFidelity.options) adds
toolkit-specific entries to the driver’s spec, and [`check_clip()`](#foley.eval.external_fidelity.ExternalFidelity.check_clip) refuses a clip
the toolkit cannot embed before anything runs.

* **Parameters:**
  * **python** – An interpreter with the toolkit installed, usually in its own venv
    (default: `$<python_env>`; neither set raises with the install line).
  * **model** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A key of `models` (default `default_model`).
  * **models** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)]]]) – Model name → (loader class in `<toolkit>.model_loader`, its args)
    (default `default_models`).
  * **workers** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The toolkit’s embedding worker processes (each loads the model).
  * **env** – Variables added to this process’s environment for the program, e.g.
    `{"TORCH_HOME": ...}` to choose where the weights are cached.
  * **timeout** – Seconds before the run is abandoned (default: none).
  * **runner** – Runs the command (default `subprocess.run`).

#### check_clip(clip, , sr, name)

Raise [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError) if the toolkit cannot embed `clip` (default: accept).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### frames_needed(dim)

The fewest embedding frames a set may have for a `dim`-dim embedding, and why.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### isolation_reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= "it pins numpy<2, so it cannot live in foley's environment"*

Why the toolkit cannot live in foley’s environment (said when no interpreter).

#### options()

Toolkit-specific entries for the driver’s spec (default: none).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### warn_frames *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[int](https://docs.python.org/3/builtins/functions.html#int)]* *= None*

Below this many embedding frames in a set, warn that the score is mostly noise
(`None`: never). The hard floor is [`frames_needed()`](#foley.eval.external_fidelity.ExternalFidelity.frames_needed).
