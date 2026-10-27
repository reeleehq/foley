"""Where else a track's bytes may be: the library's own server, then the Internet Archive.

A mirror is a ``url -> url`` function; :func:`~foley.sources.music_library.acquire`
tries each of its ``mirrors`` in turn and records the name of the one that served
the bytes. :func:`wayback` asks for the Internet Archive's raw copy (the ``id_``
form: the bytes as archived, not the archive's page around them), the only route to
a site that refuses scripts.
"""

from __future__ import annotations

from collections.abc import Callable

#: A mirror: the URL a track's bytes are asked for at, given the library's URL.
Mirror = Callable[[str], str]

#: The Internet Archive's raw-file form of a URL (``id_``: the bytes as archived;
#: ``2``: the latest capture).
WAYBACK_RAW: str = "https://web.archive.org/web/2id_/{url}"


def direct(url: str) -> str:
    """The URL itself: the library's own server.

    >>> direct("https://example.org/a.mp3")
    'https://example.org/a.mp3'
    """
    return url


def wayback(url: str) -> str:
    """The Internet Archive's raw copy of ``url`` (:data:`WAYBACK_RAW`).

    >>> wayback("https://example.org/a.mp3")
    'https://web.archive.org/web/2id_/https://example.org/a.mp3'
    """
    return WAYBACK_RAW.format(url=url)


def mirror_name(mirror: Mirror) -> str:
    """The name a row records for ``mirror`` (its function name).

    >>> mirror_name(wayback)
    'wayback'
    """
    return getattr(mirror, "__name__", None) or repr(mirror)


#: Where to look for a file, in order.
DFLT_MIRRORS: tuple[Mirror, ...] = (direct, wayback)
