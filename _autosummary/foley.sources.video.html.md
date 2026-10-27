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
  (`ffprobe` when on `PATH`; `None` when it cannot be read, which prices the call
  as an unknown cost, needing approval).
* [`local_video_file()`](#foley.sources.video.local_video_file): a local file for an uploader (bytes are written to a
  temporary file).
* [`keyed()`](#foley.sources.video.keyed): affordances as they may be recorded (the cache entry, the run
  manifest): the video replaced by its key, so neither its bytes nor a local path
  (nor an upload’s capability URL) is ever written down.

Stdlib only.

### Module Attributes

| [`VideoInput`](#foley.sources.video.VideoInput)   | a URL, a local path, or the encoded bytes.       |
|---------------------------------------------------------------|--------------------------------------------------|
| [`URL_SCHEMES`](#foley.sources.video.URL_SCHEMES)  | URL schemes sent to a backend as is (no upload). |

### Functions

| [`is_url`](#foley.sources.video.is_url)(video)                       | Whether `video` is a URL a backend can fetch itself.                                                                    |
|--------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| [`keyed`](#foley.sources.video.keyed)(affordances)                  | `affordances` with a `video` replaced by [`video_key()`](#foley.sources.video.video_key) (else unchanged). |
| [`local_video_file`](#foley.sources.video.local_video_file)(video)             | A local path holding `video` (bytes are written to a temporary file).                                                   |
| [`video_key`](#foley.sources.video.video_key)(video)                    | The cache identity of `video`: its content digest, or a remote URL as is.                                               |
| [`video_seconds`](#foley.sources.video.video_seconds)(video, \*[, ffprobe]) | The length of a local `video` in seconds, or `None` when it cannot be read.                                             |

### foley.sources.video.URL_SCHEMES *= ('http://', 'https://', 'data:')*

URL schemes sent to a backend as is (no upload).

### foley.sources.video.VideoInput

a URL, a local path, or the encoded bytes.

* **Type:**
  What `video=` accepts

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | `os.PathLike[str]` | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

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

### foley.sources.video.local_video_file(video)

A local path holding `video` (bytes are written to a temporary file).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

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

### foley.sources.video.video_seconds(video, , ffprobe=None)

The length of a local `video` in seconds, or `None` when it cannot be read.

Read by `ffprobe` (`ffprobe=` names the binary; default: the one on `PATH`).
A URL is not fetched to measure it: `None`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
