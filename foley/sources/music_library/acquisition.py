"""Acquire a music library's titles: verified files, one provenance row each, a resumable table.

:func:`acquire` turns titles into download URLs (the library's rule), fetches each
from the first of its ``mirrors`` whose bytes ``verify`` accepts, writes the file to
``out`` and returns one :class:`AcquiredTrack` per title. Every step is a seam
(keyword arguments with working defaults):

- ``fetch`` (``url -> bytes``) or ``transport`` (a foley
  :class:`~foley.sources.http.Transport`): by default the fetch goes through
  :func:`~foley.sources.music_library.fetch.make_fetch` (the resilience layer per
  host: pace, ``429`` / ``Retry-After``, breaker); a ``fetch`` of the caller's own is
  paced per host too (:func:`~foley.sources.resilience.pace_per_host`, from the
  config's ``rate``). ``clock`` / ``sleep`` time both;
- ``mirrors``: :func:`~foley.sources.music_library.mirrors.direct`, then
  :func:`~foley.sources.music_library.mirrors.wayback`;
- ``verify`` (``bytes -> seconds``):
  :func:`~foley.sources.music_library.verify.probe_verify`;
- ``out``: any ``{file name: bytes}`` store, a folder by default;
- ``intended_use``: the :class:`~foley.base.IntendedUse` each title's licence must
  allow (default :data:`foley.licensing.DEFAULT_INTENDED_USE`: commercial
  publishing).

A row's licence is a :class:`~foley.base.LicenseRecord`
(:func:`~foley.sources.music_library.libraries.track_license`), put through foley's
fail-closed gate (:func:`foley.licensing.refusal_reason`) before anything is
fetched: a title it refuses is a ``refused`` row, with the reason, and is not
downloaded. ``url`` is where the bytes came from (the mirror that served them),
``page_url`` the library's own address. A title that fails is a ``failed`` row with
its reasons; the batch goes on. A file whose digest a previous run recorded
(``kept``, from :func:`kept_digests` or :func:`kept_sources`) is not fetched again,
so a rerun resumes. A paid library fetches nothing: its rows are ``wishlist`` rows.

:meth:`AcquiredTrack.row` is a flat, JSON-safe dict (a caller such as ``an`` bridges
it into its own asset rows without foley knowing it); :func:`tracks_table` is those
rows as CSV, and :func:`attribution_text` the blocks to paste under a video.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import unicodedata
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional, Union

from ...base import IntendedUse, LicenseRecord, SerializableMixin
from ...licensing import DEFAULT_INTENDED_USE, LicenseFlags, refusal_reason
from ..http import Transport
from ..resilience import RetryAfterTooLong, SourceUnavailable, pace_per_host
from .fetch import Fetch, make_fetch, music_library_config
from .libraries import MusicLibrary, MusicLibraryError, music_library, track_license
from .mirrors import DFLT_MIRRORS, Mirror, mirror_name
from .verify import Verify, probe_verify, require_probe

#: The row statuses. ``refused``: the licence gate refused the title for the
#: intended use (nothing fetched); ``wishlist``: a paid library's title.
ACQUIRED, KEPT, FAILED, REFUSED, WISHLIST = (
    "acquired",
    "kept",
    "failed",
    "refused",
    "wishlist",
)
#: The statuses whose file is in ``out`` (what a rerun may keep, what is credited).
HELD: tuple[str, ...] = (ACQUIRED, KEPT)
#: The tracks table's columns, in order (a row's other metadata, a catalogue's
#: ``feel`` or ``genre``, follows in name order).
TRACK_COLUMNS: tuple[str, ...] = (
    "title",
    "library",
    "status",
    "file",
    "duration_s",
    "sha256",
    "license",
    "license_url",
    "rights_verified",
    "commercial_ok",
    "author",
    "url",
    "source_page_url",
    "mirror",
    "attribution",
    "credited_by",
    "error",
)
#: The metadata keys a titles file may set that are columns (the rest the library states).
METADATA_COLUMNS: tuple[str, ...] = ("credited_by",)
#: Decimal places a duration is written with.
DURATION_DECIMALS: int = 3
#: What a fetch or a verification may raise for ONE title (an HTTP or connection
#: error is an ``OSError``, a :class:`MusicLibraryError` a ``ValueError``, an
#: exhausted retry or an open breaker :class:`SourceUnavailable`, a too-long
#: ``Retry-After`` :class:`RetryAfterTooLong`); anything else (a ``KeyError`` from a
#: config without a key the fetch reads, ...) is a bug and stops the batch.
_TITLE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    SourceUnavailable,
)
#: What reading or writing ONE file of ``out`` may raise (``dol`` refuses a key with
#: ``KeyError``; a disk with ``OSError``; a name the OS cannot hold with ``ValueError``).
_STORE_ERRORS: tuple[type[BaseException], ...] = (KeyError, OSError, ValueError)
#: The directories of an absolute local path in an error message (POSIX, Windows):
#: dropped from a row's ``error``, which is written into a shareable table.
_LOCAL_DIRS = re.compile(
    # POSIX dirs; Windows dirs with one backslash or two (an OSError's repr escapes them)
    r"(?<![\w.~:/-])/(?:[^\s'\"/]+/)+|\b[A-Za-z]:(?:\\{1,2}[^\s'\"\\]+)*\\{1,2}"
)

Titles = Union[Iterable[str], Mapping[str, Mapping[str, Any]]]
Out = Union[str, Path, MutableMapping[str, bytes]]


@dataclass(frozen=True)
class AcquiredTrack(SerializableMixin):
    """One row of the tracks table: a title, what became of it, and its provenance.

    ``url`` is the URL that served the bytes (a mirror's), ``mirror`` that mirror's
    name, ``page_url`` the library's own address for the title; ``credited_by`` the
    videos that credit it and ``metadata`` a titles file's other fields (``feel``,
    ``genre``, ...).
    """

    title: str
    library: str
    status: str
    license: LicenseRecord
    file: Optional[str] = None
    sha256: Optional[str] = None
    duration_s: Optional[float] = None
    url: Optional[str] = None
    mirror: Optional[str] = None
    page_url: Optional[str] = None
    credited_by: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None

    def __post_init__(self):
        credited = self.credited_by
        credited = (credited,) if isinstance(credited, str) else credited or ()
        object.__setattr__(self, "credited_by", tuple(map(str, credited)))

    def row(self) -> dict[str, Any]:
        """The row as the tracks table writes it: flat and JSON-safe (a list joined
        by ``; ``, a mapping as JSON)."""
        lic = self.license
        duration = self.duration_s
        out = {
            "title": self.title,
            "library": self.library,
            "status": self.status,
            "file": self.file,
            "duration_s": None
            if duration is None
            else round(duration, DURATION_DECIMALS),
            "sha256": self.sha256,
            "license": lic.license_id,
            "license_url": lic.license_url,
            "rights_verified": lic.rights_verified,
            "commercial_ok": lic.commercial_ok,
            "author": lic.creator_name,
            "url": self.url,
            "source_page_url": self.page_url,
            "mirror": self.mirror,
            "attribution": lic.attribution_text,
            "credited_by": list(self.credited_by),
            "error": self.error,
            **self.metadata,
        }
        return {k: _cell(v) for k, v in out.items()}


def _cell(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return "; ".join(map(str, value))
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True)
    return value


#: The keys a titles file's metadata may not set: they are the row's own, or a
#: licence flag (a titles file cannot claim ``commercial_ok``).
_RESERVED: frozenset = frozenset(
    (
        set(TRACK_COLUMNS)
        | {f.name for f in fields(AcquiredTrack)}
        | {f.name for f in fields(LicenseFlags)}
    )
    - set(METADATA_COLUMNS)
)
#: ``kept``'s values: a file's recorded sha256, or ``{"sha256", "url", "mirror"}``
#: (:func:`kept_sources`), whose ``url`` / ``mirror`` a kept row carries on.
Kept = Mapping[str, Union[str, Mapping[str, Any]]]


def acquire(
    library: Union[str, MusicLibrary],
    titles: Titles,
    *,
    out: Out,
    fetch: Optional[Fetch] = None,
    transport: Optional[Transport] = None,
    mirrors: Sequence[Mirror] = DFLT_MIRRORS,
    verify: Verify = probe_verify,
    kept: Optional[Kept] = None,
    intended_use: IntendedUse = DEFAULT_INTENDED_USE,
    libraries: Optional[Mapping[str, MusicLibrary]] = None,
    config: Optional[dict] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[AcquiredTrack]:
    """Download ``titles`` of ``library`` into ``out``, verified, one row each.

    ``titles`` is a list, or ``{title: metadata}`` whose metadata (``credited_by``:
    the videos that credit it; a catalogue's ``feel``, ``genre``, ...) rides on the
    row. ``library`` is a :class:`MusicLibrary` or a name in ``libraries`` (default
    :data:`~foley.sources.music_library.libraries.MUSIC_LIBRARIES`).

    Each title's licence is put through :func:`foley.licensing.refusal_reason` for
    ``intended_use`` first (fail-closed: an error in the gate is a refusal); a
    refused title is a ``refused`` row and is not fetched. The others are fetched
    from each of ``mirrors`` in turn until one gives bytes ``verify`` accepts.
    ``fetch`` (``url -> bytes``) replaces the HTTP path, paced per host by the
    config's ``rate``; otherwise the files come through ``transport`` (default:
    ``requests``) wrapped by foley's resilience layer per host; that path honours
    :func:`foley.offline`. ``config`` is laid over
    :data:`~foley.sources.music_library.fetch.MUSIC_LIBRARY_HTTP`; ``clock`` /
    ``sleep`` time the waits. ``kept`` is ``{file name: sha256}`` a previous run
    recorded (:func:`kept_digests`), or ``{file name: {"sha256", "url", "mirror"}}``
    (:func:`kept_sources`, whose ``url`` and ``mirror`` the kept row keeps): a file in
    ``out`` with that digest is kept, any other is fetched again. A paid library
    downloads nothing and returns wishlist rows.

    Raises:
        MusicLibraryError: For an unknown library, titles of the wrong shape,
            metadata that restates the row, two titles saved as one file, or a
            ``kept`` value that is neither a digest nor a mapping with one.
        MusicToolMissing: When ``verify`` is the default and no probe can run
            (before anything is downloaded).
        ValueError: When both ``fetch`` and ``transport`` are given.
    """
    lib = music_library(library, libraries=libraries)
    meta = _titles_meta(titles, lib)
    if lib.paid:
        return [_wishlist(lib, title, extra) for title, extra in meta.items()]
    names = _file_names(lib, meta)
    if fetch is not None and transport is not None:
        raise ValueError("pass fetch= (url -> bytes) or transport=, not both")
    config = music_library_config(config)
    kept = {name: _kept_record(value) for name, value in (kept or {}).items()}
    refusals = {
        title: _refusal(track_license(lib, title), intended_use) for title in meta
    }
    if all(refusals.values()):  # nothing may be fetched: no probe, no egress needed
        return [
            _refused(lib, title, extra, reason=refusals[title])
            for title, extra in meta.items()
        ]
    if verify is probe_verify:
        require_probe()  # stop before the first download, not after it
    if fetch is None:
        from ...runtime import EXTERNAL, require_egress

        egress = config.get("data_egress") or EXTERNAL
        require_egress(egress, what=f"music library {lib.name!r}")
        fetch = make_fetch(transport=transport, config=config, clock=clock, sleep=sleep)
    else:
        own_fetch = fetch
        wait = pace_per_host(config.get("rate"), clock=clock, sleep=sleep)

        def paced(url: str) -> bytes:  # the caller's fetch, paced per host
            wait(url)
            return own_fetch(url)

        fetch = paced
    store = files_store(out)
    return [
        _refused(lib, title, extra, reason=refusals[title])
        if refusals[title]
        else _acquire_title(
            lib,
            title,
            extra,
            name=names[title],
            store=store,
            kept=kept.get(names[title]),
            fetch=fetch,
            mirrors=mirrors,
            verify=verify,
        )  # fmt: skip
        for title, extra in meta.items()
    ]


def _refusal(record: LicenseRecord, intended_use: IntendedUse) -> Optional[str]:
    """Why foley's licence gate refuses ``record`` for ``intended_use`` (``None``: it
    keeps it). Fail-closed: a gate that raises refuses."""
    try:
        return refusal_reason(record, intended_use)
    except Exception as e:  # noqa: BLE001 - any error in the gate is a refusal
        return f"the licence gate could not decide ({type(e).__name__}: {e})"


def _kept_record(value: Union[str, Mapping[str, Any]]) -> dict:
    """A ``kept`` value as ``{"sha256", "url", "mirror"}``."""
    if isinstance(value, str):
        return {"sha256": value}
    if isinstance(value, Mapping) and isinstance(value.get("sha256"), str):
        return {k: value.get(k) for k in ("sha256", "url", "mirror")}
    raise MusicLibraryError(
        f"a kept value is a sha256 or {{'sha256': ..., 'url': ...}}, got {value!r}"
    )


def _acquire_title(
    lib: MusicLibrary,
    title: str,
    extra: Mapping[str, Any],
    *,
    name: str,
    store: MutableMapping[str, bytes],
    kept: Optional[Mapping[str, Any]],
    fetch: Fetch,
    mirrors: Sequence[Mirror],
    verify: Verify,
) -> AcquiredTrack:
    """One title's row: kept (its recorded digest is in ``store``), acquired, or failed.

    A fetch or verification error fails the title (:data:`_TITLE_ERRORS`), and so
    does the store refusing to read or write its file (:data:`_STORE_ERRORS`, caught
    only around the store); anything else stops the batch.
    """
    page = lib.track_url(title)
    common = _common(lib, title, extra, page_url=page)

    def failed(reason: str) -> AcquiredTrack:
        lic = track_license(lib, title, page_url=page)
        return AcquiredTrack(status=FAILED, license=lic, error=reason, **common)

    try:
        held = store[name] if kept and name in store else None
    except _STORE_ERRORS as e:
        return failed(_store_error(e, name=name))
    try:
        if held is not None and _sha256(held) == kept["sha256"]:
            source = {"url": kept.get("url"), "mirror": kept.get("mirror")}
            return _held(lib, KEPT, held, verify(held), file=name, **source, **common)
        data, duration, url, mirror = _fetch_verified(
            page, mirrors=mirrors, fetch=fetch, verify=verify
        )
    except _TITLE_ERRORS as e:
        return failed(str(e))
    try:
        store[name] = data
    except _STORE_ERRORS as e:
        return failed(_store_error(e, name=name))
    return _held(
        lib, ACQUIRED, data, duration, file=name, url=url, mirror=mirror, **common
    )


def _store_error(error: BaseException, *, name: str) -> str:
    """A store's refusal as a row's ``error``: the file name, and the reason without
    the local directories it names (the table is shared; a local path is private)."""
    if isinstance(error, OSError) and error.strerror:
        reason = error.strerror
    elif isinstance(error, KeyError) and error.args:
        reason = str(error.args[0])
    else:
        reason = str(error)
    return f"could not save {name!r}: {_LOCAL_DIRS.sub('', reason)}"


def _common(
    lib: MusicLibrary,
    title: str,
    extra: Mapping[str, Any],
    *,
    page_url: Optional[str] = None,
) -> dict:
    """The row fields every status shares: identity and the titles file's metadata."""
    metadata = dict(extra)
    credited_by = metadata.pop("credited_by", ())
    return dict(
        title=title,
        library=lib.name,
        page_url=page_url,
        credited_by=credited_by,
        metadata=metadata,
    )


