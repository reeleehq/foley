# foley.sources.pyfxr.adapter

pyfxr procedural adapter: a category preset, seeded, rendered to audio bytes (#76).

pyfxr’s presets (`pyfxr.laser()`, `pyfxr.pickup()`, …) draw their parameters from
the module-level `random` of `pyfxr`. The adapter swaps a `random.Random(seed)`
in for the one draw, under a lock, and puts the module back: the global `random` is
never reseeded. The drawn parameters, with the caller’s `provider_params` over them,
build a `pyfxr.SFX`; its full resolved parameter set (every field, defaults included)
is recorded in `generation_params`, so the clip can be rebuilt from parameters alone.

pyfxr renders mono 16-bit PCM at `pyfxr.SAMPLE_RATE` (44.1 kHz) at full scale; the
adapter scales it to float with the config’s `render` gain, pads a blip shorter than
Tier-0 QC admits ([`pad_to_qc_minimum()`](foley.sources.base.html.md#foley.sources.base.pad_to_qc_minimum)), and encodes it with
[`foley.audio.encode()`](foley.audio.html.md#foley.audio.encode). A noise-waveform clip records `bit_exact: False`. The licence is
`procedural-free` with `is_ai_generated=False` (no disclosure, no watermark). The
adapter does no storage: [`foley.generate()`](foley.html.md#foley.generate) ingests the clip.

### Module Attributes

| [`Adapter`](#foley.sources.pyfxr.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.pyfxr.adapter.Adapter)                | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                   |
|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| [`PyfxrAdapter`](#foley.sources.pyfxr.adapter.PyfxrAdapter)([config]) | The pyfxr procedural adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### foley.sources.pyfxr.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.pyfxr.adapter.PyfxrAdapter(config=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The pyfxr procedural adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)).

* **Parameters:**
  **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (defaults to the module’s), passed positionally
  by the registry’s lazy loader.

#### generate(prompt, , preset=None, seed=None, provider_params=None, loop=False, output_format='wav', \*\*kw)

Synthesize the category preset `prompt` names (or `preset`).

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The sound description; picks the preset when `preset` is not
    given (`config['preset_keywords']`), and is the clip’s caption.
  * **preset** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A canonical preset (`config['presets']`), overriding the prompt.
  * **seed** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Seeds the preset’s parameter draw. `None` draws one
    ([`draw_seed()`](foley.sources.base.html.md#foley.sources.base.draw_seed)) and records it.
  * **provider_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Native `pyfxr.SFX` params (`base_freq`,
    `env_decay`, `wave_type`, …) set over the preset’s draw.
  * **loop** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – No native param: noted and ignored.
  * **output_format** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – No native param (the audio layer’s): noted and ignored.
  * **\*\*kw** – Other affordances (`duration_s`, `steps`, …): noted and ignored.
* **Return type:**
  [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)
* **Returns:**
  A [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip) under `procedural-free`,
  `is_ai_generated=False`.
* **Raises:**
  **UnsupportedParameter** – When no preset is given and none matches the prompt.
