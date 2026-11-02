# foley.eval.external_toolkit

A reference toolkit run in its own interpreter: the part every adapter shares (#48, #262).

Several evaluation toolkits cannot share foley’s environment: `fadtk` and `kadtk`
pin `numpy<2` and an old torch, `audiobox_aesthetics` pulls a recent torch foley
does not need. Each runs the way [`foley.external`](foley.external.html.md#module-foley.external) runs MFA and aeneas: clips are
written as mono 16-bit WAVs to a temporary directory, the toolkit’s interpreter runs
[`foley.eval.toolkit_driver`](foley.eval.toolkit_driver.html.md#module-foley.eval.toolkit_driver) on a JSON spec, and the JSON it writes back is the
answer. [`ExternalToolkit`](#foley.eval.external_toolkit.ExternalToolkit) is that mechanism (the interpreter and its install
hint, the failure hints, the run); what is computed over the files is the subclass’s:
a set-level distance ([`foley.eval.external_fidelity.ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity)) or a
per-clip score ([`foley.eval.aesthetics.AudioboxAesthetics`](foley.eval.aesthetics.html.md#foley.eval.aesthetics.AudioboxAesthetics)). Nothing from any
toolkit is imported here.

### Module Attributes

| [`DRIVER`](#foley.eval.external_toolkit.DRIVER)       | The script run inside a toolkit's interpreter.   |
|---------------------------------------------------------------|--------------------------------------------------|
| [`MAX_CHANNELS`](#foley.eval.external_toolkit.MAX_CHANNELS) | The most channels a clip may have.               |

### Functions

| [`as_frames_channels`](#foley.eval.external_toolkit.as_frames_channels)(wav)                          | `wav` as foley's `(frames,)` / `(frames, channels)`; refuse other layouts.        |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`write_set`](#foley.eval.external_toolkit.write_set)(wavs, sr, folder, \*, prefix[, check]) | Write each waveform in `wavs` as a mono 16-bit WAV in `folder`; return the count. |

### Classes

| [`ExternalToolkit`](#foley.eval.external_toolkit.ExternalToolkit)(\*[, python, env, timeout, ...])   | A toolkit run by [`DRIVER`](#foley.eval.external_toolkit.DRIVER) in a separate interpreter.   |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|

### foley.eval.external_toolkit.DRIVER *= PosixPath('/home/runner/work/foley/foley/foley/eval/toolkit_driver.py')*

The script run inside a toolkit’s interpreter.

### *class* foley.eval.external_toolkit.ExternalToolkit(\*, python=None, env=None, timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A toolkit run by [`DRIVER`](#foley.eval.external_toolkit.DRIVER) in a separate interpreter.

Subclasses set `toolkit`, `python_env`, `install`,
[`isolation_reason`](#foley.eval.external_toolkit.ExternalToolkit.isolation_reason) (and optionally [`failure_hints`](#foley.eval.external_toolkit.ExternalToolkit.failure_hints)), and call
[`run_driver()`](#foley.eval.external_toolkit.ExternalToolkit.run_driver).

* **Parameters:**
  * **python** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An interpreter with the toolkit installed, usually in its own venv
    (default: `$<python_env>`; neither set raises with the install line).
  * **env** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Variables added to this process’s environment for the program, e.g.
    `{"TORCH_HOME": ...}` or `{"HF_HOME": ...}` to choose where weights go.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

#### failure_hints *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {}*

A substring of a failed run’s output → what to do about it.

#### isolation_reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Why the toolkit cannot live in foley’s environment (said when no interpreter).

#### local_paths()

The interpreter as given and resolved, and its venv root: paths to keep out of
anything published ([`foley.obs.redact.redact_paths()`](foley.obs.redact.html.md#foley.obs.redact.redact_paths)). Never raises.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### resolve_python()

The toolkit’s interpreter as an executable path; raise with the install line if none.

Cheap (no program runs), so a caller can fail before anything is paid for.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### run_driver(spec, , out, cwd, what, python=None)

Run [`DRIVER`](#foley.eval.external_toolkit.DRIVER) on `spec` (plus `toolkit` and `out`); return its JSON.

`python` is the already-resolved interpreter (default: resolve it now); a
caller resolves it first to fail before writing any file.

* **Raises:**
  * [**FileNotFoundError**](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) – If no interpreter is given or found.
  * [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If the toolkit fails (its output tail, and any matching
        [`failure_hints`](#foley.eval.external_toolkit.ExternalToolkit.failure_hints), are in the message).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.external_toolkit.MAX_CHANNELS *= 8*

The most channels a clip may have. A 2-D array with at most this many rows and more
columns than that is channel-first, and is refused ([`as_frames_channels()`](#foley.eval.external_toolkit.as_frames_channels)).

### foley.eval.external_toolkit.as_frames_channels(wav)

`wav` as foley’s `(frames,)` / `(frames, channels)`; refuse other layouts.

A channel-first `(2, N)` array would otherwise be read as two-sample clips.

* **Return type:**
  `ndarray`

### foley.eval.external_toolkit.write_set(wavs, sr, folder, , prefix, check=None)

Write each waveform in `wavs` as a mono 16-bit WAV in `folder`; return the count.

Files are named `<prefix><n:05d>.wav` from 1, so sorting them keeps the input
order. `check(clip, sr=, name=)`, if given, sees each `(frames[, channels])`
clip first and raises to refuse it.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)
