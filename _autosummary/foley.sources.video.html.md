# foley.sources.video

Video inputs of video-to-audio generation (#74): what `video=` may be, its identity, its length.

A video-to-audio (V2A) backend takes the picture the sound must follow. foley accepts
it as a **URL** (`http(s)://` or a `data:` URI, sent as is), a **local path**, or
raw **bytes** (both uploaded by the backend’s adapter). Three questions are answered
here, once, for every V2A backend:

* [`video_key()`](#foley.sources.video.video_key): what the generations cache keys the video as. The **content**
  (`sha256:<hex>` of the bytes or of the file), never its path, so a moved file hits
  the cache and an edited one cannot; a remote URL is keyed as the URL.
* [`video_seconds()`](#foley.sources.video.video_seconds): its length, for a backend priced per second of the video
  (`probe=`; default [`default_probe()`](#foley.sources.video.default_probe): `ffprobe` on `PATH`, else mixing’s
  `probe_duration` through mixing’s ffmpeg resolver; `None` when it cannot be read,
  which prices the call as an unknown cost, needing approval).
* [`local_video_file()`](#foley.sources.video.local_video_file): a local file for an uploader (bytes are written to a
  temporary file whose suffix is sniffed from them: [`video_suffix()`](#foley.sources.video.video_suffix)).
* [`audio_track()`](#foley.sources.video.audio_track): the audio of a backend’s muxed video answer (MMAudio,
  ThinkSound and HunyuanVideo-Foley return the video with the sound in it), via
  `ffmpeg` ([`ffmpeg_path()`](#foley.sources.video.ffmpeg_path)).
* [`keyed()`](#foley.sources.video.keyed): affordances as they may be recorded (the cache entry, the run
  manifest): the video replaced by its key, so neither its bytes nor a local path
  (nor an upload’s capability URL) is ever written down.

Stdlib only (mixing is used when installed, never required).

### Module Attributes

| [`VideoInput`](#foley.sources.video.VideoInput)            | a URL, a local path, or the encoded bytes.                                                        |
|------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| [`URL_SCHEMES`](#foley.sources.video.URL_SCHEMES)           | URL schemes sent to a backend as is (no upload).                                                  |
| [`AUDIO_TRACK_TIMEOUT_S`](#foley.sources.video.AUDIO_TRACK_TIMEOUT_S) | The most [`audio_track()`](#foley.sources.video.audio_track) lets ffmpeg run (s).      |
| [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)       | The most [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) lets ffprobe run (s). |
| [`DEFAULT_VIDEO_SUFFIX`](#foley.sources.video.DEFAULT_VIDEO_SUFFIX)  | The suffix of bytes no signature matches (and of every other ISO BMFF brand).                     |
| [`Probe`](#foley.sources.video.Probe)                 | how [`video_seconds()`](#foley.sources.video.video_seconds) reads a local file's length. |

### Functions

| [`audio_track`](#foley.sources.video.audio_track)(container, \*[, ffmpeg, timeout_s])   | The audio of a muxed video, as WAV bytes (16-bit PCM, its own rate and channels).                                                                                                                                                                     |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`default_probe`](#foley.sources.video.default_probe)(path)                               | [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) (bounded by [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)) when `ffprobe` is on `PATH`, else [`mixing_seconds()`](#foley.sources.video.mixing_seconds). |
| [`ffmpeg_path`](#foley.sources.video.ffmpeg_path)()                                     | An `ffmpeg` binary: mixing's resolver (a pip-bundled one too), else `PATH`.                                                                                                                                                                           |
| [`ffprobe_seconds`](#foley.sources.video.ffprobe_seconds)(path, \*[, ffprobe])              | The length of the video file at `path` by `ffprobe` (default: the one on `PATH`), or `None` when there is none or it cannot read it.                                                                                                                  |
| [`is_url`](#foley.sources.video.is_url)(video)                                     | Whether `video` is a URL a backend can fetch itself.                                                                                                                                                                                                  |
| [`keyed`](#foley.sources.video.keyed)(affordances)                                | `affordances` with a `video` replaced by [`video_key()`](#foley.sources.video.video_key) (else unchanged).                                                                                                                               |
| [`local_video_file`](#foley.sources.video.local_video_file)(video, \*[, suffix])             | A local path holding `video` (bytes are written to a temporary file).                                                                                                                                                                                 |
| [`mixing_seconds`](#foley.sources.video.mixing_seconds)(path)                              | The length by mixing's `probe_duration` (`ffmpeg -i` through mixing's ffmpeg resolver, a pip-bundled ffmpeg too), or `None` when mixing's video stack is not installed or finds no ffmpeg.                                                            |
| [`video_key`](#foley.sources.video.video_key)(video)                                  | The cache identity of `video`: its content digest, or a remote URL as is.                                                                                                                                                                             |
| [`video_seconds`](#foley.sources.video.video_seconds)(video, \*[, probe])                 | The length of a local `video` in seconds, or `None` when it cannot be read.                                                                                                                                                                           |
| [`video_suffix`](#foley.sources.video.video_suffix)(data)                                | The file suffix of encoded video `data`, sniffed from its first bytes.                                                                                                                                                                                |

### foley.sources.video.AUDIO_TRACK_TIMEOUT_S *= 120.0*

The most [`audio_track()`](#foley.sources.video.audio_track) lets ffmpeg run (s).

### foley.sources.video.DEFAULT_VIDEO_SUFFIX *= '.mp4'*

The suffix of bytes no signature matches (and of every other ISO BMFF brand).

### foley.sources.video.PROBE_TIMEOUT_S *= 30.0*

The most [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) lets ffprobe run (s).

### foley.sources.video.Probe

how [`video_seconds()`](#foley.sources.video.video_seconds) reads a local file’s length.

* **Type:**
  `video -> seconds | None`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### foley.sources.video.URL_SCHEMES *= ('http://', 'https://', 'data:')*

URL schemes sent to a backend as is (no upload).

### foley.sources.video.VideoInput

a URL, a local path, or the encoded bytes.

* **Type:**
  What `video=` accepts

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | `os.PathLike[str]` | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

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

### foley.sources.video.is_url(video)

Whether `video` is a URL a backend can fetch itself.

```pycon
>>> is_url("https://x/clip.mp4"), is_url("clip.mp4"), is_url(b"...")
(True, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.video.keyed(affordances)

`affordances` with a `video` replaced by [`video_key()`](#foley.sources.video.video_key) (else unchanged).

```pycon
>>> keyed({"video": b"abc", "duration_s": 2})["video"][:15], keyed({"seed": 1})
('sha256:ba7816bf', {'seed': 1})
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.video.local_video_file(video, , suffix=None)

A local path holding `video` (bytes are written to a temporary file).

`suffix` names the temporary file’s format; default: [`video_suffix()`](#foley.sources.video.video_suffix) of the
bytes. A path is yielded as is.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.video.mixing_seconds(path)

The length by mixing’s `probe_duration` (`ffmpeg -i` through mixing’s ffmpeg
resolver, a pip-bundled ffmpeg too), or `None` when mixing’s video stack is not
installed or finds no ffmpeg. Unbounded: mixing’s probe has no timeout yet
(reeleehq/mixing#88).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.video.video_key(video)

The cache identity of `video`: its content digest, or a remote URL as is.

```pycon
>>> video_key(b"abc")[:15]
'sha256:ba7816bf'
>>> video_key("https://x/clip.mp4")
'url:https://x/clip.mp4'
```

* **Raises:**
  * [**FileNotFoundError**](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) – If `video` names a local file that does not exist.
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If `video` is none of a URL, a path or bytes.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

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

### foley.sources.video.video_suffix(data)

The file suffix of encoded video `data`, sniffed from its first bytes.

An uploader (and ffmpeg) names the format by the suffix, so a WebM written as
`.mp4` goes out mislabelled. Anything unrecognised is `.mp4`.

```pycon
>>> video_suffix(b"\x00\x00\x00\x18ftypqt  \x00"), video_suffix(b"\x00\x00\x00\x18ftypisom")
('.mov', '.mp4')
>>> video_suffix(b"\x1a\x45\xdf\xa3\x9f\x42\x82\x84webm"), video_suffix(b"\x1a\x45\xdf\xa3")
('.webm', '.mkv')
>>> video_suffix(b"RIFF\x00\x00\x00\x00AVI "), video_suffix(b"OggS"), video_suffix(b"?")
('.avi', '.ogv', '.mp4')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
