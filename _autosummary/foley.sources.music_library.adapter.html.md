# foley.sources.music_library.adapter

A free music library as a live retrieve source: titles in, licensed tracks out (#212).

[`MusicLibraryAdapter`](#foley.sources.music_library.adapter.MusicLibraryAdapter) is the [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter) of one
free library (`incompetech`), built by the registry from the library’s config
([`foley.sources.music_library.config`](foley.sources.music_library.config.html.md#module-foley.sources.music_library.config)). Through
[`foley.sources.pull.add_from()`](foley.sources.pull.html.md#foley.sources.pull.add_from) a library’s tracks get what every source’s sounds
get: the fail-closed licence gate ([`foley.keep()`](foley.html.md#foley.keep)) under the call’s intent, a
by-value [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) from
[`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) (decode, QC, embed, store) with the library’s
attribution on its licence (credits), and the run manifest.

- `search`: a library has no search API, so the query is the titles: one title,
  a list of titles, or a credits description (a video’s, read by
  [`titles_by_library()`](foley.sources.music_library.credit_parser.html.md#foley.sources.music_library.credit_parser.titles_by_library) for this
  > library’s names). Each title is a candidate whose licence is

  [`track_license()`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.track_license)’s; nothing is fetched.
- `download`: the mirror chain [`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire) uses
  ([`fetch_verified()`](foley.sources.music_library.acquisition.html.md#foley.sources.music_library.acquisition.fetch_verified): the library’s
  server, then the Internet Archive’s raw copy), through the resilient transport,
  each file checked by `verify` ([`probe_verify()`](foley.sources.music_library.verify.html.md#foley.sources.music_library.verify.probe_verify)).

The library is looked up by name on each call, so the adapter follows
[`register_music_library()`](foley.sources.music_library.html.md#foley.sources.music_library.register_music_library) (`replace=True`).

### Module Attributes

| [`Query`](#foley.sources.music_library.adapter.Query)   | one title or a credits description, or the titles.                  |
|----------------------------------------------------------|---------------------------------------------------------------------|
| [`Adapter`](#foley.sources.music_library.adapter.Adapter) | Registry convention (arioso): the loader imports `adapter.Adapter`. |

### Functions

| [`query_titles`](#foley.sources.music_library.adapter.query_titles)(query, library)   | The titles `query` names for `library`, in order, each once.   |
|---------------------------------------------------------------------------------|----------------------------------------------------------------|

### Classes

| [`Adapter`](#foley.sources.music_library.adapter.Adapter)                                          | Registry convention (arioso): the loader imports `adapter.Adapter`.                                                                              |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| [`MusicLibraryAdapter`](#foley.sources.music_library.adapter.MusicLibraryAdapter)([config, http, verify, ...]) | One free music library as a retrieve source (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### foley.sources.music_library.adapter.Adapter

Registry convention (arioso): the loader imports `adapter.Adapter`.

### *class* foley.sources.music_library.adapter.MusicLibraryAdapter(config=None, \*, http=None, verify=<function probe_verify>, mirrors=(<function direct>, <function wayback>), library=None, libraries=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One free music library as a retrieve source (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)).

* **Parameters:**
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The library’s `SOURCE_CONFIG` (the registry passes it); its
    `api['library']` names the library.
  * **http** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)]) – The [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) files are asked through, used
    as given (the registry passes a resilient one, per host). Default: the
    library’s polite transport (`requests`, paced and retried per host),
    with the call’s egress checked.
  * **verify** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `bytes -> seconds`: how a file is checked to be a track (default
    [`probe_verify()`](foley.sources.music_library.verify.html.md#foley.sources.music_library.verify.probe_verify)).
  * **mirrors** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Where a title’s file is asked for, in order.
  * **library** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`MusicLibrary`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MusicLibrary)]) – The `MusicLibrary` itself, instead of the one registered
    under `config['api']['library']`.
  * **libraries** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MusicLibrary`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MusicLibrary)]]) – Where a library name is looked up (default: the registered ones).
  * **clock** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – The monotonic clock the default transport paces by.
  * **sleep** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – How the default transport waits.

#### download(source_id)

The verified bytes of one title, from the first mirror that serves them.

* **Raises:**
  * [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the title’s licence is not one foley verified or lets it
        keep (checked here too, so a direct call cannot fetch what the gate
        would refuse).
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – If the default `verify` cannot run here.
  * [**MusicLibraryError**](foley.sources.music_library.html.md#foley.sources.music_library.MusicLibraryError) – If no mirror serves a file `verify` accepts.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### get(source_id)

The record of one title (`incompetech:Sneaky Snitch` or the bare title).

* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### *property* library *: [MusicLibrary](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MusicLibrary)*

The library this source serves (looked up on each call).

* **Raises:**
  [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – If it is not registered, or is paid.

#### search(query, , license=None, k=50, provider_params=None, \*\*\_affordances)

The titles `query` names, as candidates (at most `k`; nothing fetched).

`license` is a licence id (`'cc0'`, `'CC-BY-4.0'`, `'cc-by'`): a
library has one licence, so its titles are all kept or none are (fail
closed). There are no native params (`provider_params` is refused).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

### foley.sources.music_library.adapter.Query

one title or a credits description, or the titles.

* **Type:**
  What `query` may be

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)] | [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### foley.sources.music_library.adapter.query_titles(query, library)

The titles `query` names for `library`, in order, each once.

A string is read as a credits description first
([`titles_by_library()`](foley.sources.music_library.credit_parser.html.md#foley.sources.music_library.credit_parser.titles_by_library), over this
library’s names only); one that credits nothing is one title when it is a single
line, and no title when it is several. A list (or a titles file’s
`{title: metadata}`) is the titles.

```pycon
>>> lib = music_library("incompetech")
>>> query_titles("Sneaky Snitch", lib)
['Sneaky Snitch']
>>> query_titles('"Sneaky Snitch" Kevin MacLeod (incompetech.com)', lib)
['Sneaky Snitch']
>>> query_titles(["A", "B", "A"], lib)
['A', 'B']
```

* **Raises:**
  [**SearchArgumentError**](foley.sources.base.html.md#foley.sources.base.SearchArgumentError) – If a title is not a non-empty string, or `query` is
      empty.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