def _wishlist(lib: MusicLibrary, title: str, extra: Mapping[str, Any]) -> AcquiredTrack:
    return AcquiredTrack(
        status=WISHLIST, license=track_license(lib, title), **_common(lib, title, extra)
    )


def _refused(
    lib: MusicLibrary, title: str, extra: Mapping[str, Any], *, reason: str
) -> AcquiredTrack:
    """The row of a title the licence gate refused: its licence and why, no file."""
    page = lib.track_url(title)
    return AcquiredTrack(
        status=REFUSED,
        license=track_license(lib, title, page_url=page),
        error=f"refused for the intended use: {reason}",
        **_common(lib, title, extra, page_url=page),
    )


def _held(
    lib: MusicLibrary,
    status: str,
    data: bytes,
    duration: float,
    *,
    title: str,
    page_url: Optional[str],
    **row: Any,
) -> AcquiredTrack:
    """A row whose file is in the store, its licence stamped with the file's digest."""
    digest = _sha256(data)
    lic = track_license(lib, title, page_url=page_url, sha256=digest)
    return AcquiredTrack(
        title=title,
        status=status,
        license=lic,
        sha256=digest,
        duration_s=duration,
        page_url=page_url,
        **row,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch_verified(
    url: str,
    *,
    mirrors: Sequence[Mirror],
    fetch: Fetch,
    verify: Verify,
) -> "tuple[bytes, float, str, str]":
    """``(bytes, seconds, the URL that served them, its mirror's name)`` from the
    first of ``mirrors`` whose bytes ``verify`` accepts; every mirror's reason in one
    :class:`MusicLibraryError` when none does."""
    reasons = []
    for mirror in mirrors:
        where = mirror(url)
        try:
            data = fetch(where)
            return data, verify(data), where, mirror_name(mirror)
        except RetryAfterTooLong as e:  # not worth the wait: the next mirror instead
            reasons.append(f"{mirror_name(mirror)}: {e} (next mirror tried)")
        except _TITLE_ERRORS as e:
            reasons.append(f"{mirror_name(mirror)}: {e}")
    raise MusicLibraryError("; ".join(reasons) or "no mirrors to fetch from")


def _titles_meta(titles: Any, lib: MusicLibrary) -> dict[str, dict[str, Any]]:
    """``titles`` as ``{title: metadata}``, refused when it is neither a list of
    titles nor such a mapping, or when metadata would restate the row."""
    if isinstance(titles, (str, bytes)):
        raise MusicLibraryError("titles is one string; pass a list of titles")
    if isinstance(titles, Mapping):
        meta = {}
        for title, m in titles.items():
            if not isinstance(m, Mapping):
                raise MusicLibraryError(
                    f"{title!r}: metadata must be an object ({{'feel': ...}}), got {m!r}"
                )
            meta[title] = dict(m)
    else:
        meta = {t: {} for t in titles}
    for title, extra in meta.items():
        if not isinstance(title, str) or not title.strip():
            raise MusicLibraryError(
                f"a title must be a non-empty string, got {title!r}"
            )
        clash = sorted(set(extra) & _RESERVED)
        if clash:
            raise MusicLibraryError(
                f"{title!r}: its metadata sets {clash}, which the library or the "
                f"table states ({lib.name}); drop them from the titles file"
            )
    return meta


def _file_names(lib: MusicLibrary, meta: Mapping[str, Any]) -> dict[str, str]:
    """``{title: file name}``, refused when two titles share a file (as a
    case-insensitive disk sees it)."""
    names = {title: lib.file_name(title) for title in meta}
    seen: dict[str, str] = {}
    for title, name in names.items():
        key = unicodedata.normalize("NFC", name).casefold()
        if key in seen:
            raise MusicLibraryError(
                f"titles {seen[key]!r} and {title!r} would both be saved as {name!r}"
            )
        seen[key] = title
    return names


def files_store(out: Out) -> MutableMapping[str, bytes]:
    """``out`` as a ``{file name: bytes}`` store: a mapping is used as it is; a folder
    becomes foley's file store over it (:func:`foley.stores.make_byte_store`, which
    makes the folder on its first write)."""
    if isinstance(out, MutableMapping):
        return out
    from ...stores import make_byte_store

    return make_byte_store(out)


def tracks_table(rows: Iterable[AcquiredTrack]) -> str:
    """The tracks table as CSV text: :data:`TRACK_COLUMNS`, then any metadata the
    rows carry, in name order."""
    dicts = [r.row() for r in rows]
    extras = sorted({k for d in dicts for k in d} - set(TRACK_COLUMNS))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[*TRACK_COLUMNS, *extras])
    writer.writeheader()
    writer.writerows(dicts)
    return buffer.getvalue()


