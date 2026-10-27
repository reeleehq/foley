"""Fetching a library's files politely, through foley's transport and its resilience layer.

A library is someone's website, and a long run (63 tracks against the Wayback
Machine) meets ``429 Too Many Requests``. So the default fetch goes through a
:class:`~foley.sources.http.Transport` (default
:func:`~foley.sources.http.requests_transport`, which imports ``requests`` on its
first call only) wrapped, **per host**, by
:func:`foley.sources.resilience.resilient`: a pace from :data:`MUSIC_LIBRARY_HTTP`'s
``rate`` (2 s between two requests to one host), backoff on ``429`` / ``5xx`` that
waits what a ``Retry-After`` header asks up to the config's ``retry.max_delay_s``, a
longer ``Retry-After`` given up at once
(:class:`~foley.sources.resilience.RetryAfterTooLong`: the next mirror is tried
instead of waiting the cap again and again), and a circuit breaker. Each host has
its own pace and breaker, so falling back to the archive spends no pause, and the
library's site failing does not open the archive's breaker. The runtime's
``http_resilience`` switch turns the wrapping off, as it does for every source.

:func:`fetch_audio` refuses what is not a track: a non-200 answer, a text page (an
error page served with 200), and a body over ``max_bytes`` (by its
``Content-Length`` before the body is read, and by its length after).

A config is laid over :data:`MUSIC_LIBRARY_HTTP` (:func:`music_library_config`), so
a caller states only what it changes.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Optional

from ..http import Transport, requests_transport
from ..resilience import make_resilient_transport_from_config, pace_per_host, per_host
from .libraries import MusicLibraryError

#: ``url -> bytes``: how :func:`~foley.sources.music_library.acquire` gets a file.
Fetch = Callable[[str], bytes]

#: How a music library is fetched (the keys a source config's resilience layer reads,
#: plus the request's own). ``rate``: one request per 2 s to one host (a library is
#: someone's website); ``retry.max_delay_s``: the longest ``Retry-After`` honoured
#: (a longer one moves on to the next mirror); ``pricing``: free, so a GET is
#: re-sent after a dropped connection.
MUSIC_LIBRARY_HTTP: dict = {
    "name": "music_library",
    "rate": {"per_min": 30},
    "retry": {"max_delay_s": 120.0, "give_up_over_max_delay": True},
    "pricing": {"unit": "free"},
    "data_egress": "external",
    "user_agent": "foley-music-library (+https://github.com/reeleehq/foley)",
    # A music track is a few MB; a body past this is not one.
    "max_bytes": 64 * 1024 * 1024,
}


def music_library_config(config: Optional[dict] = None) -> dict:
    """``config`` laid over :data:`MUSIC_LIBRARY_HTTP` (top-level keys: a ``retry``
    or ``rate`` given replaces the default one whole).

    >>> music_library_config({"rate": {"per_min": 6}})["rate"], music_library_config()["max_bytes"]
    ({'per_min': 6}, 67108864)
    """
    return {**MUSIC_LIBRARY_HTTP, **(config or {})}


def polite_transport(
    transport: Optional[Transport] = None,
    *,
    config: Optional[dict] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Transport:
    """``transport`` (default :func:`~foley.sources.http.requests_transport`) with a
    resilient wrapper per host, built from ``config`` (see the module docstring).

    Left unwrapped when the active runtime turns ``http_resilience`` off.
    """
    from ...runtime import current_runtime

    base = transport if transport is not None else requests_transport
    if not current_runtime().http_resilience:
        return base
    config = music_library_config(config)
    return per_host(
        lambda: make_resilient_transport_from_config(
            config, base=base, clock=clock, sleep=sleep
        )
    )


def _header(resp, name: str) -> str:
    """A response header, matched case-insensitively (``''`` when absent)."""
    headers = getattr(resp, "headers", None) or {}
    wanted = name.lower()
    return next((str(v) for k, v in headers.items() if k.lower() == wanted), "")


def _content_length(resp) -> Optional[int]:
    """The ``Content-Length`` a response declares, or ``None`` (absent or unreadable)."""
    try:
        return int(_header(resp, "Content-Length").strip())
    except ValueError:
        return None


def fetch_audio(url: str, *, http: Transport, config: Optional[dict] = None) -> bytes:
    """``url``'s bytes, asked for with the config's user agent.

    A body over ``max_bytes`` is refused by its declared ``Content-Length`` before
    ``resp.content`` is touched, and by its length after (a server may declare none,
    or lie). foley's :class:`~foley.sources.http.Transport` returns a whole response,
    so with :func:`~foley.sources.http.requests_transport` the body is already in
    memory when the header is read: the header check spares the copy, not the
    download. A streaming transport, which would stop at ``max_bytes``, is a
    follow-up.

    Raises:
        MusicLibraryError: On a non-200 answer, a ``text/*`` page (an error page
            served with 200), a body over ``config['max_bytes']``, or one shorter
            than its declared ``Content-Length`` (a cut download, which a probe of
            its header alone would still accept).
    """
    config = music_library_config(config)
    cap = config["max_bytes"]
    resp = http("GET", url, headers={"User-Agent": config["user_agent"]})
    if resp.status_code != 200:
        raise MusicLibraryError(f"HTTP {resp.status_code} from {url}")
    kind = _header(resp, "Content-Type").split(";")[0].strip()
    if kind.startswith("text/"):
        raise MusicLibraryError(f"{url} is a {kind} page, not audio")
    declared = _content_length(resp)
    if declared is not None and declared > cap:
        raise MusicLibraryError(f"{url} declares {declared} bytes, over {cap}")
    data = resp.content
    if len(data) > cap:
        raise MusicLibraryError(f"{url} is over {cap} bytes")
    if declared is not None and len(data) < declared:  # a probe reads a header only
        raise MusicLibraryError(
            f"{url} is truncated: {len(data)} of the {declared} bytes it declares"
        )
    return data


def make_fetch(
    *,
    transport: Optional[Transport] = None,
    config: Optional[dict] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetch:
    """The default ``url -> bytes``: :func:`fetch_audio` over :func:`polite_transport`
    (``config`` laid over :data:`MUSIC_LIBRARY_HTTP`)."""
    config = music_library_config(config)
    http = polite_transport(transport, config=config, clock=clock, sleep=sleep)
    return functools.partial(fetch_audio, http=http, config=config)


def library_fetch(
    *,
    fetch: Optional[Fetch] = None,
    transport: Optional[Transport] = None,
    config: Optional[dict] = None,
    what: str = "music library",
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetch:
    """The ``url -> bytes`` a library's files are fetched with (one rule for every caller).

    A ``fetch`` of the caller's own is paced per host by the config's ``rate``
    (:func:`~foley.sources.resilience.pace_per_host`). Otherwise the call's egress is
    checked (:func:`foley.runtime.require_egress`, so :func:`foley.offline` refuses
    it, naming ``what``) and :func:`make_fetch` goes through ``transport``.

    Raises:
        ValueError: When both ``fetch`` and ``transport`` are given.
        EgressBlocked: When the HTTP path is refused by an offline scope.
    """
    if fetch is not None and transport is not None:
        raise ValueError("pass fetch= (url -> bytes) or transport=, not both")
    config = music_library_config(config)
    if fetch is None:
        from ...runtime import EXTERNAL, require_egress

        require_egress(config.get("data_egress") or EXTERNAL, what=what)
        return make_fetch(transport=transport, config=config, clock=clock, sleep=sleep)
    own_fetch = fetch
    wait = pace_per_host(config.get("rate"), clock=clock, sleep=sleep)

    def paced(url: str) -> bytes:  # the caller's fetch, paced per host
        wait(url)
        return own_fetch(url)

    return paced
