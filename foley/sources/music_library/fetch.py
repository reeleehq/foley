"""Fetching a library's files politely, through foley's transport and its resilience layer.

A library is someone's website, and a long run (63 tracks against the Wayback
Machine) meets ``429 Too Many Requests``. So the default fetch goes through a
:class:`~foley.sources.http.Transport` (default
:func:`~foley.sources.http.requests_transport`, which imports ``requests`` on its
first call only) wrapped, **per host**, by
:func:`foley.sources.resilience.resilient`: a pace from :data:`MUSIC_LIBRARY_HTTP`'s
``rate`` (2 s between two requests to one host), backoff on ``429`` / ``5xx`` that
waits what a ``Retry-After`` header asks (up to the config's ``retry.max_delay_s``),
and a circuit breaker. Each host has its own pace and breaker, so falling back to
the archive spends no pause, and the library's site failing does not open the
archive's breaker. The runtime's ``http_resilience`` switch turns the wrapping off,
as it does for every source.

:func:`fetch_audio` refuses what is not a track: a non-200 answer, a text page (an
error page served with 200), and a body over ``max_bytes``.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Optional

from ..http import Transport, requests_transport
from ..resilience import make_resilient_transport_from_config, per_host
from .libraries import MusicLibraryError

#: ``url -> bytes``: how :func:`~foley.sources.music_library.acquire` gets a file.
Fetch = Callable[[str], bytes]

#: How a music library is fetched (the keys a source config's resilience layer reads,
#: plus the request's own). ``rate``: one request per 2 s to one host (a library is
#: someone's website); ``retry.max_delay_s``: the longest ``Retry-After`` honoured
#: as asked; ``pricing``: free, so a GET is re-sent after a dropped connection.
MUSIC_LIBRARY_HTTP: dict = {
    "name": "music_library",
    "rate": {"per_min": 30},
    "retry": {"max_delay_s": 120.0},
    "pricing": {"unit": "free"},
    "data_egress": "external",
    "user_agent": "foley-music-library (+https://github.com/reeleehq/foley)",
    # A music track is a few MB; a body past this is not one.
    "max_bytes": 64 * 1024 * 1024,
}


def polite_transport(
    transport: Optional[Transport] = None,
    *,
    config: dict = MUSIC_LIBRARY_HTTP,
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


def fetch_audio(
    url: str, *, http: Transport, config: dict = MUSIC_LIBRARY_HTTP
) -> bytes:
    """``url``'s bytes, asked for with the config's user agent.

    Raises:
        MusicLibraryError: On a non-200 answer, a ``text/*`` page (an error page
            served with 200), or a body over ``config['max_bytes']``.
    """
    resp = http("GET", url, headers={"User-Agent": config["user_agent"]})
    if resp.status_code != 200:
        raise MusicLibraryError(f"HTTP {resp.status_code} from {url}")
    kind = _header(resp, "Content-Type").split(";")[0].strip()
    if kind.startswith("text/"):
        raise MusicLibraryError(f"{url} is a {kind} page, not audio")
    data = resp.content
    if len(data) > config["max_bytes"]:
        raise MusicLibraryError(f"{url} is over {config['max_bytes']} bytes")
    return data


def make_fetch(
    *,
    transport: Optional[Transport] = None,
    config: dict = MUSIC_LIBRARY_HTTP,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetch:
    """The default ``url -> bytes``: :func:`fetch_audio` over :func:`polite_transport`."""
    http = polite_transport(transport, config=config, clock=clock, sleep=sleep)
    return functools.partial(fetch_audio, http=http, config=config)
