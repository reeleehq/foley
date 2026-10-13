# foley.sources.elevenlabs.adapter

ElevenLabs Sound Effects generate adapter — hosted Text-to-SFX v2 over HTTP.

Turns a natural-language prompt into a [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)
via the ElevenLabs `POST /v1/sound-generation` endpoint (report 02 §ElevenLabs).
The response is raw audio bytes (default MP3 44.1 kHz), stored **by-value** (the
generation flywheel) once the `foley.sources.generate.generate()` façade routes
it through [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one).

Two ElevenLabs-specific quirks the adapter handles:

* **\`\`output_format\`\` is a URL query parameter**, not a JSON body field; everything
  else (`text` / `model_id` / `prompt_influence` / `loop` /
  `duration_seconds`) is the JSON body.
* **No seed / negative-prompt / step control** — generation is non-deterministic, so
  `generation_seed` stays `None` and those unified affordances warn-and-drop.

HTTP is dependency-injected (a [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)), so the
adapter is fully testable with no network and `import foley` stays dol-only; the
real `requests` lives only behind
[`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport) (the `foley[elevenlabs]` extra).
The adapter performs NO storage/library access — it builds the audio + a generated
[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) and returns; the façade converges it on the
shared ingest pipeline.

### Module Attributes

| [`Adapter`](#foley.sources.elevenlabs.adapter.Adapter)   | Registry convention (arioso): the loader imports `adapter.Adapter`.   |
|------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.elevenlabs.adapter.Adapter)                                          | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                                |
|---------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ElevenLabsAdapter`](#foley.sources.elevenlabs.adapter.ElevenLabsAdapter)([config, api_key, http, plan]) | ElevenLabs Sound Effects generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |

### foley.sources.elevenlabs.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.elevenlabs.adapter.ElevenLabsAdapter(config=None, , api_key=None, http=None, plan=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

ElevenLabs Sound Effects generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The `SOURCE_CONFIG` (defaults to the module’s). Passed positionally
    by the registry’s lazy loader (the arioso `Adapter(config)` convention).
  * **api_key** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The ElevenLabs token. Defaults to `$ELEVENLABS_API_KEY`.
  * **http** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)]) – The injected [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) (defaults to
    [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)); tests pass a fake.
  * **plan** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The ElevenLabs account plan (`'elevenlabs-paid-plan'` |
    `'elevenlabs-free-plan'`), which decides the generated sound’s licence.
    Defaults to `$FOLEY_ELEVENLABS_PLAN`; with neither, `generate` refuses
    before calling the API (#56).

#### *property* api_key *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The ElevenLabs token (constructor, else a bound key, else `$ELEVENLABS_API_KEY`).

#### generate(prompt, , duration=None, prompt_influence=None, negative_prompt=None, steps=None, seed=None, loop=False, output_format='wav', \*\*kw)

Generate a sound effect for `prompt`; return its bytes + provisional candidate.

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language sound description (required).
  * **duration** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds (clamped to the native `0.5..30` range). `None`
    lets the model auto-determine the length from the prompt.
  * **prompt_influence** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `0..1` (identity map to the native field; higher =
    closer to the prompt, less variety). `None` (default) omits it, so
    the API applies its own default.
  * **seed** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – No ElevenLabs SFX equivalent — a
    non-default value warns-and-drops (recorded in the clip notes);
    `generation_seed` stays `None`.
  * **loop** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Produce a seamless-loopable clip (native `loop`; v2 default).
  * **output_format** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Coarse foley token (`wav` | `opus` | `mp3`)
    translated to the native enum; `wav` is the lossless `pcm_48000`
    wrapped in a WAV header here, falling back to MP3 (with a note) if
    the account’s plan refuses PCM. Ingest re-archives to FLAC.
  * **\*\*kw** – Extra/unknown affordances (warn-and-dropped).
* **Return type:**
  [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)
* **Returns:**
  A [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip) (`origin=generated`,
  `license_id` = the account plan, `is_ai_generated=True`).
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If the plan is unknown (before any API call).

#### *property* plan *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The account plan = the generated sound’s `license_id` (fail-closed when unknown).

#### request_salt()

What besides the request decides the result: the plan (it decides the licence).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
