# foley.sources.music_library

Acquire a licensed music library, with provenance: verified files, a tracks table, attribution.

A production that scores itself from free libraries writes the same script each
time: turn the titles a channel credits into download URLs, fetch them politely,
check each file is audio, record where it came from and under which licence, and
collect the attribution lines the licence asks for. [`acquire()`](#foley.sources.music_library.acquire) is that script:

```default
from foley.sources.music_library import acquire, attribution_text, tracks_table

rows = acquire("incompetech", ["Sneaky Snitch"], out="audio/macleod")
open("audio/macleod/tracks.csv", "w").write(tracks_table(rows))
print(attribution_text(rows))
```

- **A library is data** ([`MusicLibrary`](#foley.sources.music_library.MusicLibrary), `MUSIC_LIBRARIES`,
  [`register_music_library()`](#foley.sources.music_library.register_music_library)): `incompetech` (Kevin MacLeod, CC BY 4.0) and
  > the paid `artlist` and `epidemic_sound`, whose titles become wishlist rows.
- **Licences come from foley’s SSOT**: each row’s
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) is built from the library’s licence URL by
  [`foley.licensing.license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url) ([`track_license()`](#foley.sources.music_library.track_license)) and gated
  > by [`foley.licensing.refusal_reason()`](foley.licensing.html.md#foley.licensing.refusal_reason) for `acquire`’s `intended_use`
  > (default: commercial publishing) before anything is fetched; a refused title is a
  > `refused` row. A paid library claims no rights.
- **Fetching is foley’s**: a [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) wrapped per host
  by [`foley.sources.resilience.resilient()`](foley.sources.resilience.html.md#foley.sources.resilience.resilient) (pace, `429` / `Retry-After`,
  breaker), with the library’s own server then the Internet Archive’s raw copy as
  mirrors ([`direct()`](#foley.sources.music_library.direct), [`wayback()`](#foley.sources.music_library.wayback)); [`probe_verify()`](#foley.sources.music_library.probe_verify) checks each file
  has an audio stream and a length, with foley’s media probes.
- **Rows are portable** ([`AcquiredTrack`](#foley.sources.music_library.AcquiredTrack)): `.row()` is flat and JSON-safe,
  [`tracks_table()`](#foley.sources.music_library.tracks_table) writes them as CSV and [`kept_digests()`](#foley.sources.music_library.kept_digests) (or
  [`kept_sources()`](#foley.sources.music_library.kept_sources), with each file’s URL) reads a table back, so a rerun fetches
  > only what it lacks.
- **Each free library is also a live retrieve source** of its own name (#212):
  `foley.add_from("incompetech", query="Sneaky Snitch")` (a title, a list of
  titles, or a credits description) puts each title through the licence gate
  under the call’s intent and [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one), giving
  by-value [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) rows with their attribution, and a run
  manifest. The config is built from the library ([`library_source_config()`](#foley.sources.music_library.library_source_config),
  declared as the callable `config.SOURCE_CONFIGS`, so a library registered at
  runtime is a source on the next discovery); the adapter
  ([`MusicLibraryAdapter`](foley.sources.music_library.adapter.html.md#foley.sources.music_library.adapter.MusicLibraryAdapter)) runs the same
  mirror chain and `verify` as [`acquire()`](#foley.sources.music_library.acquire). A paid library is not a source.

Stdlib only at import; `requests` loads on the first real download.

```pycon
>>> lib = MUSIC_LIBRARIES["incompetech"]
>>> lib.track_url("Sneaky Snitch")
'https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3'
>>> track_license(lib, "Sneaky Snitch").license_id
'CC-BY-4.0'
```

### Functions

| [`acquire`](#foley.sources.music_library.acquire)(library, titles, \*, out[, fetch, ...])    | Download `titles` of `library` into `out`, verified, one row each.                                                                                                                                                                                                                |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`attribution_text`](#foley.sources.music_library.attribution_text)(rows)                             | The attribution blocks to paste under a video, one per track that has one (acquired or kept), blank-line separated, each once.                                                                                                                                                    |
| [`direct`](#foley.sources.music_library.direct)(url)                                        | The URL itself: the library's own server.                                                                                                                                                                                                                                         |
| [`fetch_audio`](#foley.sources.music_library.fetch_audio)(url, \*, http[, config])               | `url`'s bytes, asked for with the config's user agent.                                                                                                                                                                                                                            |
| [`files_store`](#foley.sources.music_library.files_store)(out)                                   | `out` as a `{file name: bytes}` store: a mapping is used as it is; a folder becomes foley's file store over it ([`foley.stores.make_byte_store()`](foley.stores.html.md#foley.stores.make_byte_store), which makes the folder on its first write).         |
| [`kept_digests`](#foley.sources.music_library.kept_digests)(table)                                | `{file: sha256}` of the acquired or kept rows of a tracks table: what a rerun may keep.                                                                                                                                                                                           |
| [`kept_sources`](#foley.sources.music_library.kept_sources)(table)                                | `{file: {"sha256", "url", "mirror"}}` of the acquired or kept rows of a tracks table: [`kept_digests()`](#foley.sources.music_library.kept_digests) with where each file came from, so a kept row still says which URL and mirror served it (`acquire(kept=...)` takes either). |
| [`library_source_config`](#foley.sources.music_library.library_source_config)(library)                     | The `SOURCE_CONFIG` of the free `library`.                                                                                                                                                                                                                                        |
| [`make_fetch`](#foley.sources.music_library.make_fetch)(\*[, transport, config, clock, sleep])  | The default `url -> bytes`: [`fetch_audio()`](#foley.sources.music_library.fetch_audio) over [`polite_transport()`](#foley.sources.music_library.polite_transport) (`config` laid over `MUSIC_LIBRARY_HTTP`).                                                                    |
| [`mirror_name`](#foley.sources.music_library.mirror_name)(mirror)                                | The name a row records for `mirror` (its function name).                                                                                                                                                                                                                          |
| [`music_library`](#foley.sources.music_library.music_library)(library, \*[, libraries])            | `library` itself, or the registered library of that name.                                                                                                                                                                                                                         |
| [`music_library_config`](#foley.sources.music_library.music_library_config)([config])                     | `config` laid over `MUSIC_LIBRARY_HTTP` (top-level keys: a `retry` or `rate` given replaces the default one whole).                                                                                                                                                               |
| [`polite_transport`](#foley.sources.music_library.polite_transport)([transport, config, clock, ...])  | `transport` (default [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)) with a resilient wrapper per host, built from `config` (see the module docstring).                                                              |
| [`probe_available`](#foley.sources.music_library.probe_available)()                                  | Whether [`probe_verify()`](#foley.sources.music_library.probe_verify)'s probes can run here: `ffprobe` on `PATH`, or both mixing's video probe with an `ffmpeg` (the length) and `soundfile` (the audio stream).                                                                |
| [`probe_verify`](#foley.sources.music_library.probe_verify)(data, \*[, probe, has_audio, suffix]) | The duration of the audio `data`, in seconds.                                                                                                                                                                                                                                     |
| [`register_music_library`](#foley.sources.music_library.register_music_library)(library, \*[, replace])     | Add `library` to `MUSIC_LIBRARIES` (`replace` to redefine one).                                                                                                                                                                                                                   |
| [`require_probe`](#foley.sources.music_library.require_probe)()                                    | Raise [`MusicToolMissing`](#foley.sources.music_library.MusicToolMissing) unless [`probe_available()`](#foley.sources.music_library.probe_available).                                                                                                                                |
| [`safe_file_name`](#foley.sources.music_library.safe_file_name)(title, \*[, suffix])                | `title` as a file name: NFC, path separators as `-`, no leading dot.                                                                                                                                                                                                              |
| [`title_url`](#foley.sources.music_library.title_url)(template)                                | The `title -> URL` rule that puts the URL-quoted title in `template`'s `{title}`.                                                                                                                                                                                                 |
| [`titles_by_library`](#foley.sources.music_library.titles_by_library)(description, \*[, libraries])    | The titles a video description credits, by library (default: the registered ones).                                                                                                                                                                                                |
| [`titles_from_json`](#foley.sources.music_library.titles_from_json)(text)                             | A titles file's JSON: a list of titles, or `{title: {metadata}}`.                                                                                                                                                                                                                 |
| [`track_license`](#foley.sources.music_library.track_license)(library, title, \*[, page_url, ...]) | The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) of `title` from `library`.                                                                                                                                                            |
| [`tracks_table`](#foley.sources.music_library.tracks_table)(rows)                                 | The tracks table as CSV text: `TRACK_COLUMNS`, then any metadata the rows carry, in name order.                                                                                                                                                                                   |
| [`wayback`](#foley.sources.music_library.wayback)(url)                                       | The Internet Archive's raw copy of `url` (`WAYBACK_RAW`).                                                                                                                                                                                                                         |

### Classes

| `MusicLibraryAdapter`([config, http, verify, ...])                                              | One free music library as a retrieve source (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)).   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`AcquiredTrack`](#foley.sources.music_library.AcquiredTrack)(title, library, status, license) | One row of the tracks table: a title, what became of it, and its provenance.                                                                       |
| [`MusicLibrary`](#foley.sources.music_library.MusicLibrary)(name, author[, license_url, ...]) | One library: who made it, under which licence, and where a title's file is.                                                                        |

### Exceptions

| [`MusicLibraryError`](#foley.sources.music_library.MusicLibraryError)   | A library, a title or a file that cannot be used, and why.             |
|----------------------------------------------------------------------|------------------------------------------------------------------------|
| [`MusicToolMissing`](#foley.sources.music_library.MusicToolMissing)    | A tool every title needs is missing: the batch stops before it starts. |

### *class* foley.sources.music_library.AcquiredTrack(title, library, status, license, file=None, sha256=None, duration_s=None, url=None, mirror=None, page_url=None, credited_by=(), metadata=dict(), error=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One row of the tracks table: a title, what became of it, and its provenance.

`url` is the URL that served the bytes (a mirror’s), `mirror` that mirror’s
name, `page_url` the library’s own address for the title; `credited_by` the
videos that credit it and `metadata` a titles file’s other fields (`feel`,
`genre`, …).

#### row()

The row as the tracks table writes it: flat and JSON-safe (a list joined
by 

```
``
```

; 

```
``
```

, a mapping as JSON).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *class* foley.sources.music_library.MusicLibrary(name, author, license_url=None, track_url=None, attribution='"{title}" {author}', author_url=None, aliases=(), file_name=<function safe_file_name>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One library: who made it, under which licence, and where a title’s file is.

`license_url` is the URL of its Creative Commons licence, read by
[`license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url); `None` makes the library
PAID (its titles become wishlist rows, never downloads; `track_url` is then
unused). `track_url` is the `title -> URL` rule ([`title_url()`](#foley.sources.music_library.title_url) builds one
from a template). `attribution` is a template over `{title}`, `{author}`
and `{license_url}`. `aliases` are the names a video description credits it
by (`From Epidemic Sound:`, `Kevin MacLeod (incompetech.com)`);
`file_name` the name a title is saved under.

#### attribution_for(title)

The library’s attribution for `title`, from its template.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### file_name(, suffix='.mp3')

`title` as a file name: NFC, path separators as `-`, no leading dot.

```pycon
>>> safe_file_name("AC/DC"), safe_file_name("../../escape")
('AC-DC.mp3', '-..-escape.mp3')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* license_id *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The foley licence id its licence URL maps to (`'unknown'` when paid).

#### *property* paid *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the library has no free licence (wishlist rows only).

#### *property* rights_verified *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether foley recognises the licence outright (never for a paid library).

### *exception* foley.sources.music_library.MusicLibraryError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A library, a title or a file that cannot be used, and why.

### *exception* foley.sources.music_library.MusicToolMissing

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

A tool every title needs is missing: the batch stops before it starts.

### foley.sources.music_library.acquire(library, titles, \*, out, fetch=None, transport=None, mirrors=(<function direct>, <function wayback>), verify=<function probe_verify>, kept=None, intended_use=IntendedUse(commercial=True, publish=True, redistribute_standalone=False, will_train=False, can_attribute=True, revenue_usd=0, allow_voice_or_trademark=False, territory=None), libraries=None, config=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

Download `titles` of `library` into `out`, verified, one row each.

`titles` is a list, or `{title: metadata}` whose metadata (`credited_by`:
the videos that credit it; a catalogue’s `feel`, `genre`, …) rides on the
row. `library` is a [`MusicLibrary`](#foley.sources.music_library.MusicLibrary) or a name in `libraries` (default
[`MUSIC_LIBRARIES`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MUSIC_LIBRARIES)).

Each title’s licence is put through [`foley.licensing.refusal_reason()`](foley.licensing.html.md#foley.licensing.refusal_reason) for
`intended_use` first (fail-closed: an error in the gate is a refusal); a
refused title is a `refused` row and is not fetched. The others are fetched
from each of `mirrors` in turn until one gives bytes `verify` accepts.
`fetch` (`url -> bytes`) replaces the HTTP path, paced per host by the
config’s `rate`; otherwise the files come through `transport` (default:
`requests`) wrapped by foley’s resilience layer per host; that path honours
[`foley.offline()`](foley.html.md#foley.offline). `config` is laid over
[`MUSIC_LIBRARY_HTTP`](foley.sources.music_library.fetch.html.md#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP); `clock` /
`sleep` time the waits. `kept` is `{file name: sha256}` a previous run
recorded ([`kept_digests()`](#foley.sources.music_library.kept_digests)), or `{file name: {"sha256", "url", "mirror"}}`
([`kept_sources()`](#foley.sources.music_library.kept_sources), whose `url` and `mirror` the kept row keeps): a file in
`out` with that digest is kept, any other is fetched again. A paid library
downloads nothing and returns wishlist rows.

* **Raises:**
  * [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – For an unknown library, titles of the wrong shape,
        metadata that restates the row, two titles saved as one file, or a
        `kept` value that is neither a digest nor a mapping with one.
  * [**MusicToolMissing**](#foley.sources.music_library.MusicToolMissing) – When `verify` is the default and no probe can run
        (before anything is downloaded).
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – When both `fetch` and `transport` are given.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`AcquiredTrack`](foley.sources.music_library.acquisition.html.md#foley.sources.music_library.acquisition.AcquiredTrack)]

### foley.sources.music_library.attribution_text(rows)

The attribution blocks to paste under a video, one per track that has one
(acquired or kept), blank-line separated, each once.

Each block is [`foley.provenance.credits.attribution_line()`](foley.provenance.credits.html.md#foley.provenance.credits.attribution_line) of the row’s
licence: the library’s own wording, verbatim.

```pycon
>>> from foley.sources.music_library import MUSIC_LIBRARIES, track_license
>>> lic = track_license(MUSIC_LIBRARIES["incompetech"], "A")
>>> print(attribution_text([AcquiredTrack("A", "incompetech", ACQUIRED, lic)] * 2))
"A" Kevin MacLeod (incompetech.com)
Licensed under Creative Commons: By Attribution 4.0 License
http://creativecommons.org/licenses/by/4.0/
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.direct(url)

The URL itself: the library’s own server.

```pycon
>>> direct("https://example.org/a.mp3")
'https://example.org/a.mp3'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.fetch_audio(url, , http, config=None)

`url`’s bytes, asked for with the config’s user agent.

A body over `max_bytes` is refused by its declared `Content-Length` before
`resp.content` is touched, and by its length after (a server may declare none,
or lie). foley’s [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) returns a whole response,
so with [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport) the body is already in
memory when the header is read: the header check spares the copy, not the
download. A streaming transport, which would stop at `max_bytes`, is a
follow-up.

* **Raises:**
  [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – On a non-200 answer, a `text/*` page (an error page
      served with 200), a body over `config['max_bytes']`, or one shorter
      than its declared `Content-Length` (a cut download, which a probe of
      its header alone would still accept).
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.sources.music_library.files_store(out)

`out` as a `{file name: bytes}` store: a mapping is used as it is; a folder
becomes foley’s file store over it ([`foley.stores.make_byte_store()`](foley.stores.html.md#foley.stores.make_byte_store), which
makes the folder on its first write).

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### foley.sources.music_library.kept_digests(table)

`{file: sha256}` of the acquired or kept rows of a tracks table: what a rerun
may keep. `table` is [`tracks_table()`](#foley.sources.music_library.tracks_table)’s CSV text, or the rows themselves
([`AcquiredTrack`](#foley.sources.music_library.AcquiredTrack) or their [`row()`](#foley.sources.music_library.AcquiredTrack.row) dicts, read back
from JSON).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.music_library.kept_sources(table)

`{file: {"sha256", "url", "mirror"}}` of the acquired or kept rows of a
tracks table: [`kept_digests()`](#foley.sources.music_library.kept_digests) with where each file came from, so a kept row
still says which URL and mirror served it (`acquire(kept=...)` takes either).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### foley.sources.music_library.library_source_config(library)

The `SOURCE_CONFIG` of the free `library`.

* **Raises:**
  [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – If `library` is paid (a paid library is not a source).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.music_library.make_fetch(\*, transport=None, config=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

The default `url -> bytes`: [`fetch_audio()`](#foley.sources.music_library.fetch_audio) over [`polite_transport()`](#foley.sources.music_library.polite_transport)
(`config` laid over `MUSIC_LIBRARY_HTTP`).

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### foley.sources.music_library.mirror_name(mirror)

The name a row records for `mirror` (its function name).

```pycon
>>> mirror_name(wayback)
'wayback'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.music_library(library, , libraries=None)

`library` itself, or the registered library of that name.

* **Raises:**
  [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – If no library of that name is registered (naming those that are).
* **Return type:**
  [`MusicLibrary`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MusicLibrary)

### foley.sources.music_library.music_library_config(config=None)

`config` laid over `MUSIC_LIBRARY_HTTP` (top-level keys: a `retry`
or `rate` given replaces the default one whole).

```pycon
>>> music_library_config({"rate": {"per_min": 6}})["rate"], music_library_config()["max_bytes"]
({'per_min': 6}, 67108864)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.music_library.polite_transport(transport=None, \*, config=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

`transport` (default [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)) with a
resilient wrapper per host, built from `config` (see the module docstring).

Left unwrapped when the active runtime turns `http_resilience` off.

* **Return type:**
  [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)

### foley.sources.music_library.probe_available()

Whether [`probe_verify()`](#foley.sources.music_library.probe_verify)’s probes can run here: `ffprobe` on `PATH`, or
both mixing’s video probe with an `ffmpeg` (the length) and `soundfile` (the
audio stream).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.music_library.probe_verify(data, , probe=None, has_audio=None, suffix='.mp3')

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
  [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – When the file is empty, has no audio stream (or one
      cannot be confirmed), or has no readable duration.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.sources.music_library.register_music_library(library, , replace=False)

Add `library` to `MUSIC_LIBRARIES` (`replace` to redefine one).

A free library is checked for one licence right only, keeping the files
(`cache_bytes_ok`); the uses a production makes of them are gated per title by
[`acquire()`](#foley.sources.music_library.acquire) (`intended_use`).

A library’s name is also its live-source name (`foley.add_from(name, ...)`),
so it may not be the name of a source another [`foley.sources`](foley.sources.html.md#module-foley.sources) module
declares, or one registered directly (`openverse`, `freesound`, a `fal_*`
endpoint, …): that library would silently take the source over, or silently
never become one.

* **Raises:**
  * [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – If the name is taken (and not `replace`), or a free
        library has no `track_url` rule or a licence that does not allow
        keeping the files (a ShareAlike / NoDerivatives licence, refused on
        purpose; a licence URL foley cannot read; a licence whose flags say no).
  * [**SourceNameCollision**](foley.sources.registry.html.md#foley.sources.registry.SourceNameCollision) – If the name is another module’s source name.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.music_library.require_probe()

Raise [`MusicToolMissing`](#foley.sources.music_library.MusicToolMissing) unless [`probe_available()`](#foley.sources.music_library.probe_available).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.music_library.safe_file_name(title, , suffix='.mp3')

`title` as a file name: NFC, path separators as `-`, no leading dot.

```pycon
>>> safe_file_name("AC/DC"), safe_file_name("../../escape")
('AC-DC.mp3', '-..-escape.mp3')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.title_url(template)

The `title -> URL` rule that puts the URL-quoted title in `template`’s `{title}`.

```pycon
>>> title_url("https://x.org/music/{title}.mp3")("Night Owl")
'https://x.org/music/Night%20Owl.mp3'
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.music_library.titles_by_library(description, , libraries=None)

The titles a video description credits, by library (default: the registered ones).

A line naming a library (by name or alias, with `From`/`Music by`/
`Music:` and a parenthetical allowed around it) opens its block, and each
following line is a title until a blank line; a timestamp, a
`Song:`/`Track:` label, quotes and bullets are stripped, and links and
licence lines skipped. The attribution form (`"Title" Kevin MacLeod
(incompetech.com)`) credits its title wherever it stands.

```pycon
>>> text = '''Music:
... From Epidemic Sound:
... - 0:00 Night Owl
... - Song: "Morning Light"
... https://www.epidemicsound.com/
...
... "Sneaky Snitch" Kevin MacLeod (incompetech.com)
... Licensed under Creative Commons: By Attribution 4.0 License'''
>>> titles_by_library(text)
{'epidemic_sound': ['Night Owl', 'Morning Light'], 'incompetech': ['Sneaky Snitch']}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.sources.music_library.titles_from_json(text)

A titles file’s JSON: a list of titles, or `{title: {metadata}}`.

```pycon
>>> titles_from_json('["A", "B"]'), titles_from_json('{"A": {"feel": "Bright"}}')
(['A', 'B'], {'A': {'feel': 'Bright'}})
```

* **Raises:**
  [**MusicLibraryError**](#foley.sources.music_library.MusicLibraryError) – If `text` is not JSON, or not one of those two shapes.
* **Return type:**
  [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]]

### foley.sources.music_library.track_license(library, title, , page_url=None, sha256=None)

The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) of `title` from `library`.

A free library’s record carries the id [`license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url)
reads from its licence URL, the flags derived from it (`requires_attribution`
among them), `rights_verified` only where that id is verified, and the
library’s attribution for the title. A paid library’s claims nothing:
`'unknown'`, every flag closed, no attribution.

```pycon
>>> rec = track_license(MUSIC_LIBRARIES["incompetech"], "A")
>>> rec.license_id, rec.requires_attribution, rec.commercial_ok, rec.rights_verified
('CC-BY-4.0', True, True, True)
>>> rec = track_license(MUSIC_LIBRARIES["artlist"], "A")
>>> rec.license_id, rec.commercial_ok, rec.rights_verified, rec.attribution_text
('unknown', False, False, None)
```

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.sources.music_library.tracks_table(rows)

The tracks table as CSV text: `TRACK_COLUMNS`, then any metadata the
rows carry, in name order.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.wayback(url)

The Internet Archive’s raw copy of `url` (`WAYBACK_RAW`).

```pycon
>>> wayback("https://example.org/a.mp3")
'https://web.archive.org/web/2id_/https://example.org/a.mp3'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### Modules

| [`acquisition`](foley.sources.music_library.acquisition.html.md#module-foley.sources.music_library.acquisition)     | Acquire a music library's titles: verified files, one provenance row each, a resumable table.   |
|-----------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| [`adapter`](foley.sources.music_library.adapter.html.md#module-foley.sources.music_library.adapter)             | A free music library as a live retrieve source: titles in, licensed tracks out (#212).          |
| [`config`](foley.sources.music_library.config.html.md#module-foley.sources.music_library.config)               | `SOURCE_CONFIGS` for the music libraries: one retrieve source per free library (#212).          |
| [`credit_parser`](foley.sources.music_library.credit_parser.html.md#module-foley.sources.music_library.credit_parser) | Which titles a video credits, by library: the credit-block parser and the titles file.          |
| [`fetch`](foley.sources.music_library.fetch.html.md#module-foley.sources.music_library.fetch)                 | Fetching a library's files politely, through foley's transport and its resilience layer.        |
| [`libraries`](foley.sources.music_library.libraries.html.md#module-foley.sources.music_library.libraries)         | Music libraries as data: who made one, its licence, its credit, where a title's file is.        |
| [`mirrors`](foley.sources.music_library.mirrors.html.md#module-foley.sources.music_library.mirrors)             | Where else a track's bytes may be: the library's own server, then the Internet Archive.         |
| [`verify`](foley.sources.music_library.verify.html.md#module-foley.sources.music_library.verify)               | Checking a downloaded file is audio: an audio stream and a duration, read by foley's probes.    |
