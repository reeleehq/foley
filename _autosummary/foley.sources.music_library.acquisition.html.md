# foley.sources.music_library.acquisition

Acquire a music library’s titles: verified files, one provenance row each, a resumable table.

[`acquire()`](#foley.sources.music_library.acquisition.acquire) turns titles into download URLs (the library’s rule), fetches each
from the first of its `mirrors` whose bytes `verify` accepts, writes the file to
`out` and returns one [`AcquiredTrack`](#foley.sources.music_library.acquisition.AcquiredTrack) per title. Every step is a seam
(keyword arguments with working defaults):

- `fetch` (`url -> bytes`) or `transport` (a foley
  [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)): by default the fetch goes through
  [`make_fetch()`](foley.sources.music_library.fetch.html.md#foley.sources.music_library.fetch.make_fetch) (the resilience layer per
  > host: pace, `429` / `Retry-After`, breaker); a `fetch` of the caller’s own is
  > paced per host too ([`pace_per_host()`](foley.sources.resilience.html.md#foley.sources.resilience.pace_per_host), from the
  > config’s `rate`). `clock` / `sleep` time both;
- `mirrors`: [`direct()`](foley.sources.music_library.mirrors.html.md#foley.sources.music_library.mirrors.direct), then
  [`wayback()`](foley.sources.music_library.mirrors.html.md#foley.sources.music_library.mirrors.wayback);
- `verify` (`bytes -> seconds`):
  [`probe_verify()`](foley.sources.music_library.verify.html.md#foley.sources.music_library.verify.probe_verify);
- `out`: any `{file name: bytes}` store, a folder by default;
- `intended_use`: the [`IntendedUse`](foley.base.html.md#foley.base.IntendedUse) each title’s licence must
  allow (default [`foley.licensing.DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE): commercial
  publishing).

A row’s licence is a [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
([`track_license()`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.track_license)), put through foley’s
fail-closed gate ([`foley.licensing.refusal_reason()`](foley.licensing.html.md#foley.licensing.refusal_reason)) before anything is
fetched: a title it refuses is a `refused` row, with the reason, and is not
downloaded. `url` is where the bytes came from (the mirror that served them),
`page_url` the library’s own address. A title that fails is a `failed` row with
its reasons; the batch goes on. A file whose digest a previous run recorded
(`kept`, from [`kept_digests()`](#foley.sources.music_library.acquisition.kept_digests) or [`kept_sources()`](#foley.sources.music_library.acquisition.kept_sources)) is not fetched again,
so a rerun resumes. A paid library fetches nothing: its rows are `wishlist` rows.

[`AcquiredTrack.row()`](#foley.sources.music_library.acquisition.AcquiredTrack.row) is a flat, JSON-safe dict (a caller such as `an` bridges
it into its own asset rows without foley knowing it); [`tracks_table()`](#foley.sources.music_library.acquisition.tracks_table) is those
rows as CSV, and [`attribution_text()`](#foley.sources.music_library.acquisition.attribution_text) the blocks to paste under a video.

### Module Attributes

| [`ACQUIRED`](#foley.sources.music_library.acquisition.ACQUIRED)          | the licence gate refused the title for the intended use (nothing fetched); `wishlist`: a paid library's title.                                                              |
|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`KEPT`](#foley.sources.music_library.acquisition.KEPT)              | the licence gate refused the title for the intended use (nothing fetched); `wishlist`: a paid library's title.                                                              |
| [`FAILED`](#foley.sources.music_library.acquisition.FAILED)            | the licence gate refused the title for the intended use (nothing fetched); `wishlist`: a paid library's title.                                                              |
| [`REFUSED`](#foley.sources.music_library.acquisition.REFUSED)           | the licence gate refused the title for the intended use (nothing fetched); `wishlist`: a paid library's title.                                                              |
| [`WISHLIST`](#foley.sources.music_library.acquisition.WISHLIST)          | the licence gate refused the title for the intended use (nothing fetched); `wishlist`: a paid library's title.                                                              |
| [`HELD`](#foley.sources.music_library.acquisition.HELD)              | The statuses whose file is in `out` (what a rerun may keep, what is credited).                                                                                              |
| [`TRACK_COLUMNS`](#foley.sources.music_library.acquisition.TRACK_COLUMNS)     | The tracks table's columns, in order (a row's other metadata, a catalogue's `feel` or `genre`, follows in name order).                                                      |
| [`METADATA_COLUMNS`](#foley.sources.music_library.acquisition.METADATA_COLUMNS)  | The metadata keys a titles file may set that are columns (the rest the library states).                                                                                     |
| [`DURATION_DECIMALS`](#foley.sources.music_library.acquisition.DURATION_DECIMALS) | Decimal places a duration is written with.                                                                                                                                  |
| [`Kept`](#foley.sources.music_library.acquisition.Kept)              | a file's recorded sha256, or `{"sha256", "url", "mirror"}` ([`kept_sources()`](#foley.sources.music_library.acquisition.kept_sources)), whose `url` / `mirror` a kept row carries on. |

### Functions

| [`acquire`](#foley.sources.music_library.acquisition.acquire)(library, titles, \*, out[, fetch, ...])   | Download `titles` of `library` into `out`, verified, one row each.                                                                                                                                                                                                                |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`attribution_text`](#foley.sources.music_library.acquisition.attribution_text)(rows)                            | The attribution blocks to paste under a video, one per track that has one (acquired or kept), blank-line separated, each once.                                                                                                                                                    |
| [`files_store`](#foley.sources.music_library.acquisition.files_store)(out)                                  | `out` as a `{file name: bytes}` store: a mapping is used as it is; a folder becomes foley's file store over it ([`foley.stores.make_byte_store()`](foley.stores.html.md#foley.stores.make_byte_store), which makes the folder on its first write).         |
| [`kept_digests`](#foley.sources.music_library.acquisition.kept_digests)(table)                               | `{file: sha256}` of the acquired or kept rows of a tracks table: what a rerun may keep.                                                                                                                                                                                           |
| [`kept_sources`](#foley.sources.music_library.acquisition.kept_sources)(table)                               | `{file: {"sha256", "url", "mirror"}}` of the acquired or kept rows of a tracks table: [`kept_digests()`](#foley.sources.music_library.acquisition.kept_digests) with where each file came from, so a kept row still says which URL and mirror served it (`acquire(kept=...)` takes either). |
| [`tracks_table`](#foley.sources.music_library.acquisition.tracks_table)(rows)                                | The tracks table as CSV text: [`TRACK_COLUMNS`](#foley.sources.music_library.acquisition.TRACK_COLUMNS), then any metadata the rows carry, in name order.                                                                                                                                    |

### Classes

| [`AcquiredTrack`](#foley.sources.music_library.acquisition.AcquiredTrack)(title, library, status, license)   | One row of the tracks table: a title, what became of it, and its provenance.   |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|

### foley.sources.music_library.acquisition.ACQUIRED *= 'acquired'*

the licence gate refused the title for the
intended use (nothing fetched); `wishlist`: a paid library’s title.

* **Type:**
  The row statuses. `refused`

### *class* foley.sources.music_library.acquisition.AcquiredTrack(title, library, status, license, file=None, sha256=None, duration_s=None, url=None, mirror=None, page_url=None, credited_by=(), metadata=dict(), error=None)

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

### foley.sources.music_library.acquisition.DURATION_DECIMALS *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 3*

Decimal places a duration is written with.

### foley.sources.music_library.acquisition.FAILED *= 'failed'*

the licence gate refused the title for the
intended use (nothing fetched); `wishlist`: a paid library’s title.

* **Type:**
  The row statuses. `refused`

### foley.sources.music_library.acquisition.HELD *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('acquired', 'kept')*

The statuses whose file is in `out` (what a rerun may keep, what is credited).

### foley.sources.music_library.acquisition.KEPT *= 'kept'*

the licence gate refused the title for the
intended use (nothing fetched); `wishlist`: a paid library’s title.

* **Type:**
  The row statuses. `refused`

### foley.sources.music_library.acquisition.Kept

a file’s recorded sha256, or `{"sha256", "url", "mirror"}`
([`kept_sources()`](#foley.sources.music_library.acquisition.kept_sources)), whose `url` / `mirror` a kept row carries on.

* **Type:**
  `kept`’s values

alias of [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### foley.sources.music_library.acquisition.METADATA_COLUMNS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('credited_by',)*

The metadata keys a titles file may set that are columns (the rest the library states).

### foley.sources.music_library.acquisition.REFUSED *= 'refused'*

the licence gate refused the title for the
intended use (nothing fetched); `wishlist`: a paid library’s title.

* **Type:**
  The row statuses. `refused`

### foley.sources.music_library.acquisition.TRACK_COLUMNS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('title', 'library', 'status', 'file', 'duration_s', 'sha256', 'license', 'license_url', 'rights_verified', 'commercial_ok', 'author', 'url', 'source_page_url', 'mirror', 'attribution', 'credited_by', 'error')*

The tracks table’s columns, in order (a row’s other metadata, a catalogue’s
`feel` or `genre`, follows in name order).

### foley.sources.music_library.acquisition.WISHLIST *= 'wishlist'*

the licence gate refused the title for the
intended use (nothing fetched); `wishlist`: a paid library’s title.

* **Type:**
  The row statuses. `refused`

### foley.sources.music_library.acquisition.acquire(library, titles, \*, out, fetch=None, transport=None, mirrors=(<function direct>, <function wayback>), verify=<function probe_verify>, kept=None, intended_use=IntendedUse(commercial=True, publish=True, redistribute_standalone=False, will_train=False, can_attribute=True, revenue_usd=0, allow_voice_or_trademark=False, territory=None), libraries=None, config=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

Download `titles` of `library` into `out`, verified, one row each.

`titles` is a list, or `{title: metadata}` whose metadata (`credited_by`:
the videos that credit it; a catalogue’s `feel`, `genre`, …) rides on the
row. `library` is a `MusicLibrary` or a name in `libraries` (default
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
recorded ([`kept_digests()`](#foley.sources.music_library.acquisition.kept_digests)), or `{file name: {"sha256", "url", "mirror"}}`
([`kept_sources()`](#foley.sources.music_library.acquisition.kept_sources), whose `url` and `mirror` the kept row keeps): a file in
`out` with that digest is kept, any other is fetched again. A paid library
downloads nothing and returns wishlist rows.

* **Raises:**
  * [**MusicLibraryError**](foley.sources.music_library.html.md#foley.sources.music_library.MusicLibraryError) – For an unknown library, titles of the wrong shape,
        metadata that restates the row, two titles saved as one file, or a
        `kept` value that is neither a digest nor a mapping with one.
  * [**MusicToolMissing**](foley.sources.music_library.html.md#foley.sources.music_library.MusicToolMissing) – When `verify` is the default and no probe can run
        (before anything is downloaded).
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – When both `fetch` and `transport` are given.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`AcquiredTrack`](#foley.sources.music_library.acquisition.AcquiredTrack)]

### foley.sources.music_library.acquisition.attribution_text(rows)

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

### foley.sources.music_library.acquisition.files_store(out)

`out` as a `{file name: bytes}` store: a mapping is used as it is; a folder
becomes foley’s file store over it ([`foley.stores.make_byte_store()`](foley.stores.html.md#foley.stores.make_byte_store), which
makes the folder on its first write).

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### foley.sources.music_library.acquisition.kept_digests(table)

`{file: sha256}` of the acquired or kept rows of a tracks table: what a rerun
may keep. `table` is [`tracks_table()`](#foley.sources.music_library.acquisition.tracks_table)’s CSV text, or the rows themselves
([`AcquiredTrack`](#foley.sources.music_library.acquisition.AcquiredTrack) or their [`row()`](#foley.sources.music_library.acquisition.AcquiredTrack.row) dicts, read back
from JSON).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.music_library.acquisition.kept_sources(table)

`{file: {"sha256", "url", "mirror"}}` of the acquired or kept rows of a
tracks table: [`kept_digests()`](#foley.sources.music_library.acquisition.kept_digests) with where each file came from, so a kept row
still says which URL and mirror served it (`acquire(kept=...)` takes either).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### foley.sources.music_library.acquisition.tracks_table(rows)

The tracks table as CSV text: [`TRACK_COLUMNS`](#foley.sources.music_library.acquisition.TRACK_COLUMNS), then any metadata the
rows carry, in name order.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
