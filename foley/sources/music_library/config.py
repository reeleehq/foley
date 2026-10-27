"""``SOURCE_CONFIGS`` for the music libraries: one retrieve source per free library (#212).

Each free :class:`~foley.sources.music_library.libraries.MusicLibrary` in
:data:`~foley.sources.music_library.libraries.MUSIC_LIBRARIES` is a live retrieve
source of its own name (``incompetech``), so ``foley.add_from("incompetech",
query="Sneaky Snitch")`` runs it through the licence gate, ``ingest_one`` and the run
manifest like any other source. A paid library is not a source: it never downloads.

``SOURCE_CONFIGS`` is a function, not a tuple: the registry
(:func:`foley.sources.registry.discover_sources`) calls it on every discovery pass,
so a library added with
:func:`~foley.sources.music_library.libraries.register_music_library` becomes a
source without a config file of its own. Each config is built by
:func:`library_source_config` from the library itself and from
:data:`~foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP` (the pace, the
``Retry-After`` cap, free pricing, external egress), so the polite fetch and the
source share one declaration.

>>> cfg = library_source_config(MUSIC_LIBRARIES["incompetech"])
>>> cfg["kind"], cfg["license"]["accepted_license_ids"], cfg["pricing"]["unit"]
('retrieve', ['CC-BY-4.0'], 'free')
>>> [c["name"] for c in SOURCE_CONFIGS()]
['incompetech']
"""

from __future__ import annotations

from typing import Optional

from ...licensing import derive_license_flags
from .fetch import MUSIC_LIBRARY_HTTP
from .libraries import MUSIC_LIBRARIES, MusicLibrary, MusicLibraryError

#: The id CC0 has in foley's licence table (``license='cc0'`` keeps it).
CC0_LICENSE_ID: str = "CC0-1.0"
#: The pip extra a library source needs (the lazy ``requests``).
EXTRA: str = "music-library"


def license_section(library: MusicLibrary) -> dict:
    """The ``license`` block of ``library``'s source: its one licence, from its URL.

    ``search_default`` is ``None``: a library has one licence, so ``add_from``'s
    default does not narrow it to CC0 (an explicit ``license=`` still does, fail
    closed). Each item's :class:`~foley.base.LicenseRecord` is still
    :func:`~foley.sources.music_library.libraries.track_license`'s, gated per call.
    """
    license_id = library.license_id
    return {
        "default_license_id": license_id,
        "accepted_license_ids": [license_id],
        "cc0_license_ids": [license_id] if license_id == CC0_LICENSE_ID else [],
        "search_default": None,
        "license_url": library.license_url,
        "cache_bytes_ok": True,  # register_music_library refuses a library without it
        # The licence table's flag (the SSOT track_license reads), never a guess.
        "requires_attribution": derive_license_flags(license_id).requires_attribution,
    }


def library_source_config(library: MusicLibrary) -> dict:
    """The ``SOURCE_CONFIG`` of the free ``library``.

    Raises:
        MusicLibraryError: If ``library`` is paid (a paid library is not a source).
    """
    if library.paid:
        raise MusicLibraryError(
            f"music library {library.name!r} is paid: it is not a source "
            "(its titles are wishlist rows; see acquire)"
        )
    return {
        **MUSIC_LIBRARY_HTTP,  # rate, retry, pricing (free), data_egress, user agent, cap
        "name": library.name,
        "kind": "retrieve",
        "display_name": f"{library.author} ({library.name}, music library)",
        "website": library.author_url,
        "auth": None,
        "dependencies": [],
        "optional_dependencies": ["requests"],
        "extra": EXTRA,
        "param_map": {
            # A library has no search API: the query is a title, a list of titles, or
            # a credits description (titles_by_library reads it).
            "query": {"native_name": "titles", "required": True},
            "k": {"native_name": "k"},
            "license": {"native_name": "license", "adapter_handled": True},
        },
        "supported_affordances": ["query", "k", "license"],
        "on_unsupported_param": "warn",
        "api": {"library": library.name},
        "output": {"default_format": "mp3", "returns": "bytes", "storage": "by_value"},
        "license": license_section(library),
        "pricing": {
            **MUSIC_LIBRARY_HTTP["pricing"],
            "amount_usd": 0.0,
            "source": f"{library.name}: a free licence ({library.license_id})",
        },
        # One pace and one breaker per host: the library's site and the Wayback
        # Machine (its mirror) are paced, and fail, separately.
        "resilience_scope": "per_host",
        "capabilities": {"music": True},
    }


def SOURCE_CONFIGS(
    libraries: Optional[dict] = None,
) -> "list[dict]":  # noqa: N802 - the registry's name
    """The configs of the free libraries registered now (``libraries``: default
    :data:`~foley.sources.music_library.libraries.MUSIC_LIBRARIES`)."""
    libraries = MUSIC_LIBRARIES if libraries is None else libraries
    return [library_source_config(lib) for lib in libraries.values() if not lib.paid]
