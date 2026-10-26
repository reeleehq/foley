# foley.sources.stable_audio_3.adapter

Stable Audio 3 Small-SFX generate adapter: Stability’s TFLite CPU build, run as a process.

The model is not a pip package: Stability ships it as `optimized/tflite` in
`Stability-AI/stable-audio-3` (a script plus a requirements file, weights fetched on
first use from the ungated `stabilityai/stable-audio-3-optimized`). The adapter drives
that checkout’s `scripts/sa3_tflite.py` with the checkout’s own virtualenv Python, so
foley takes on no dependency and `import foley` stays dol-only. Setup is two commands
([`setup_hint()`](#foley.sources.stable_audio_3.adapter.setup_hint)); a missing checkout raises `SourceConfigurationError` with them,
which the generation order treats as “skip this backend”.

* **Seam:** `runner=` (`runner(cmd, *, cwd, env, timeout) -> (returncode, stderr)`)
  is the process boundary; a test injects a fake that writes the `--out` file.
* **Offline:** the process runs with `HF_HUB_OFFLINE=1` when the runtime forbids
  external egress, and a failure then raises [`ModelNotCached`](foley.runtime.html.md#foley.runtime.ModelNotCached)
  (foley never downloads weights inside [`foley.offline()`](foley.html.md#foley.offline), #86).
* **Seed:** always passed (a random one when none is given) and recorded, so every
  clip is reproducible from its provenance.
* **Distilled:** CFG 1; `prompt_influence` is noted and not applied (#70), and a
  negative prompt only acts when CFG is above 1, so it is dropped with a note.

### Module Attributes

| [`Runner`](#foley.sources.stable_audio_3.adapter.Runner)   | `runner(cmd, *, cwd, env, timeout) -> (returncode, stderr_text)`.   |
|-----------------------------------------------------------|---------------------------------------------------------------------|
| [`Adapter`](#foley.sources.stable_audio_3.adapter.Adapter)  | Registry convention (arioso): the loader imports `adapter.Adapter`. |

### Functions

| [`runtime_ready`](#foley.sources.stable_audio_3.adapter.runtime_ready)([config, home])   | Whether the checkout and its virtualenv are in place (weights download on first use).   |
|----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`sa3_home`](#foley.sources.stable_audio_3.adapter.sa3_home)([config])              | Where the Stability checkout lives: `$FOLEY_SA3_DIR`, else the config's default.        |
| [`setup_hint`](#foley.sources.stable_audio_3.adapter.setup_hint)([config])            | The commands that install the runtime and fetch the weights (never run by foley).       |

### Classes

| [`Adapter`](#foley.sources.stable_audio_3.adapter.Adapter)                                     | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                             |
|----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [`StableAudio3Adapter`](#foley.sources.stable_audio_3.adapter.StableAudio3Adapter)([config, runner, home]) | Local Stable Audio 3 Small-SFX adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### foley.sources.stable_audio_3.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### foley.sources.stable_audio_3.adapter.Runner

`runner(cmd, *, cwd, env, timeout) -> (returncode, stderr_text)`.

alias of `Callable`[[…], `tuple[int, str]`]

### *class* foley.sources.stable_audio_3.adapter.StableAudio3Adapter(config=None, , runner=None, home=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Local Stable Audio 3 Small-SFX adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (the registry passes it positionally).
  * **runner** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – The process boundary (see [`Runner`](#foley.sources.stable_audio_3.adapter.Runner)); defaults to a subprocess.
  * **home** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]) – The Stability checkout; defaults to [`sa3_home()`](#foley.sources.stable_audio_3.adapter.sa3_home).

#### generate(prompt, , duration=None, prompt_influence=None, negative_prompt=None, steps=None, seed=None, loop=False, output_format='wav', provider_params=None, \*\*kw)

Generate a sound for `prompt` on the CPU; return its bytes + provisional candidate.

`duration` is clamped to the model’s 1..120 s (default 10 s); the model renders
whole latent frames, so the clip may differ from it by a few milliseconds.
`seed=None` draws a random seed, recorded in the clip’s provenance.
`provider_params` (#61) are native script flags merged over the translated
ones (`seconds`, `steps`, `cfg`, `seed`; any other key is passed as
`--<key> <value>`) and recorded in `generation_params`; the config’s
`provider_params` policy refuses the prompt, output path and model flags.

* **Return type:**
  [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)

#### invoke_native(prompt, native)

Run the script with native flags into a temp file; return the WAV bytes it wrote.

The public entry below foley’s translation (#61): each `native` key (the
script’s `seconds` / `steps` / `cfg` / `seed`, or any other flag) becomes
a `--<key> <value>` flag, followed by foley’s own `--dit` / `--decoder` /
`--prompt` / `--out`. No licence record is built and no dispatch-layer check
runs (cost, egress): a caller owns those.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.sources.stable_audio_3.adapter.runtime_ready(config=None, , home=None)

Whether the checkout and its virtualenv are in place (weights download on first use).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.stable_audio_3.adapter.sa3_home(config=None)

Where the Stability checkout lives: `$FOLEY_SA3_DIR`, else the config’s default.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### foley.sources.stable_audio_3.adapter.setup_hint(config=None)

The commands that install the runtime and fetch the weights (never run by foley).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