Table = Union[str, Iterable[Union[AcquiredTrack, Mapping[str, Any]]]]


def _held_rows(table: Table) -> Iterable[Mapping[str, Any]]:
    """The acquired or kept rows (with a file and a digest) of a tracks table."""
    if isinstance(table, str):
        rows: Iterable[Mapping[str, Any]] = csv.DictReader(io.StringIO(table))
    else:
        rows = (r.row() if isinstance(r, AcquiredTrack) else r for r in table)
    return (
        r for r in rows if r.get("status") in HELD and r.get("file") and r.get("sha256")
    )


def kept_digests(table: Table) -> dict[str, str]:
    """``{file: sha256}`` of the acquired or kept rows of a tracks table: what a rerun
    may keep. ``table`` is :func:`tracks_table`'s CSV text, or the rows themselves
    (:class:`AcquiredTrack` or their :meth:`~AcquiredTrack.row` dicts, read back
    from JSON)."""
    return {r["file"]: r["sha256"] for r in _held_rows(table)}


def kept_sources(table: Table) -> dict[str, dict[str, Any]]:
    """``{file: {"sha256", "url", "mirror"}}`` of the acquired or kept rows of a
    tracks table: :func:`kept_digests` with where each file came from, so a kept row
    still says which URL and mirror served it (``acquire(kept=...)`` takes either)."""
    return {
        r["file"]: {
            "sha256": r["sha256"],
            "url": r.get("url") or None,
            "mirror": r.get("mirror") or None,
        }
        for r in _held_rows(table)
    }


def attribution_text(rows: Iterable[AcquiredTrack]) -> str:
    """The attribution blocks to paste under a video, one per track that has one
    (acquired or kept), blank-line separated, each once.

    Each block is :func:`foley.provenance.credits.attribution_line` of the row's
    licence: the library's own wording, verbatim.

    >>> from foley.sources.music_library import MUSIC_LIBRARIES, track_license
    >>> lic = track_license(MUSIC_LIBRARIES["incompetech"], "A")
    >>> print(attribution_text([AcquiredTrack("A", "incompetech", ACQUIRED, lic)] * 2))
    "A" Kevin MacLeod (incompetech.com)
    Licensed under Creative Commons: By Attribution 4.0 License
    http://creativecommons.org/licenses/by/4.0/
    <BLANKLINE>
    """
    from ...provenance.credits import attribution_line

    blocks = dict.fromkeys(
        attribution_line(r.license, fmt="plain")
        for r in rows
        if r.status in HELD and r.license.attribution_text
    )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
