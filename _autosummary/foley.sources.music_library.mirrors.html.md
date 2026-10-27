# foley.sources.music_library.mirrors

Where else a track’s bytes may be: the library’s own server, then the Internet Archive.

A mirror is a `url -> url` function; [`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire)
tries each of its `mirrors` in turn and records the name of the one that served
the bytes. [`wayback()`](#foley.sources.music_library.mirrors.wayback) asks for the Internet Archive’s raw copy (the `id_`
form: the bytes as archived, not the archive’s page around them), the only route to
a site that refuses scripts.

### Module Attributes

| [`Mirror`](#foley.sources.music_library.mirrors.Mirror)       | the URL a track's bytes are asked for at, given the library's URL.   |
|---------------------------------------------------------------|----------------------------------------------------------------------|
| [`WAYBACK_RAW`](#foley.sources.music_library.mirrors.WAYBACK_RAW)  | the bytes as archived; `2`: the latest capture).                     |
| [`DFLT_MIRRORS`](#foley.sources.music_library.mirrors.DFLT_MIRRORS) | Where to look for a file, in order.                                  |

### Functions

| [`direct`](#foley.sources.music_library.mirrors.direct)(url)         | The URL itself: the library's own server.                                                                |
|----------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| [`mirror_name`](#foley.sources.music_library.mirrors.mirror_name)(mirror) | The name a row records for `mirror` (its function name).                                                 |
| [`wayback`](#foley.sources.music_library.mirrors.wayback)(url)        | The Internet Archive's raw copy of `url` ([`WAYBACK_RAW`](#foley.sources.music_library.mirrors.WAYBACK_RAW)). |

### foley.sources.music_library.mirrors.DFLT_MIRRORS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[str](https://docs.python.org/3/builtins/stdtypes.html#str)], [str](https://docs.python.org/3/builtins/stdtypes.html#str)], ...]* *= (<function direct>, <function wayback>)*

Where to look for a file, in order.

### foley.sources.music_library.mirrors.Mirror

the URL a track’s bytes are asked for at, given the library’s URL.

* **Type:**
  A mirror

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.music_library.mirrors.WAYBACK_RAW *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'https://web.archive.org/web/2id_/{url}'*

the bytes as archived;
`2`: the latest capture).

* **Type:**
  The Internet Archive’s raw-file form of a URL (`id_`

### foley.sources.music_library.mirrors.direct(url)

The URL itself: the library’s own server.

```pycon
>>> direct("https://example.org/a.mp3")
'https://example.org/a.mp3'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.mirrors.mirror_name(mirror)

The name a row records for `mirror` (its function name).

```pycon
>>> mirror_name(wayback)
'wayback'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.mirrors.wayback(url)

The Internet Archive’s raw copy of `url` ([`WAYBACK_RAW`](#foley.sources.music_library.mirrors.WAYBACK_RAW)).

```pycon
>>> wayback("https://example.org/a.mp3")
'https://web.archive.org/web/2id_/https://example.org/a.mp3'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
