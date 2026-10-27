# foley.sources.stable_audio.adapter

Stable Audio Open 1.0 generate adapter — local `diffusers` inference.

Turns a natural-language prompt into a [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)
via `diffusers.StableAudioPipeline` running on-device (report 02 §Stable Audio
Open). The model produces a 44.1 kHz stereo waveform (up to ~47 s); the adapter
encodes it to container bytes, which the `foley.sources.generate.generate()`
façade stores **by-value** (the generation flywheel) through the shared
[`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) pipeline.

Load-bearing details verified against the diffusers docs + HF model card:

* \*\*The CFG kwarg is `guidance_scale``** (NOT ``cfg_scale`), and it MUST be passed
  explicitly or the pipeline silently uses its own default 7.0. foley maps its
  unified `prompt_influence` (0..1) onto it linearly (1..15, declared in the
  config’s `coerce`); `None` sends the model’s own default, and a distilled
  checkpoint (`native_defaults["distilled"]`) always gets its native default.
* \*\*Output is channel-first `(channels, samples)``** — transposed to the
  time-first ``(frames, channels)` foley/soundfile convention before encoding.
* **The sample rate is read off the pipeline** (`pipe.vae.sampling_rate` = 44100),
  never hardcoded.
* **\`\`loop\`\` and \`\`output_format\`\` have no native pipeline param** (loop is a future
  WEAVE crossfade; format is the audio-write layer) — they warn-and-drop; the
  adapter never fabricates a pipeline kwarg.

`torch` / `diffusers` are imported lazily inside the methods (the
`foley[stable-audio]` extra), so `import foley` and source discovery stay
dol-only. The local-model DI seams are `pipeline=` (the analog of the hosted
adapters’ `http=`) and `make_generator=` (the seeded `torch.Generator`): inject
fakes for both and no ML stack loads at all — the whole adapter is testable with no
torch. The adapter performs NO storage/library access; the façade converges it on
the shared ingest pipeline.

**Reproducibility across devices (#207).** The default generator is a CPU
`torch.Generator` ([`cpu_generator()`](#foley.sources.stable_audio.adapter.cpu_generator)), as diffusers recommends: the pipeline’s
`randn_tensor` draws the initial latents on the generator’s device and moves them to
the pipeline’s, so a seed starts from the same noise on CUDA and on CPU. Only that starting noise is
device-independent: the denoising runs in the pipeline’s device and dtype (float16 on
CUDA, float32 on CPU), and the scheduler’s per-step noise is drawn there too, so the
bytes are identical only on the same device and dtype: both are recorded in
`generation_params` (`device`, `dtype`, and the `generator_device`). That the
pipeline accepts a CPU generator for a CUDA pipeline is diffusers’ `randn_tensor`
behaviour (it draws on the generator’s device, then moves the tensor), not checked
here (diffusers is not a test dependency); [`torch_generator()`](#foley.sources.stable_audio.adapter.torch_generator) (on the
pipeline’s device) is one `make_generator=` away. A clip stored before #207 records
no `generator_device`: its generator was on the pipeline’s device, so a CUDA one
reproduces with `make_generator=torch_generator`.

### Module Attributes

| [`GeneratorFactory`](#foley.sources.stable_audio.adapter.GeneratorFactory)   | the seeded RNG the pipeline draws from.                             |
|---------------------------------------------------------------------|---------------------------------------------------------------------|
| [`Adapter`](#foley.sources.stable_audio.adapter.Adapter)            | Registry convention (arioso): the loader imports `adapter.Adapter`. |

### Functions

| [`cpu_generator`](#foley.sources.stable_audio.adapter.cpu_generator)(device, seed)   | A CPU `torch.Generator` seeded with `seed`, whatever the pipeline's `device`.   |
|--------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`torch_generator`](#foley.sources.stable_audio.adapter.torch_generator)(device, seed) | A `torch.Generator` on `device` (the pipeline's) seeded with `seed`.            |

### Classes

| [`Adapter`](#foley.sources.stable_audio.adapter.Adapter)                                     | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                                   |
|----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`StableAudioAdapter`](#foley.sources.stable_audio.adapter.StableAudioAdapter)([config, pipeline, ...]) | Local Stable Audio Open 1.0 generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### foley.sources.stable_audio.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### foley.sources.stable_audio.adapter.GeneratorFactory

the seeded RNG the pipeline draws from.

* **Type:**
  `make_generator(device, seed) -> generator`

alias of `Callable`[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any), [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *class* foley.sources.stable_audio.adapter.StableAudioAdapter(config=None, , pipeline=None, make_generator=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Local Stable Audio Open 1.0 generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (defaults to the module’s). Passed positionally
    by the registry’s lazy loader (the arioso `Adapter(config)` convention).
  * **pipeline** – An optional pre-built pipeline (the dependency-injection seam —
    a test injects a fake callable exposing `.vae.sampling_rate` +
    `.device`; production omits it and the real
    `diffusers.StableAudioPipeline` lazy-loads on first generation).
  * **make_generator** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any), [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – `make_generator(device, seed)`, the seeded generator handed
    to the pipeline (default [`cpu_generator()`](#foley.sources.stable_audio.adapter.cpu_generator), for the same initial noise
    on any device; [`torch_generator()`](#foley.sources.stable_audio.adapter.torch_generator) puts it on the pipeline’s device);
    a test with a fake pipeline passes a fake one, so no torch is needed.

#### generate(prompt, , duration_s=None, prompt_influence=None, negative_prompt=None, steps=None, seed=None, loop=False, output_format='wav', provider_params=None, \*\*kw)

Generate a sound for `prompt`; return its bytes + provisional candidate.

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language sound description (required).
  * **duration_s** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds (clamped to the model’s ~47.55 s max). `None` uses a
    sane 10 s default (NOT the 47.55 s maximum).
  * **prompt_influence** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `0..1` unified adherence, mapped linearly onto the
    native `guidance_scale` (1..15). `None` (default) sends the
    model’s own default (7.0 for Stable Audio Open 1.0); a distilled
    checkpoint ignores it with a note.
  * **negative_prompt** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Content to exclude (ignored by the model when guidance
    ≤ 1).
  * **steps** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Diffusion steps (native `num_inference_steps`); default 200.
  * **seed** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Reproducibility seed → the generator `make_generator` builds (by
    default a CPU `torch.Generator`, #207); recorded in provenance, with
    the device and dtype it ran on.
    `None` draws one ([`draw_seed()`](foley.sources.base.html.md#foley.sources.base.draw_seed)) and records
    it, so the clip is reproducible all the same (#163). Through
    [`foley.generate()`](foley.html.md#foley.generate) the dispatch layer has already drawn it
    (`foley.sources._dispatch.draws_seed()`, #206); this draw serves a
    direct call.
  * **loop** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – No native param (a future WEAVE crossfade) — warn-and-drop.
  * **output_format** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – No native param (the audio-write layer) — warn-and-drop;
    the clip is archived as FLAC by ingest regardless.
  * **provider_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Native `StableAudioPipeline` kwargs merged over the
    translated ones (#61; e.g. `{"num_inference_steps": 50}`), recorded
    in `generation_params`.
  * **\*\*kw** – Extra/unknown affordances (warn-and-dropped).
* **Return type:**
  [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)
* **Returns:**
  A [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip) (`origin=generated`,
  `license_id='Stability-Community'`, `is_ai_generated=True`,
  `generation_seed` captured).

#### invoke_native(prompt, , native, seed=None)

Run the pipeline with native kwargs; return `(encoded_bytes, sample_rate)`.

The public entry below foley’s translation (#61): `native` goes to the
`StableAudioPipeline` call as is (`guidance_scale`, `audio_end_in_s`, …).
No licence record is built and no dispatch-layer check runs (cost, egress): a
caller of this method owns those. It also owns the seed: unlike
[`generate()`](#foley.sources.stable_audio.adapter.StableAudioAdapter.generate), which draws one when none is given, `seed=None` here sends
no generator, so the pipeline falls back on its own randomness.

### foley.sources.stable_audio.adapter.cpu_generator(device, seed)

A CPU `torch.Generator` seeded with `seed`, whatever the pipeline’s `device`.

The default factory (#207): the initial noise is then the same on every device.

### foley.sources.stable_audio.adapter.torch_generator(device, seed)

A `torch.Generator` on `device` (the pipeline’s) seeded with `seed`.
