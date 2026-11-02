# foley.sources.video

Video inputs of generation (#74): a video’s length, and the audio of a muxed video answer.

A video-to-audio (V2A) backend takes the picture the sound must follow (`video=`).
How a media input is keyed, recorded, replayed and uploaded (a video and an edit’s
`audio=` alike) is in [`foley.sources.media`](foley.sources.media.html.md#module-foley.sources.media); what only a video needs is here:

* [`video_seconds()`](#foley.sources.video.video_seconds): its length, for a backend priced per second of the video
  (`probe=`; default [`default_probe()`](#foley.sources.video.default_probe): `ffprobe` on `PATH`, else mixing’s
  `probe_duration` through mixing’s ffmpeg resolver; `None` when it cannot be read,
  which prices the call as an unknown cost, needing approval).
* [`has_audio_stream()`](#foley.sources.video.has_audio_stream): whether a media file has an audio stream (`ffprobe`,
  else `soundfile`; `None` when it cannot tell).
* [`audio_track()`](#foley.sources.video.audio_track): the audio of a backend’s muxed video answer (MMAudio,
  ThinkSound and HunyuanVideo-Foley return the video with the sound in it), via
  `ffmpeg` ([`ffmpeg_path()`](#foley.sources.video.ffmpeg_path)).

The helpers that now serve every media input (#215) were named for the video and are
still importable from here under those names, as plain aliases of their
[`foley.sources.media`](foley.sources.media.html.md#module-foley.sources.media) versions: `video_key()` ([`media_key()`](foley.sources.media.html.md#foley.sources.media.media_key)),
`is_video_key()` ([`is_media_key()`](foley.sources.media.html.md#foley.sources.media.is_media_key)),
`recorded_video_key()` ([`recorded_media_key()`](foley.sources.media.html.md#foley.sources.media.recorded_media_key)),
`video_url()` ([`media_url()`](foley.sources.media.html.md#foley.sources.media.media_url)),
`local_video_file()` ([`local_media_file()`](foley.sources.media.html.md#foley.sources.media.local_media_file)) and
[`VideoInput`](#foley.sources.video.VideoInput) ([`MediaValue`](foley.sources.media.html.md#foley.sources.media.MediaValue)); the rest of that module’s
names (`MEDIA`, `keyed()`, `replayable()`, `RemoteVideo`, …) are
re-exported as they are.

Stdlib only (mixing and soundfile are used when installed, never required).

### Module Attributes

| [`VideoInput`](#foley.sources.video.VideoInput)            | What `video=` accepts ([`MediaValue`](foley.sources.media.html.md#foley.sources.media.MediaValue)).   |
|------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`AUDIO_TRACK_TIMEOUT_S`](#foley.sources.video.AUDIO_TRACK_TIMEOUT_S) | The most [`audio_track()`](#foley.sources.video.audio_track) lets ffmpeg run (s).                          |
| [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)       | The most [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) lets ffprobe run (s).                     |
| [`Probe`](#foley.sources.video.Probe)                 | how [`video_seconds()`](#foley.sources.video.video_seconds) reads a local file's length.                     |
| [`AudioStreamCheck`](#foley.sources.video.AudioStreamCheck)      | whether a media file has an audio stream (`None`: it cannot tell).                                                    |

### Functions

| [`audio_track`](#foley.sources.video.audio_track)(container, \*[, ffmpeg, timeout_s])   | The audio of a muxed video, as WAV bytes (16-bit PCM, its own rate and channels).                                                                                                                                                                     |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`default_probe`](#foley.sources.video.default_probe)(path)                               | [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) (bounded by [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)) when `ffprobe` is on `PATH`, else [`mixing_seconds()`](#foley.sources.video.mixing_seconds). |
| [`ffmpeg_path`](#foley.sources.video.ffmpeg_path)()                                     | An `ffmpeg` binary: mixing's resolver (a pip-bundled one too), else `PATH`.                                                                                                                                                                           |
| [`ffprobe_seconds`](#foley.sources.video.ffprobe_seconds)(path, \*[, ffprobe])              | The length of the video file at `path` by `ffprobe` (default: the one on `PATH`), or `None` when there is none or it cannot read it.                                                                                                                  |
| [`has_audio_stream`](#foley.sources.video.has_audio_stream)(path, \*[, ffprobe])             | Whether the media file at `path` has an audio stream, or `None` when that cannot be told.                                                                                                                                                             |
| [`mixing_seconds`](#foley.sources.video.mixing_seconds)(path)                              | The length by mixing's `probe_duration` (`ffmpeg -i` through mixing's ffmpeg resolver, a pip-bundled ffmpeg too), or `None` when mixing's video stack is not installed or finds no ffmpeg.                                                            |
| [`video_seconds`](#foley.sources.video.video_seconds)(video, \*[, probe])                 | The length of a local `video` in seconds, or `None` when it cannot be read.                                                                                                                                                                           |

### foley.sources.video.AUDIO_TRACK_TIMEOUT_S *= 120.0*

The most [`audio_track()`](#foley.sources.video.audio_track) lets ffmpeg run (s).

### foley.sources.video.AudioStreamCheck

whether a media file has an audio stream
(`None`: it cannot tell). [`has_audio_stream()`](#foley.sources.video.has_audio_stream) is the default.

* **Type:**
  `path -> True | False | None`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### foley.sources.video.PROBE_TIMEOUT_S *= 30.0*

The most [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) lets ffprobe run (s).

### foley.sources.video.Probe

how [`video_seconds()`](#foley.sources.video.video_seconds) reads a local file’s length.

* **Type:**
  `video -> seconds | None`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### foley.sources.video.VideoInput

What `video=` accepts ([`MediaValue`](foley.sources.media.html.md#foley.sources.media.MediaValue)).

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`RemoteVideo`](foley.sources.media.html.md#foley.sources.media.RemoteVideo) | `os.PathLike[str]` | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.sources.video.audio_track(container, , ffmpeg=None, timeout_s=120.0)

The audio of a muxed video, as WAV bytes (16-bit PCM, its own rate and channels).

Written to a file, not a pipe, so ffmpeg can finish the WAV header (a piped WAV
carries a streaming placeholder size).

* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If no `ffmpeg` is found, it cannot read an audio stream, or it
      runs past `timeout_s`.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.sources.video.default_probe(path)

[`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) (bounded by [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)) when `ffprobe` is on
`PATH`, else [`mixing_seconds()`](#foley.sources.video.mixing_seconds). Never both: a file that stalls ffprobe would
stall mixing’s unbounded `ffmpeg -i` too.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.video.ffmpeg_path()

An `ffmpeg` binary: mixing’s resolver (a pip-bundled one too), else `PATH`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.video.ffprobe_seconds(path, , ffprobe=None)

The length of the video file at `path` by `ffprobe` (default: the one on
`PATH`), or `None` when there is none or it cannot read it.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.video.has_audio_stream(path, , ffprobe=None)

Whether the media file at `path` has an audio stream, or `None` when that
cannot be told.

By `ffprobe` (default: the one on `PATH`; bounded by [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)):
`True` when it lists an audio stream, `False` when it lists none or cannot
read the file (a video-only mp4, a gif, an error page), `None` when it cannot
run or runs too long. Without `ffprobe`, by `soundfile` (the decoder
[`foley.audio.load()`](foley.audio.html.md#foley.audio.load) uses): `True` when it decodes the file to one or more
channels, else `None` (it reads no video container, so its refusal says
nothing). A caller that needs an answer treats `None` as no (fail closed).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### foley.sources.video.mixing_seconds(path)

The length by mixing’s `probe_duration` (`ffmpeg -i` through mixing’s ffmpeg
resolver, a pip-bundled ffmpeg too), or `None` when mixing’s video stack is not
installed or finds no ffmpeg. Unbounded: mixing’s probe has no timeout yet
(reeleehq/mixing#88).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.video.video_seconds(video, , probe=None)

The length of a local `video` in seconds, or `None` when it cannot be read.

`probe(path) -> seconds | None` reads it (default: [`default_probe()`](#foley.sources.video.default_probe)); a
probe that raises counts as unreadable. A URL is not fetched to measure it:
`None`.

```pycon
>>> video_seconds(b"...", probe=lambda path: 4.5)
4.5
>>> video_seconds("https://x/clip.mp4", probe=lambda path: 4.5) is None
True
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
