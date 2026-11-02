# foley.sources.media

Media inputs of generation (#74, #162, #215): what `video=` and an edit’s `audio=` may be, and their identity.

A backend that sounds a picture (video-to-audio) takes a `video=`; a backend that
edits a source clip takes an `audio=`. Both are **media inputs** ([`MEDIA`](#foley.sources.media.MEDIA),
[`MEDIA_INPUTS`](#foley.sources.media.MEDIA_INPUTS)) and take the same forms: a **URL** (`http(s)://` or a
`data:` URI, sent as is), a [`RemoteVideo`](#foley.sources.media.RemoteVideo) (a URL with the SHA-256 of its
content), a **local path**, or raw **bytes** (both uploaded by the backend’s adapter).
These questions are answered here, once, for every media input:

* [`media_key()`](#foley.sources.media.media_key): what the generations cache keys the input as. The **content**
  (`sha256:<hex>` of the bytes, the file or a [`RemoteVideo`](#foley.sources.media.RemoteVideo)’s digest), never
  its path, so a moved file hits the cache and an edited one cannot; a bare remote URL
  is keyed as the URL.
* [`is_media_key()`](#foley.sources.media.is_media_key): whether a value is already such a key (as a cache entry keeps it).
* [`replayable()`](#foley.sources.media.replayable): whether an identical request may be served from the cache. Not
  for a bare remote URL: the content behind it may have changed (#173).
* [`recorded_media_key()`](#foley.sources.media.recorded_media_key): the key as it is **written down** (a cache entry, a run
  manifest, a licence): a bare URL without its query, fragment or credentials, so a
  presigned URL’s token never reaches a record (#184). The request digest still
  hashes [`media_key()`](#foley.sources.media.media_key).
* [`media_url()`](#foley.sources.media.media_url): the URL a backend fetches the input from itself, if it is one.
* [`local_media_file()`](#foley.sources.media.local_media_file): a local file for an uploader (bytes are written to a
  temporary file whose suffix is sniffed from them: [`video_suffix()`](#foley.sources.media.video_suffix), or the
  input’s own sniffer, [`MediaInput.suffix()`](#foley.sources.media.MediaInput.suffix)).
* [`keyed()`](#foley.sources.media.keyed): affordances as they may be recorded (the cache entry, the run
  manifest): each media input replaced by its recorded key, so neither its bytes nor a
  local path (nor an upload’s capability URL, nor a presigned URL’s token) is written
  down.

Each media input is one row of [`MEDIA`](#foley.sources.media.MEDIA) (its mode, its upload suffix sniffer, its
length probe): a video’s suffix is sniffed by [`video_suffix()`](#foley.sources.media.video_suffix) and its length read
by [`foley.sources.video.video_seconds()`](foley.sources.video.html.md#foley.sources.video.video_seconds); an edit’s source clip’s by
[`audio_suffix()`](#foley.sources.media.audio_suffix) and [`audio_seconds()`](#foley.sources.media.audio_seconds).

What only a video has (its length by `ffprobe`/mixing, the audio track of a muxed
answer) is in [`foley.sources.video`](foley.sources.video.html.md#module-foley.sources.video), which also keeps this module’s helpers
importable under their former `video_*` names.

Stdlib only (soundfile and falaw are used when installed, never required).

### Module Attributes

| [`MEDIA`](#foley.sources.media.MEDIA)                | the media inputs a backend is given (keyed by content, never by path), in precedence order (a video decides the mode over an audio).   |
|-----------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| [`MEDIA_INPUTS`](#foley.sources.media.MEDIA_INPUTS)         | The affordances of [`MEDIA`](#foley.sources.media.MEDIA).                                                             |
| [`REMOTE_SCHEMES`](#foley.sources.media.REMOTE_SCHEMES)       | Schemes of a URL the backend fetches from a server (what it serves may change).                                                        |
| [`URL_SCHEMES`](#foley.sources.media.URL_SCHEMES)          | URL schemes sent to a backend as is (no upload); a `data:` URI holds its content.                                                      |
| [`URL_KEY_PREFIX`](#foley.sources.media.URL_KEY_PREFIX)       | The key prefix of a media input known only by its URL (its content unseen).                                                            |
| [`MediaValue`](#foley.sources.media.MediaValue)           | a URL, a [`RemoteVideo`](#foley.sources.media.RemoteVideo), a local path, or the bytes.                                     |
| [`REDACTED_QUERY`](#foley.sources.media.REDACTED_QUERY)       | What stands in for a recorded URL's query and fragment.                                                                                |
| [`DEFAULT_VIDEO_SUFFIX`](#foley.sources.media.DEFAULT_VIDEO_SUFFIX) | The suffix of video bytes no signature matches (and of every other ISO BMFF brand).                                                    |
| [`DEFAULT_AUDIO_SUFFIX`](#foley.sources.media.DEFAULT_AUDIO_SUFFIX) | The suffix of audio bytes no signature matches.                                                                                        |

### Functions

| [`audio_seconds`](#foley.sources.media.audio_seconds)(audio)                        | The length of an audio input (bytes or a local path) in seconds, or `None`.                                                                                                                                                                                                                                                                              |
|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`audio_suffix`](#foley.sources.media.audio_suffix)(data)                          | The file suffix of encoded audio `data` (flac, wav, mp3, ogg), sniffed from its first bytes.                                                                                                                                                                                                                                                             |
| [`fal_immutable_url`](#foley.sources.media.fal_immutable_url)(url)                      | falaw's `is_immutable_url` (fal's own CDN mints a new URL per upload), else `False` when falaw is not installed: an unknown URL is taken as mutable.                                                                                                                                                                                                     |
| [`is_media_key`](#foley.sources.media.is_media_key)(value)                         | Whether `value` is already a key [`media_key()`](#foley.sources.media.media_key) makes (as a cache entry keeps it).                                                                                                                                                                                                                         |
| [`is_url`](#foley.sources.media.is_url)(media)                               | Whether `media` is a URL a backend can fetch itself.                                                                                                                                                                                                                                                                                                     |
| [`keyed`](#foley.sources.media.keyed)(affordances, \*[, key])               | `affordances` with each media input ([`MEDIA_INPUTS`](#foley.sources.media.MEDIA_INPUTS)) replaced by its `key`.                                                                                                                                                                                                                               |
| [`local_media_file`](#foley.sources.media.local_media_file)(media, \*[, suffix])       | A local path holding `media` (bytes are written to a temporary file).                                                                                                                                                                                                                                                                                    |
| [`media_key`](#foley.sources.media.media_key)(media)                            | The cache identity of `media`: its content digest, or a bare remote URL as is.                                                                                                                                                                                                                                                                           |
| [`media_url`](#foley.sources.media.media_url)(media)                            | The URL a backend fetches `media` from itself, or `None` (a path or bytes).                                                                                                                                                                                                                                                                              |
| [`recorded_media_key`](#foley.sources.media.recorded_media_key)(media)                   | [`media_key()`](#foley.sources.media.media_key) as it is written down: a bare URL keeps its scheme, host and path only (#184): its query, fragment and `;` path parameters (a presigned URL's signature, a session id) become [`REDACTED_QUERY`](#foley.sources.media.REDACTED_QUERY), and credentials before the host are dropped. |
| [`remote_media_input`](#foley.sources.media.remote_media_input)(affordances)             | The name of the first media input given as a bare remote URL, or `None`.                                                                                                                                                                                                                                                                                 |
| [`replayable`](#foley.sources.media.replayable)(affordances, \*[, is_immutable]) | Whether an identical request may be served from the cache (#173).                                                                                                                                                                                                                                                                                        |
| [`video_suffix`](#foley.sources.media.video_suffix)(data)                          | The file suffix of encoded video `data`, sniffed from its first bytes.                                                                                                                                                                                                                                                                                   |

### Classes

| [`MediaInput`](#foley.sources.media.MediaInput)(name, mode, does, covers, ...)   | One media input of generation (a row of [`MEDIA`](#foley.sources.media.MEDIA)): the affordance that carries it, the mode it puts a call in, and how foley reads it.   |
|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`RemoteVideo`](#foley.sources.media.RemoteVideo)(\*, url, sha256)                | A remote video `url` with the SHA-256 of its bytes: keyed, and replayed, by content.                                                                                                   |

### foley.sources.media.DEFAULT_AUDIO_SUFFIX *= '.wav'*

The suffix of audio bytes no signature matches.

### foley.sources.media.DEFAULT_VIDEO_SUFFIX *= '.mp4'*

The suffix of video bytes no signature matches (and of every other ISO BMFF brand).

### foley.sources.media.MEDIA *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [MediaInput](#foley.sources.media.MediaInput)]* *= {'audio': MediaInput(name='audio', mode='edit', does='edits a source clip', covers='to match the source clip', suffix_of='media.audio_suffix', seconds_of='media.audio_seconds'), 'video': MediaInput(name='video', mode='v2a', does='sounds a picture', covers='to cover the video', suffix_of='media.video_suffix', seconds_of='video.video_seconds')}*

the media inputs a backend is given (keyed by content, never by path), in
precedence order (a video decides the mode over an audio).

* **Type:**
  SSOT

### foley.sources.media.MEDIA_INPUTS *= ('video', 'audio')*

The affordances of [`MEDIA`](#foley.sources.media.MEDIA).

### *class* foley.sources.media.MediaInput(name, mode, does, covers, suffix_of, seconds_of)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One media input of generation (a row of [`MEDIA`](#foley.sources.media.MEDIA)): the affordance that
carries it, the mode it puts a call in, and how foley reads it.

#### name

The affordance (`video`, `audio`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### mode

The generation mode a call given it is in (`v2a`, `edit`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### does

What a source taking it does (said when it is missing).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### covers

How a `duration_s` set to its length is noted.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### suffix_of

The sniffer of its bytes’ file suffix, as `'<module>.<name>'` in
[`foley.sources`](foley.sources.html.md#module-foley.sources).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### seconds_of

The probe of its length, likewise. Both are looked up when
called, so a test can stand in for the probe.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* needed *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

What a source taking it says when a call lacks it.

```pycon
>>> MEDIA["audio"].needed
'needs an audio= (it edits a source clip)'
```

#### seconds(value)

Its length in seconds, or `None` (a URL, an unreadable input).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### suffix(data)

The file suffix its `data` is uploaded under (sniffed from its first bytes).

```pycon
>>> MEDIA["audio"].suffix(b"fLaC\x00"), MEDIA["video"].suffix(b"?")
('.flac', '.mp4')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.media.MediaValue

a URL, a [`RemoteVideo`](#foley.sources.media.RemoteVideo), a local path, or the bytes.

* **Type:**
  What a media input accepts

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`RemoteVideo`](#foley.sources.media.RemoteVideo) | `os.PathLike[str]` | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.sources.media.REDACTED_QUERY *= '?…'*

What stands in for a recorded URL’s query and fragment.

### foley.sources.media.REMOTE_SCHEMES *= ('http://', 'https://')*

Schemes of a URL the backend fetches from a server (what it serves may change).

### *class* foley.sources.media.RemoteVideo(, url, sha256)

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

### foley.sources.media.URL_KEY_PREFIX *= 'url:'*

The key prefix of a media input known only by its URL (its content unseen).

### foley.sources.media.URL_SCHEMES *= ('http://', 'https://', 'data:')*

URL schemes sent to a backend as is (no upload); a `data:` URI holds its content.

### foley.sources.media.audio_seconds(audio)

The length of an audio input (bytes or a local path) in seconds, or `None`.

`None` for a URL (not fetched), without `soundfile`, or when it cannot be read.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.media.audio_suffix(data)

The file suffix of encoded audio `data` (flac, wav, mp3, ogg), sniffed from its first bytes.

Anything unrecognised is [`DEFAULT_AUDIO_SUFFIX`](#foley.sources.media.DEFAULT_AUDIO_SUFFIX).

```pycon
>>> audio_suffix(b"fLaC\x00"), audio_suffix(b"RIFF\x00\x00\x00\x00WAVEfmt ")
('.flac', '.wav')
>>> audio_suffix(b"ID3\x04"), audio_suffix(b"\xff\xfb\x90"), audio_suffix(b"OggS")
('.mp3', '.mp3', '.ogg')
>>> audio_suffix(b"?")
'.wav'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.media.fal_immutable_url(url)

falaw’s `is_immutable_url` (fal’s own CDN mints a new URL per upload), else
`False` when falaw is not installed: an unknown URL is taken as mutable.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.media.is_media_key(value)

Whether `value` is already a key [`media_key()`](#foley.sources.media.media_key) makes (as a cache entry keeps it).

```pycon
>>> is_media_key("sha256:" + "ab" * 32), is_media_key("url:https://x/a.mp4")
(True, True)
>>> is_media_key("clip.mp4"), is_media_key(b"sha256:")
(False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.media.is_url(media)

Whether `media` is a URL a backend can fetch itself.

```pycon
>>> is_url("https://x/clip.mp4"), is_url("clip.mp4"), is_url(b"...")
(True, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.media.keyed(affordances, \*, key=<function recorded_media_key>)

`affordances` with each media input ([`MEDIA_INPUTS`](#foley.sources.media.MEDIA_INPUTS)) replaced by its `key`.

The default is the key as it is written down ([`recorded_media_key()`](#foley.sources.media.recorded_media_key)); the
request digest passes `key=media_key`, the full identity, which is only hashed.
Unchanged when the call has no media input.

```pycon
>>> keyed({"video": b"abc", "duration_s": 2})["video"][:15], keyed({"seed": 1})
('sha256:ba7816bf', {'seed': 1})
>>> keyed({"audio": b"abc"})["audio"] == keyed({"video": b"abc"})["video"]
True
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.media.local_media_file(media, , suffix=None)

A local path holding `media` (bytes are written to a temporary file).

`suffix` names the temporary file’s format; default: [`video_suffix()`](#foley.sources.media.video_suffix) of the
bytes. A path is yielded as is.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.media.media_key(media)

The cache identity of `media`: its content digest, or a bare remote URL as is.

```pycon
>>> media_key(b"abc")[:15]
'sha256:ba7816bf'
>>> media_key("https://x/clip.mp4")
'url:https://x/clip.mp4'
>>> media_key(RemoteVideo(url="https://x/clip.mp4", sha256="ab" * 32))[:11]
'sha256:abab'
```

* **Raises:**
  * [**FileNotFoundError**](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) – If `media` names a local file that does not exist.
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If `media` is none of a URL, a path or bytes.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.media.media_url(media)

The URL a backend fetches `media` from itself, or `None` (a path or bytes).

```pycon
>>> media_url("https://x/clip.mp4"), media_url("clip.mp4"), media_url(b"...")
('https://x/clip.mp4', None, None)
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.media.recorded_media_key(media)

[`media_key()`](#foley.sources.media.media_key) as it is written down: a bare URL keeps its scheme, host and
path only (#184): its query, fragment and `;` path parameters (a presigned URL’s
signature, a session id) become [`REDACTED_QUERY`](#foley.sources.media.REDACTED_QUERY), and credentials before
the host are dropped. Two URLs that differ only there record (and are found by
[`find()`](foley.stores.html.md#foley.stores.GenerationsCache.find)) as one, as a re-signed URL should.
An already recorded or bare `url:` key is redacted the same way.

```pycon
>>> recorded_media_key("https://u:p@bucket.s3.example/a.mp4?X-Amz-Signature=s3cr3t")
'url:https://bucket.s3.example/a.mp4?…'
>>> recorded_media_key("https://[::1]:8080/a.mp4;jsessionid=X#t=2")
'url:https://[::1]:8080/a.mp4?…'
>>> recorded_media_key("https://x/a.mp4"), recorded_media_key(b"abc")[:11]
('url:https://x/a.mp4', 'sha256:ba78')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.media.remote_media_input(affordances)

The name of the first media input given as a bare remote URL, or `None`.

```pycon
>>> remote_media_input({"audio": "https://x/a.wav"}), remote_media_input({"video": b"x"})
('audio', None)
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.media.replayable(affordances, \*, is_immutable=<function fal_immutable_url>)

Whether an identical request may be served from the cache (#173).

Not when a media input ([`MEDIA_INPUTS`](#foley.sources.media.MEDIA_INPUTS)) is a bare remote URL whose content
foley never saw, unless `is_immutable(url)` says it never serves other bytes
(default: [`fal_immutable_url()`](#foley.sources.media.fal_immutable_url), fal’s own CDN). Decided from the values
alone: no file is read.

```pycon
>>> replayable({"video": "https://x/latest.mp4"}), replayable({"video": b"abc"})
(False, True)
>>> replayable({"video": "https://x/a.mp4"}, is_immutable=lambda url: True)
True
>>> replayable({"seed": 1}), replayable({"audio": "https://x/take.wav"})
(True, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.media.video_suffix(data)

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
