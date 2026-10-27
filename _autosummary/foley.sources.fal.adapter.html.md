# foley.sources.fal.adapter

The fal generate adapter — one class for every fal-hosted SFX endpoint, run through `falaw`.

Each fal source (`fal_stable_audio_3`, `fal_elevenlabs`, `fal_sonilo`,
`fal_mmaudio`, the video-to-audio and the edit endpoints; see
[`foley.sources.fal.config`](foley.sources.fal.config.html.md#module-foley.sources.fal.config)) gets its own instance of [`FalAdapter`](#foley.sources.fal.adapter.FalAdapter), built
from its own config. A media input (a `video` to sound, an edit’s source `audio`)
is sent as a URL (a local path or bytes uploaded) and recorded by its content key. The
adapter:

1. builds the native request from the already-translated affordances with the same
   `foley.sources._dispatch.native_request()` that keys the generations cache, so
   > the request sent and the request cached cannot drift, then adds the prompt, the
   > endpoint’s default duration when none was asked for, and its `fixed_arguments`;
2. calls the endpoint through the injected `runner` (default [`falaw_runner()`](#foley.sources.fal.adapter.falaw_runner):
   `falaw.cached_call_fal` + `falaw.materialize_asset`, under the key foley
   resolved). The runner always asks falaw to skip its cache *read*: replaying a paid
   request is foley’s generations cache’s job (`reuse_cached=`), and a second replay
   layer underneath would turn `reuse_cached=False` into a silent replay;
3. returns a [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip) whose licence comes from the
   config’s licence row (fail-closed), with the native request, the seed the endpoint
   reports having used, and the fal endpoint id recorded as provenance.

No storage access here (the façade ingests). The `runner` seam is how tests stay
offline: they pass a fake that returns canned bytes, and a call the fake does not know
is an error, never a fall-through to the network.

### Module Attributes

| [`FAL_CREDENTIAL`](#foley.sources.fal.adapter.FAL_CREDENTIAL)   | The credential name falaw binds a fal key under (`falaw.using_fal_credentials`).                                                                                                                         |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`FAL_KEY_ENV_VARS`](#foley.sources.fal.adapter.FAL_KEY_ENV_VARS) | The env vars falaw reads a fal key from, in order.                                                                                                                                                       |
| [`Runner`](#foley.sources.fal.adapter.Runner)           | `runner(endpoint_id, arguments, *, api_key, audio_field) -> (audio_bytes, response)`, or a [`FalAnswer`](#foley.sources.fal.adapter.FalAnswer) (that two-tuple, with fal's run `.metrics`, #186). |
| [`Adapter`](#foley.sources.fal.adapter.Adapter)          | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                                                                                      |

### Functions

| [`audio_url`](#foley.sources.fal.adapter.audio_url)(response[, field])                      | The URL of the audio in a fal response: `{field: {url}}` or `{field: [{url}, ...]}`.                                              |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| [`falaw_runner`](#foley.sources.fal.adapter.falaw_runner)(endpoint_id, arguments, \*, api_key) | Call a fal endpoint through falaw and return `(audio bytes, raw response)`.                                                       |
| [`falaw_uploader`](#foley.sources.fal.adapter.falaw_uploader)(path, \*, api_key)                 | A fal-fetchable URL for the local file at `path` (`falaw.upload`: content-addressed, so an unchanged file is not uploaded twice). |

### Classes

| [`Adapter`](#foley.sources.fal.adapter.Adapter)                                        | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                    |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| [`FalAdapter`](#foley.sources.fal.adapter.FalAdapter)(config, \*[, api_key, runner, ...]) | A fal-hosted generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)). |
| [`FalAnswer`](#foley.sources.fal.adapter.FalAnswer)(media, response[, metrics])          | A runner's `(media, response)`, with fal's run `metrics` beside it.                                                                    |

### foley.sources.fal.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### foley.sources.fal.adapter.FAL_CREDENTIAL *= 'fal'*

The credential name falaw binds a fal key under (`falaw.using_fal_credentials`).

### foley.sources.fal.adapter.FAL_KEY_ENV_VARS *= ('FAL_KEY', 'FAL_API_KEY')*

The env vars falaw reads a fal key from, in order.

### *class* foley.sources.fal.adapter.FalAdapter(config, , api_key=None, runner=None, uploader=None, demux=None, http=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A fal-hosted generate adapter (a [`GenerateAdapter`](foley.sources.base.html.md#foley.sources.base.GenerateAdapter)).

* **Parameters:**
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – This source’s config (one of `SOURCE_CONFIGS`),
    passed positionally by the registry’s lazy loader.
  * **api_key** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The fal key. Defaults to a key bound for this source
    (`foley.using_source_accounts(<source>=key)`), else one bound for fal
    itself (`falaw.using_fal_credentials(key)`, or `fal=` in
    `ocracy.kit.using_credentials`: one binding covers every fal source),
    else `$FAL_KEY`, else `$FAL_API_KEY`.
  * **runner** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)] | [`FalAnswer`](#foley.sources.fal.adapter.FalAnswer)]]) – The transport seam (default [`falaw_runner()`](#foley.sources.fal.adapter.falaw_runner)); tests pass a fake.
  * **uploader** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `(path, *, api_key) -> url`, how a local `video=` or `audio=`
    (a path or bytes) reaches fal (default [`falaw_uploader()`](#foley.sources.fal.adapter.falaw_uploader)); tests pass
    a fake.
  * **demux** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)], [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]) – `(container bytes) -> audio bytes`, for an endpoint that answers
    with a video (`output.container == 'video'`; default
    [`foley.sources.video.audio_track()`](foley.sources.video.html.md#foley.sources.video.audio_track), which needs ffmpeg).
  * **http** – Accepted and ignored: the registry passes a resilient HTTP transport to
    external sources, but this adapter’s transport is falaw (which retries and
    classifies errors itself).

#### account_id()

The account a call is made on, for the generations cache (`'operator'` or a fingerprint).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* api_key *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The fal key (see the class docstring for the order); raises if none.

#### demuxer()

How to take the audio out of this endpoint’s answer, or `None` (audio already).

* **Raises:**
  [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – If the endpoint answers with a video and no
      ffmpeg can open it (before any call, so nothing is paid for).
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)], [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]

#### generate(prompt, , provider_params=None, \*\*affordances)

Generate a sound for `prompt` on this source’s fal endpoint.

`affordances` are the canonical ones the dispatch layer kept (translated,
clamped, noted); see `foley.sources._dispatch.plan_generation()`.
`provider_params` (#61) are native endpoint arguments merged over the
translated ones and recorded in `generation_params`. The clip’s `raw` is
the endpoint’s response (its audio is a URL, not the bytes).

* **Raises:**
  [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – If no fal key is available (before any call).
* **Return type:**
  [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)

#### invoke_native(arguments)

Call this source’s fal endpoint with native `arguments`; return `(media, response)`.

`media` is the bytes at the response’s `output.audio_field`: the audio, or
for an endpoint that answers with a video (`output.container`), the video.

The public entry below foley’s translation (#61): `arguments` are sent as
is (no fixed arguments or default duration are added). No licence record is
built and no dispatch-layer gate (cost authorization, egress, the generations
cache) runs here: a caller of this method owns them, and pays for the call.

* **Raises:**
  [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – If no fal key is available (before any call).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### native_arguments(prompt, \*\*affordances)

The exact payload this adapter sends for `prompt` and translated `affordances`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### request_salt()

What the payload carries beyond the native request: part of the cache key.

The default duration and the fixed arguments are sent but are not
affordances, so a change to either must not replay a clip made without it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.sources.fal.adapter.FalAnswer(media, response, metrics=None)

Bases: [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)

A runner’s `(media, response)`, with fal’s run `metrics` beside it.

Still the two-tuple every runner answers (`media, response = answer`), so a
caller that does not know about metrics is unchanged; `.metrics` is fal’s
`Completed.metrics` (`inference_time`), or `None`.

### foley.sources.fal.adapter.Runner

`runner(endpoint_id, arguments, *, api_key, audio_field) -> (audio_bytes, response)`,
or a [`FalAnswer`](#foley.sources.fal.adapter.FalAnswer) (that two-tuple, with fal’s run `.metrics`, #186).

alias of `Callable`[[…], `tuple[bytes, dict] | FalAnswer`]

### foley.sources.fal.adapter.audio_url(response, field='audio')

The URL of the audio in a fal response: `{field: {url}}` or `{field: [{url}, ...]}`.

```pycon
>>> audio_url({"audio": {"url": "https://x/a.wav"}})
'https://x/a.wav'
>>> audio_url({"audio": [{"url": "https://x/b.wav"}]})
'https://x/b.wav'
>>> audio_url({"audio_file": {"url": "https://x/c.wav"}}, "audio_file")
'https://x/c.wav'
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.fal.adapter.falaw_runner(endpoint_id, arguments, , api_key, audio_field='audio')

Call a fal endpoint through falaw and return `(audio bytes, raw response)`.

A [`FalAnswer`](#foley.sources.fal.adapter.FalAnswer): its `.metrics` are fal’s `Completed.metrics`
(`inference_time`: the seconds the runner spent), which falaw carries on its
`done` event (falaw#125); `None` when fal reported none (or an older falaw
dropped them).

`refresh=True` skips falaw’s cache read and keeps its write (see the module
docstring: foley’s generations cache owns replay). The audio is downloaded by
`falaw.materialize_asset`, which content-addresses it in falaw’s store.

* **Raises:**
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – For a refusal before anything was billed (the fal
        client is not installed, the key is refused, the account has no funds, an
        argument cannot be sent), so the run’s budget reservation is released.
  * [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If the response carries no audio URL.
* **Return type:**
  [`FalAnswer`](#foley.sources.fal.adapter.FalAnswer)

### foley.sources.fal.adapter.falaw_uploader(path, , api_key)

A fal-fetchable URL for the local file at `path` (`falaw.upload`: content-addressed,
so an unchanged file is not uploaded twice).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
