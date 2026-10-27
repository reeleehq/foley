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
dol-only. The local-model DI seam is `pipeline=` (the analog of the hosted
adapters’ `http=`): inject a fake pipeline and no ML stack loads at all — the
whole adapter is testable with no torch. The adapter performs NO storage/library
access; the façade converges it on the shared ingest pipeline.

### Module Attributes

| [`Adapter`](#foley.sources.stable_audio.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.stable_audio.adapter.Adapter)                                | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                                   |
|-----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`StableAudioAdapter`](#foley.sources.stable_audio.adapter.StableAudioAdapter)([config, pipeline]) | Local Stable Audio Open 1.0 generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### foley.sources.stable_audio.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.stable_audio.adapter.StableAudioAdapter(config=None, , pipeline=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Local Stable Audio Open 1.0 generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (defaults to the module’s). Passed positionally
    by the registry’s lazy loader (the arioso `Adapter(config)` convention).
  * **pipeline** – An optional pre-built pipeline (the dependency-injection seam —
    a test injects a fake callable exposing `.vae.sampling_rate` +
    `.device`; production omits it and the real
    `diffusers.StableAudioPipeline` lazy-loads on first generation).

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
  * **seed** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Reproducibility seed → a per-device `torch.Generator`; recorded
    in provenance. `None` → non-deterministic (no torch import).
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
caller of this method owns those. Builds a per-device `torch.Generator` only
when `seed` is set (so a `seed=None` generation never imports torch — the
fake-pipeline test path).
