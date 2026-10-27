# foley.sources.music_library.verify

Checking a downloaded file is audio: an audio stream and a duration, read by foley’s probes.

[`probe_verify()`](#foley.sources.music_library.verify.probe_verify) is the default `verify` seam of
[`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire) (`bytes -> seconds`). It writes the
bytes to a temporary file, checks it has an audio stream with
[`foley.sources.video.has_audio_stream()`](foley.sources.video.html.md#foley.sources.video.has_audio_stream) (`ffprobe`, else `soundfile`), and
reads its length with [`foley.sources.video.default_probe()`](foley.sources.video.html.md#foley.sources.video.default_probe) (`ffprobe`, bounded
by a timeout, else mixing’s probe): the probes foley uses for media, rather than a
second ffprobe wrapper. An empty file, one with no audio stream (a video-only mp4, a
gif), one whose audio stream cannot be confirmed (fail closed), and one with no
readable duration (an error page saved as `.mp3`) are refused. [`require_probe()`](#foley.sources.music_library.verify.require_probe)
stops a batch before its first download when the checks cannot run.

### Module Attributes

| [`Verify`](#foley.sources.music_library.verify.Verify)   | how a file is checked to be a track (raises when it is not).   |
|-----------------------------------------------------------|----------------------------------------------------------------|

### Functions

| [`probe_available`](#foley.sources.music_library.verify.probe_available)()                                  | Whether [`probe_verify()`](#foley.sources.music_library.verify.probe_verify)'s probes can run here: `ffprobe` on `PATH`, or both mixing's video probe with an `ffmpeg` (the length) and `soundfile` (the audio stream).   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`probe_verify`](#foley.sources.music_library.verify.probe_verify)(data, \*[, probe, has_audio, suffix]) | The duration of the audio `data`, in seconds.                                                                                                                                                                        |
| [`require_probe`](#foley.sources.music_library.verify.require_probe)()                                    | Raise [`MusicToolMissing`](#foley.sources.music_library.verify.MusicToolMissing) unless [`probe_available()`](#foley.sources.music_library.verify.probe_available).                                                                   |

### Exceptions

| [`MusicToolMissing`](#foley.sources.music_library.verify.MusicToolMissing)   | A tool every title needs is missing: the batch stops before it starts.   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------|

### *exception* foley.sources.music_library.verify.MusicToolMissing

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

A tool every title needs is missing: the batch stops before it starts.

### foley.sources.music_library.verify.Verify

how a file is checked to be a track (raises when it is not).

* **Type:**
  `bytes -> seconds`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.music_library.verify.probe_available()

Whether [`probe_verify()`](#foley.sources.music_library.verify.probe_verify)’s probes can run here: `ffprobe` on `PATH`, or
both mixing’s video probe with an `ffmpeg` (the length) and `soundfile` (the
audio stream).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.music_library.verify.probe_verify(data, , probe=None, has_audio=None, suffix='.mp3')

The duration of the audio `data`, in seconds.

The bytes are written to a temporary file named with `suffix` (from a pipe,
ffprobe reports no duration). `has_audio(path) -> True | False | None` must
say `True` (default [`has_audio_stream()`](foley.sources.video.html.md#foley.sources.video.has_audio_stream); `None`,
“cannot tell”, is a refusal), then `probe(path) -> seconds | None` reads the
length (default [`default_probe()`](foley.sources.video.html.md#foley.sources.video.default_probe)).

```pycon
>>> probe_verify(b"ID3...", probe=lambda path: 61.5, has_audio=lambda path: True)
61.5
>>> probe_verify(b"<html>403</html>", probe=lambda path: 3.0,
...              has_audio=lambda path: False)
Traceback (most recent call last):
...
foley.sources.music_library.libraries.MusicLibraryError: the file has no audio stream
>>> probe_verify(b"ID3...", probe=lambda path: None, has_audio=lambda path: True)
Traceback (most recent call last):
...
foley.sources.music_library.libraries.MusicLibraryError: the file has no readable duration (not audio)
```

* **Raises:**
  [**MusicLibraryError**](foley.sources.music_library.html.md#foley.sources.music_library.MusicLibraryError) – When the file is empty, has no audio stream (or one
      cannot be confirmed), or has no readable duration.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.sources.music_library.verify.require_probe()

Raise [`MusicToolMissing`](#foley.sources.music_library.verify.MusicToolMissing) unless [`probe_available()`](#foley.sources.music_library.verify.probe_available).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
