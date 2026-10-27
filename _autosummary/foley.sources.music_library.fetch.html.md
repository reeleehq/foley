# foley.sources.music_library.fetch

Fetching a library’s files politely, through foley’s transport and its resilience layer.

A library is someone’s website, and a long run (63 tracks against the Wayback
Machine) meets `429 Too Many Requests`. So the default fetch goes through a
[`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) (default
[`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport), which imports `requests` on its
first call only) wrapped, **per host**, by
[`foley.sources.resilience.resilient()`](foley.sources.resilience.html.md#foley.sources.resilience.resilient): a pace from [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP)’s
`rate` (2 s between two requests to one host), backoff on `429` / `5xx` that
waits what a `Retry-After` header asks up to the config’s `retry.max_delay_s`, a
longer `Retry-After` given up at once
([`RetryAfterTooLong`](foley.sources.resilience.html.md#foley.sources.resilience.RetryAfterTooLong): the next mirror is tried
instead of waiting the cap again and again), and a circuit breaker. Each host has
its own pace and breaker, so falling back to the archive spends no pause, and the
library’s site failing does not open the archive’s breaker. The runtime’s
`http_resilience` switch turns the wrapping off, as it does for every source.

[`fetch_audio()`](#foley.sources.music_library.fetch.fetch_audio) refuses what is not a track: a non-200 answer, a text page (an
error page served with 200), and a body over `max_bytes` (by its
`Content-Length` before the body is read, and by its length after).

A config is laid over [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP) ([`music_library_config()`](#foley.sources.music_library.fetch.music_library_config)), so
a caller states only what it changes.

### Module Attributes

| [`Fetch`](#foley.sources.music_library.fetch.Fetch)              | how [`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire) gets a file.   |
|---------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP) | How a music library is fetched (the keys a source config's resilience layer reads, plus the request's own).       |

### Functions

| [`fetch_audio`](#foley.sources.music_library.fetch.fetch_audio)(url, \*, http[, config])              | `url`'s bytes, asked for with the config's user agent.                                                                                                                                                                                                        |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`make_fetch`](#foley.sources.music_library.fetch.make_fetch)(\*[, transport, config, clock, sleep]) | The default `url -> bytes`: [`fetch_audio()`](#foley.sources.music_library.fetch.fetch_audio) over [`polite_transport()`](#foley.sources.music_library.fetch.polite_transport) (`config` laid over [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP)). |
| [`music_library_config`](#foley.sources.music_library.fetch.music_library_config)([config])                    | `config` laid over [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP) (top-level keys: a `retry` or `rate` given replaces the default one whole).                                                                                            |
| [`polite_transport`](#foley.sources.music_library.fetch.polite_transport)([transport, config, clock, ...]) | `transport` (default [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)) with a resilient wrapper per host, built from `config` (see the module docstring).                                          |

### foley.sources.music_library.fetch.Fetch

how [`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire) gets a file.

* **Type:**
  `url -> bytes`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)* *= {'data_egress': 'external', 'max_bytes': 67108864, 'name': 'music_library', 'pricing': {'unit': 'free'}, 'rate': {'per_min': 30}, 'retry': {'give_up_over_max_delay': True, 'max_delay_s': 120.0}, 'user_agent': 'foley-music-library (+https://github.com/reeleehq/foley)'}*

How a music library is fetched (the keys a source config’s resilience layer reads,
plus the request’s own). `rate`: one request per 2 s to one host (a library is
someone’s website); `retry.max_delay_s`: the longest `Retry-After` honoured
(a longer one moves on to the next mirror); `pricing`: free, so a GET is
re-sent after a dropped connection.

### foley.sources.music_library.fetch.fetch_audio(url, , http, config=None)

`url`’s bytes, asked for with the config’s user agent.

A body over `max_bytes` is refused by its declared `Content-Length` before
`resp.content` is touched, and by its length after (a server may declare none,
or lie). foley’s [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) returns a whole response,
so with [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport) the body is already in
memory when the header is read: the header check spares the copy, not the
download. A streaming transport, which would stop at `max_bytes`, is a
follow-up.

* **Raises:**
  [**MusicLibraryError**](foley.sources.music_library.html.md#foley.sources.music_library.MusicLibraryError) – On a non-200 answer, a `text/*` page (an error page
      served with 200), a body over `config['max_bytes']`, or one shorter
      than its declared `Content-Length` (a cut download, which a probe of
      its header alone would still accept).
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.sources.music_library.fetch.make_fetch(\*, transport=None, config=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

The default `url -> bytes`: [`fetch_audio()`](#foley.sources.music_library.fetch.fetch_audio) over [`polite_transport()`](#foley.sources.music_library.fetch.polite_transport)
(`config` laid over [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP)).

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### foley.sources.music_library.fetch.music_library_config(config=None)

`config` laid over [`MUSIC_LIBRARY_HTTP`](#foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP) (top-level keys: a `retry`
or `rate` given replaces the default one whole).

```pycon
>>> music_library_config({"rate": {"per_min": 6}})["rate"], music_library_config()["max_bytes"]
({'per_min': 6}, 67108864)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.music_library.fetch.polite_transport(transport=None, \*, config=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

`transport` (default [`requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)) with a
resilient wrapper per host, built from `config` (see the module docstring).

Left unwrapped when the active runtime turns `http_resilience` off.

* **Return type:**
  [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport)
