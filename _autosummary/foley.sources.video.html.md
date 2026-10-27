# foley.sources.video

Video inputs of video-to-audio generation (#74): what `video=` may be, its identity, its length.

A video-to-audio (V2A) backend takes the picture the sound must follow. foley accepts
it as a **URL** (`http(s)://` or a `data:` URI, sent as is), a
[`RemoteVideo`](#foley.sources.video.RemoteVideo) (a URL with the SHA-256 of its content), a **local path**, or raw
**bytes** (both uploaded by the backend’s adapter). These questions are answered here,
once, for every V2A backend:

* [`video_key()`](#foley.sources.video.video_key): what the generations cache keys the video as. The **content**
  (`sha256:<hex>` of the bytes, the file or a [`RemoteVideo`](#foley.sources.video.RemoteVideo)’s digest), never
  its path, so a moved file hits the cache and an edited one cannot; a bare remote URL
  is keyed as the URL.
* [`replayable()`](#foley.sources.video.replayable): whether an identical request may be served from the cache. Not
  for a bare remote URL: the content behind it may have changed (#173).
* [`recorded_video_key()`](#foley.sources.video.recorded_video_key): the key as it is **written down** (a cache entry, a run
  manifest, a licence): a bare URL without its query, fragment or credentials, so a
  presigned URL’s token never reaches a record (#184). The request digest still
  hashes [`video_key()`](#foley.sources.video.video_key).
* [`video_seconds()`](#foley.sources.video.video_seconds): its length, for a backend priced per second of the video
  (`probe=`; default [`default_probe()`](#foley.sources.video.default_probe): `ffprobe` on `PATH`, else mixing’s
  `probe_duration` through mixing’s ffmpeg resolver; `None` when it cannot be read,
  which prices the call as an unknown cost, needing approval).
* [`has_audio_stream()`](#foley.sources.video.has_audio_stream): whether a media file has an audio stream (`ffprobe`,
  else `soundfile`; `None` when it cannot tell).
* [`local_video_file()`](#foley.sources.video.local_video_file): a local file for an uploader (bytes are written to a
  temporary file whose suffix is sniffed from them: [`video_suffix()`](#foley.sources.video.video_suffix)).
* [`audio_track()`](#foley.sources.video.audio_track): the audio of a backend’s muxed video answer (MMAudio,
  ThinkSound and HunyuanVideo-Foley return the video with the sound in it), via
  `ffmpeg` ([`ffmpeg_path()`](#foley.sources.video.ffmpeg_path)).
* [`keyed()`](#foley.sources.video.keyed): affordances as they may be recorded (the cache entry, the run
  manifest): the video replaced by its recorded key, so neither its bytes nor a local
  path (nor an upload’s capability URL, nor a presigned URL’s token) is written down.

Stdlib only (mixing is used when installed, never required).

### Module Attributes

| [`REMOTE_SCHEMES`](#foley.sources.video.REMOTE_SCHEMES)        | Schemes of a URL the backend fetches from a server (what it serves may change).                    |
|------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| [`URL_SCHEMES`](#foley.sources.video.URL_SCHEMES)           | URL schemes sent to a backend as is (no upload); a `data:` URI holds its content.                  |
| [`URL_KEY_PREFIX`](#foley.sources.video.URL_KEY_PREFIX)        | The key prefix of a video known only by its URL (its content unseen).                              |
| [`VideoInput`](#foley.sources.video.VideoInput)            | a URL, a [`RemoteVideo`](#foley.sources.video.RemoteVideo), a local path, or the bytes. |
| [`AUDIO_TRACK_TIMEOUT_S`](#foley.sources.video.AUDIO_TRACK_TIMEOUT_S) | The most [`audio_track()`](#foley.sources.video.audio_track) lets ffmpeg run (s).       |
| [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)       | The most [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) lets ffprobe run (s).  |
| [`DEFAULT_VIDEO_SUFFIX`](#foley.sources.video.DEFAULT_VIDEO_SUFFIX)  | The suffix of bytes no signature matches (and of every other ISO BMFF brand).                      |
| [`Probe`](#foley.sources.video.Probe)                 | how [`video_seconds()`](#foley.sources.video.video_seconds) reads a local file's length.  |
| [`AudioStreamCheck`](#foley.sources.video.AudioStreamCheck)      | whether a media file has an audio stream (`None`: it cannot tell).                                 |
| [`REDACTED_QUERY`](#foley.sources.video.REDACTED_QUERY)        | What stands in for a recorded URL's query and fragment.                                            |

### Functions

| [`audio_track`](#foley.sources.video.audio_track)(container, \*[, ffmpeg, timeout_s])   | The audio of a muxed video, as WAV bytes (16-bit PCM, its own rate and channels).                                                                                                                                                                                                                                                                        |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`default_probe`](#foley.sources.video.default_probe)(path)                               | [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) (bounded by [`PROBE_TIMEOUT_S`](#foley.sources.video.PROBE_TIMEOUT_S)) when `ffprobe` is on `PATH`, else [`mixing_seconds()`](#foley.sources.video.mixing_seconds).                                                                                                    |
| [`fal_immutable_url`](#foley.sources.video.fal_immutable_url)(url)                            | falaw's `is_immutable_url` (fal's own CDN mints a new URL per upload), else `False` when falaw is not installed: an unknown URL is taken as mutable.                                                                                                                                                                                                     |
| [`ffmpeg_path`](#foley.sources.video.ffmpeg_path)()                                     | An `ffmpeg` binary: mixing's resolver (a pip-bundled one too), else `PATH`.                                                                                                                                                                                                                                                                              |
| [`ffprobe_seconds`](#foley.sources.video.ffprobe_seconds)(path, \*[, ffprobe])              | The length of the video file at `path` by `ffprobe` (default: the one on `PATH`), or `None` when there is none or it cannot read it.                                                                                                                                                                                                                     |
| [`has_audio_stream`](#foley.sources.video.has_audio_stream)(path, \*[, ffprobe])             | Whether the media file at `path` has an audio stream, or `None` when that cannot be told.                                                                                                                                                                                                                                                                |
| [`is_url`](#foley.sources.video.is_url)(video)                                     | Whether `video` is a URL a backend can fetch itself.                                                                                                                                                                                                                                                                                                     |
| [`is_video_key`](#foley.sources.video.is_video_key)(value)                               | Whether `value` is already a key [`video_key()`](#foley.sources.video.video_key) makes (as a cache entry keeps it).                                                                                                                                                                                                                         |
| [`keyed`](#foley.sources.video.keyed)(affordances, \*[, key])                     | `affordances` with a `video` replaced by its `key` (else unchanged).                                                                                                                                                                                                                                                                                     |
| [`local_video_file`](#foley.sources.video.local_video_file)(video, \*[, suffix])             | A local path holding `video` (bytes are written to a temporary file).                                                                                                                                                                                                                                                                                    |
| [`mixing_seconds`](#foley.sources.video.mixing_seconds)(path)                              | The length by mixing's `probe_duration` (`ffmpeg -i` through mixing's ffmpeg resolver, a pip-bundled ffmpeg too), or `None` when mixing's video stack is not installed or finds no ffmpeg.                                                                                                                                                               |
| [`recorded_video_key`](#foley.sources.video.recorded_video_key)(video)                         | [`video_key()`](#foley.sources.video.video_key) as it is written down: a bare URL keeps its scheme, host and path only (#184): its query, fragment and `;` path parameters (a presigned URL's signature, a session id) become [`REDACTED_QUERY`](#foley.sources.video.REDACTED_QUERY), and credentials before the host are dropped. |
| [`replayable`](#foley.sources.video.replayable)(affordances, \*[, is_immutable])       | Whether an identical request may be served from the cache (#173).                                                                                                                                                                                                                                                                                        |
| [`video_key`](#foley.sources.video.video_key)(video)                                  | The cache identity of `video`: its content digest, or a bare remote URL as is.                                                                                                                                                                                                                                                                           |
| [`video_seconds`](#foley.sources.video.video_seconds)(video, \*[, probe])                 | The length of a local `video` in seconds, or `None` when it cannot be read.                                                                                                                                                                                                                                                                              |
| [`video_suffix`](#foley.sources.video.video_suffix)(data)                                | The file suffix of encoded video `data`, sniffed from its first bytes.                                                                                                                                                                                                                                                                                   |
| [`video_url`](#foley.sources.video.video_url)(video)                                  | The URL a backend fetches `video` from itself, or `None` (a path or bytes).                                                                                                                                                                                                                                                                              |

### Classes

| [`RemoteVideo`](#foley.sources.video.RemoteVideo)(\*, url, sha256)   | A remote video `url` with the SHA-256 of its bytes: keyed, and replayed, by content.   |
|---------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|

### foley.sources.video.AUDIO_TRACK_TIMEOUT_S *= 120.0*

The most [`audio_track()`](#foley.sources.video.audio_track) lets ffmpeg run (s).

### foley.sources.video.AudioStreamCheck

whether a media file has an audio stream
(`None`: it cannot tell). [`has_audio_stream()`](#foley.sources.video.has_audio_stream) is the default.

* **Type:**
  `path -> True | False | None`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### foley.sources.video.DEFAULT_VIDEO_SUFFIX *= '.mp4'*

The suffix of bytes no signature matches (and of every other ISO BMFF brand).

### foley.sources.video.PROBE_TIMEOUT_S *= 30.0*

The most [`ffprobe_seconds()`](#foley.sources.video.ffprobe_seconds) lets ffprobe run (s).

### foley.sources.video.Probe

how [`video_seconds()`](#foley.sources.video.video_seconds) reads a local file’s length.

* **Type:**
  `video -> seconds | None`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### foley.sources.video.REDACTED_QUERY *= '?…'*

What stands in for a recorded URL’s query and fragment.

### foley.sources.video.REMOTE_SCHEMES *= ('http://', 'https://')*

Schemes of a URL the backend fetches from a server (what it serves may change).

### *class* foley.sources.video.RemoteVideo(, url, sha256)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A remote video `url` with the SHA-256 of its bytes: keyed, and replayed, by content.

A bare `https://` URL is keyed as the URL, which foley cannot see behind, so an
identical request for it is never served from the generations cache (the picture
may have changed: `.../latest.mp4`). A caller who knows the content passes this
instead, and a repeat is replayed while the digest is the same (#173).

The digest is **trusted, not checked** (foley does not fetch the URL): it is
recorded as the input’s identity in the cache key and the licence’s
`generation_params`, as a digest foley computed would be.

```pycon
>>> RemoteVideo(url="https://x/clip.mp4", sha256="sha256:" + "ab" * 32).sha256[:4]
'abab'
>>> RemoteVideo(url="clip.mp4", sha256="ab" * 32)
Traceback (most recent call last):
...
ValueError: RemoteVideo.url must be an http(s) URL, got 'clip.mp4'
```

### foley.sources.video.URL_KEY_PREFIX *= 'url:'*

The key prefix of a video known only by its URL (its content unseen).

### foley.sources.video.URL_SCHEMES *= ('http://', 'https://', 'data:')*

URL schemes sent to a backend as is (no upload); a `data:` URI holds its content.

### foley.sources.video.VideoInput

a URL, a [`RemoteVideo`](#foley.sources.video.RemoteVideo), a local path, or the bytes.

* **Type:**
  What `video=` accepts

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`RemoteVideo`](#foley.sources.video.RemoteVideo) | `os.PathLike[str]` | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

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

### foley.sources.video.fal_immutable_url(url)

falaw’s `is_immutable_url` (fal’s own CDN mints a new URL per upload), else
`False` when falaw is not installed: an unknown URL is taken as mutable.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

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

### foley.sources.video.is_url(video)

Whether `video` is a URL a backend can fetch itself.

```pycon
>>> is_url("https://x/clip.mp4"), is_url("clip.mp4"), is_url(b"...")
(True, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.video.is_video_key(value)

Whether `value` is already a key [`video_key()`](#foley.sources.video.video_key) makes (as a cache entry keeps it).

```pycon
>>> is_video_key("sha256:" + "ab" * 32), is_video_key("url:https://x/a.mp4")
(True, True)
>>> is_video_key("clip.mp4"), is_video_key(b"sha256:")
(False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.video.keyed(affordances, \*, key=<function recorded_video_key>)

`affordances` with a `video` replaced by its `key` (else unchanged).

The default is the key as it is written down ([`recorded_video_key()`](#foley.sources.video.recorded_video_key)); the
request digest passes `key=video_key`, the full identity, which is only hashed.

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

### foley.sources.video.recorded_video_key(video)

[`video_key()`](#foley.sources.video.video_key) as it is written down: a bare URL keeps its scheme, host and
path only (#184): its query, fragment and `;` path parameters (a presigned URL’s
signature, a session id) become [`REDACTED_QUERY`](#foley.sources.video.REDACTED_QUERY), and credentials before
the host are dropped. Two URLs that differ only there record (and are found by
[`find()`](foley.stores.html.md#foley.stores.GenerationsCache.find)) as one, as a re-signed URL should.
An already recorded or bare `url:` key is redacted the same way.

```pycon
>>> recorded_video_key("https://u:p@bucket.s3.example/a.mp4?X-Amz-Signature=s3cr3t")
'url:https://bucket.s3.example/a.mp4?…'
>>> recorded_video_key("https://[::1]:8080/a.mp4;jsessionid=X#t=2")
'url:https://[::1]:8080/a.mp4?…'
>>> recorded_video_key("https://x/a.mp4"), recorded_video_key(b"abc")[:11]
('url:https://x/a.mp4', 'sha256:ba78')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.video.replayable(affordances, \*, is_immutable=<function fal_immutable_url>)

Whether an identical request may be served from the cache (#173).

Not when its video is a bare remote URL whose content foley never saw, unless
`is_immutable(url)` says it never serves other bytes (default:
[`fal_immutable_url()`](#foley.sources.video.fal_immutable_url), fal’s own CDN). Decided from the value alone: no file
is read.

```pycon
>>> replayable({"video": "https://x/latest.mp4"}), replayable({"video": b"abc"})
(False, True)
>>> replayable({"video": "https://x/a.mp4"}, is_immutable=lambda url: True)
True
>>> replayable({"seed": 1})
True
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.video.video_key(video)

The cache identity of `video`: its content digest, or a bare remote URL as is.

```pycon
>>> video_key(b"abc")[:15]
'sha256:ba7816bf'
>>> video_key("https://x/clip.mp4")
'url:https://x/clip.mp4'
>>> video_key(RemoteVideo(url="https://x/clip.mp4", sha256="ab" * 32))[:11]
'sha256:abab'
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

### foley.sources.video.video_url(video)

The URL a backend fetches `video` from itself, or `None` (a path or bytes).

```pycon
>>> video_url("https://x/clip.mp4"), video_url("clip.mp4"), video_url(b"...")
('https://x/clip.mp4', None, None)
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
