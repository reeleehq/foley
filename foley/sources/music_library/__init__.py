"""Acquire a licensed music library, with provenance: verified files, a tracks table, attribution.

A production that scores itself from free libraries writes the same script each
time: turn the titles a channel credits into download URLs, fetch them politely,
check each file is audio, record where it came from and under which licence, and
collect the attribution lines the licence asks for. :func:`acquire` is that script::

    from foley.sources.music_library import acquire, attribution_text, tracks_table

    rows = acquire("incompetech", ["Sneaky Snitch"], out="audio/macleod")
    open("audio/macleod/tracks.csv", "w").write(tracks_table(rows))
    print(attribution_text(rows))

- **A library is data** (:class:`MusicLibrary`, :data:`MUSIC_LIBRARIES`,
  :func:`register_music_library`): ``incompetech`` (Kevin MacLeod, CC BY 4.0) and
  the paid ``artlist`` and ``epidemic_sound``, whose titles become wishlist rows.
- **Licences come from foley's SSOT**: each row's
  :class:`~foley.base.LicenseRecord` is built from the library's licence URL by
  :func:`foley.licensing.license_id_from_cc_url` (:func:`track_license`) and gated
  by :func:`foley.licensing.refusal_reason` for ``acquire``'s ``intended_use``
  (default: commercial publishing) before anything is fetched; a refused title is a
  ``refused`` row. A paid library claims no rights.
- **Fetching is foley's**: a :class:`~foley.sources.http.Transport` wrapped per host
  by :func:`foley.sources.resilience.resilient` (pace, ``429`` / ``Retry-After``,
  breaker), with the library's own server then the Internet Archive's raw copy as
  mirrors (:func:`direct`, :func:`wayback`); :func:`probe_verify` checks each file
  has an audio stream and a length, with foley's media probes.
- **Rows are portable** (:class:`AcquiredTrack`): ``.row()`` is flat and JSON-safe,
  :func:`tracks_table` writes them as CSV and :func:`kept_digests` (or
  :func:`kept_sources`, with each file's URL) reads a table back, so a rerun fetches
  only what it lacks.

- **Each free library is also a live retrieve source** of its own name (#212):
  ``foley.add_from("incompetech", query="Sneaky Snitch")`` (a title, a list of
  titles, or a credits description) puts each title through the licence gate
  under the call's intent and :func:`~foley.index.ingest.ingest_one`, giving
  by-value :class:`~foley.base.SoundRecord` rows with their attribution, and a run
  manifest. The config is built from the library (:func:`library_source_config`,
  declared as the callable ``config.SOURCE_CONFIGS``, so a library registered at
  runtime is a source on the next discovery); the adapter
  (:class:`~foley.sources.music_library.adapter.MusicLibraryAdapter`) runs the same
  mirror chain and ``verify`` as :func:`acquire`. A paid library is not a source.

Stdlib only at import; ``requests`` loads on the first real download.

>>> lib = MUSIC_LIBRARIES["incompetech"]
>>> lib.track_url("Sneaky Snitch")
'https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3'
>>> track_license(lib, "Sneaky Snitch").license_id
'CC-BY-4.0'
"""

from __future__ import annotations

from .acquisition import (
    ACQUIRED,
    FAILED,
    HELD,
    KEPT,
    REFUSED,
    TRACK_COLUMNS,
    WISHLIST,
    AcquiredTrack,
    acquire,
    attribution_text,
    files_store,
    kept_digests,
    kept_sources,
    tracks_table,
)
from .config import library_source_config
from .credit_parser import titles_by_library, titles_from_json
from .fetch import (
    MUSIC_LIBRARY_HTTP,
    fetch_audio,
    make_fetch,
    music_library_config,
    polite_transport,
)
from .libraries import (
    BUILTIN_LIBRARIES,
    MUSIC_LIBRARIES,
    MusicLibrary,
    MusicLibraryError,
    music_library,
    register_music_library,
    safe_file_name,
    title_url,
    track_license,
)
from .mirrors import DFLT_MIRRORS, WAYBACK_RAW, direct, mirror_name, wayback
from .verify import MusicToolMissing, probe_available, probe_verify, require_probe

__all__ = [
    "ACQUIRED",
    "MusicLibraryAdapter",
    "BUILTIN_LIBRARIES",
    "DFLT_MIRRORS",
    "FAILED",
    "HELD",
    "KEPT",
    "MUSIC_LIBRARIES",
    "MUSIC_LIBRARY_HTTP",
    "REFUSED",
    "TRACK_COLUMNS",
    "WAYBACK_RAW",
    "WISHLIST",
    "AcquiredTrack",
    "MusicLibrary",
    "MusicLibraryError",
    "MusicToolMissing",
    "acquire",
    "attribution_text",
    "direct",
    "fetch_audio",
    "files_store",
    "kept_digests",
    "kept_sources",
    "library_source_config",
    "make_fetch",
    "mirror_name",
    "music_library",
    "music_library_config",
    "polite_transport",
    "probe_available",
    "probe_verify",
    "register_music_library",
    "require_probe",
    "safe_file_name",
    "title_url",
    "titles_by_library",
    "titles_from_json",
    "track_license",
    "tracks_table",
    "wayback",
]


def __getattr__(name: str):
    """Lazily expose the source adapter (loads ``adapter.py`` on demand)."""
    if name == "MusicLibraryAdapter":
        from .adapter import MusicLibraryAdapter

        return MusicLibraryAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
