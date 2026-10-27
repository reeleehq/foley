# foley.sources.music_library.config

`SOURCE_CONFIGS` for the music libraries: one retrieve source per free library (#212).

Each free [`MusicLibrary`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MusicLibrary) in
[`MUSIC_LIBRARIES`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MUSIC_LIBRARIES) is a live retrieve
source of its own name (`incompetech`), so `foley.add_from("incompetech",
query="Sneaky Snitch")` runs it through the licence gate, `ingest_one` and the run
manifest like any other source. A paid library is not a source: it never downloads.

`SOURCE_CONFIGS` is a function, not a tuple: the registry
([`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources)) calls it on every discovery pass,
so a library added with
[`register_music_library()`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.register_music_library) becomes a
source without a config file of its own. Each config is built by
[`library_source_config()`](#foley.sources.music_library.config.library_source_config) from the library itself and from
[`MUSIC_LIBRARY_HTTP`](foley.sources.music_library.fetch.html.md#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP) (the pace, the
`Retry-After` cap, free pricing, external egress), so the polite fetch and the
source share one declaration.

```pycon
>>> cfg = library_source_config(MUSIC_LIBRARIES["incompetech"])
>>> cfg["kind"], cfg["license"]["accepted_license_ids"], cfg["pricing"]["unit"]
('retrieve', ['CC-BY-4.0'], 'free')
>>> [c["name"] for c in SOURCE_CONFIGS()]
['incompetech']
```

### Module Attributes

| [`CC0_LICENSE_ID`](#foley.sources.music_library.config.CC0_LICENSE_ID)   | The id CC0 has in foley's licence table (`license='cc0'` keeps it).   |
|-------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`EXTRA`](#foley.sources.music_library.config.EXTRA)            | The pip extra a library source needs (the lazy `requests`).           |

### Functions

| [`SOURCE_CONFIGS`](#foley.sources.music_library.config.SOURCE_CONFIGS)([libraries])    | The configs of the free libraries registered now (`libraries`: default [`MUSIC_LIBRARIES`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MUSIC_LIBRARIES)).   |
|---------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`library_source_config`](#foley.sources.music_library.config.library_source_config)(library) | The `SOURCE_CONFIG` of the free `library`.                                                                                                                                                        |
| [`license_section`](#foley.sources.music_library.config.license_section)(library)       | The `license` block of `library`'s source: its one licence, from its URL.                                                                                                                         |

### foley.sources.music_library.config.CC0_LICENSE_ID *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'CC0-1.0'*

The id CC0 has in foley’s licence table (`license='cc0'` keeps it).

### foley.sources.music_library.config.EXTRA *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'music-library'*

The pip extra a library source needs (the lazy `requests`).

### foley.sources.music_library.config.SOURCE_CONFIGS(libraries=None)

The configs of the free libraries registered now (`libraries`: default
[`MUSIC_LIBRARIES`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.MUSIC_LIBRARIES)).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.sources.music_library.config.library_source_config(library)

The `SOURCE_CONFIG` of the free `library`.

* **Raises:**
  [**MusicLibraryError**](foley.sources.music_library.html.md#foley.sources.music_library.MusicLibraryError) – If `library` is paid (a paid library is not a source).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.music_library.config.license_section(library)

The `license` block of `library`’s source: its one licence, from its URL.

`search_default` is `None`: a library has one licence, so `add_from`’s
default does not narrow it to CC0 (an explicit `license=` still does, fail
closed). Each item’s [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) is still
[`track_license()`](foley.sources.music_library.libraries.html.md#foley.sources.music_library.libraries.track_license)’s, gated per call.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
