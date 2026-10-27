"""A free music library as a live retrieve source: titles in, licensed tracks out (#212).

:class:`MusicLibraryAdapter` is the :class:`~foley.sources.base.SourceAdapter` of one
free library (``incompetech``), built by the registry from the library's config
(:mod:`foley.sources.music_library.config`). Through
:func:`foley.sources.pull.add_from` a library's tracks get what every source's sounds
get: the fail-closed licence gate (:func:`foley.keep`) under the call's intent, a
by-value :class:`~foley.base.SoundRecord` from
:func:`~foley.index.ingest.ingest_one` (decode, QC, embed, store) with the library's
attribution on its licence (credits), and the run manifest.

- ``search``: a library has no search API, so the query is the titles: one title,
  a list of titles, or a credits description (a video's, read by
  :func:`~foley.sources.music_library.credit_parser.titles_by_library` for this
  library's names). Each title is a candidate whose licence is
  :func:`~foley.sources.music_library.libraries.track_license`'s; nothing is fetched.
- ``download``: the mirror chain :func:`~foley.sources.music_library.acquire` uses
  (:func:`~foley.sources.music_library.acquisition.fetch_verified`: the library's
  server, then the Internet Archive's raw copy), through the resilient transport,
  each file checked by ``verify`` (:func:`~foley.sources.music_library.verify.probe_verify`).

The library is looked up by name on each call, so the adapter follows
:func:`~foley.sources.music_library.register_music_library` (``replace=True``).
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Optional, Union

from ...base import Candidate, CandidateOrigin, SoundRecord
from ...licensing import wanted_license_ids
from .._keyless import raw_id
from ..base import SearchArgumentError, SourceConfigurationError, check_provider_params
from ..http import Transport
from .acquisition import fetch_verified
from .config import library_source_config, license_section
from .credit_parser import titles_by_library
from .fetch import Fetch, fetch_audio, library_fetch, music_library_config
from .libraries import MusicLibrary, MusicLibraryError, music_library, track_license
from .mirrors import DFLT_MIRRORS, Mirror
from .verify import MusicToolMissing, Verify, probe_verify, require_probe

#: What ``query`` may be: one title or a credits description, or the titles.
Query = Union[str, Iterable[str], Mapping[str, Any]]


def query_titles(query: Query, library: MusicLibrary) -> "list[str]":
    """The titles ``query`` names for ``library``, in order, each once.

    A string is read as a credits description first
    (:func:`~foley.sources.music_library.credit_parser.titles_by_library`, over this
    library's names only); one that credits nothing is one title when it is a single
    line, and no title when it is several. A list (or a titles file's
    ``{title: metadata}``) is the titles.

    >>> lib = music_library("incompetech")
    >>> query_titles("Sneaky Snitch", lib)
    ['Sneaky Snitch']
    >>> query_titles('"Sneaky Snitch" Kevin MacLeod (incompetech.com)', lib)
    ['Sneaky Snitch']
    >>> query_titles(["A", "B", "A"], lib)
    ['A', 'B']

    Raises:
        SearchArgumentError: If a title is not a non-empty string, or ``query`` is
            empty.
    """
    if isinstance(query, str):
        text = query.strip()
        if not text:
            raise SearchArgumentError("query names no title")
        credited = titles_by_library(text, libraries={library.name: library})
        titles = credited.get(library.name) or ([] if "\n" in text else [text])
    elif isinstance(query, Mapping):
        titles = list(query)
    else:
        titles = list(query)
    bad = [t for t in titles if not isinstance(t, str) or not t.strip()]
    if bad:
        raise SearchArgumentError(f"a title must be a non-empty string, got {bad!r}")
    return list(dict.fromkeys(t.strip() for t in titles))


class MusicLibraryAdapter:
    """One free music library as a retrieve source (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The library's ``SOURCE_CONFIG`` (the registry passes it); its
            ``api['library']`` names the library.
        http: The :class:`~foley.sources.http.Transport` files are asked through, used
            as given (the registry passes a resilient one, per host). Default: the
            library's polite transport (``requests``, paced and retried per host),
            with the call's egress checked.
        verify: ``bytes -> seconds``: how a file is checked to be a track (default
            :func:`~foley.sources.music_library.verify.probe_verify`).
        mirrors: Where a title's file is asked for, in order.
        library: The :class:`MusicLibrary` itself, instead of the one registered
            under ``config['api']['library']``.
        libraries: Where a library name is looked up (default: the registered ones).
        clock: The monotonic clock the default transport paces by.
        sleep: How the default transport waits.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        http: Optional[Transport] = None,
        verify: Verify = probe_verify,
        mirrors: Sequence[Mirror] = DFLT_MIRRORS,
        library: Optional[MusicLibrary] = None,
        libraries: Optional[Mapping[str, MusicLibrary]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if config is None:
            if library is None:
                raise SourceConfigurationError(
                    "a music library source needs its config or its library"
                )
            config = library_source_config(library)
        self.config = config
        self._library = library
        self._libraries = libraries
        self._http = http
        self._verify = verify
        self._mirrors = tuple(mirrors)
        self._clock, self._sleep = clock, sleep

    @property
    def library(self) -> MusicLibrary:
        """The library this source serves (looked up on each call).

        Raises:
            SourceConfigurationError: If it is not registered, or is paid.
        """
        name = (self.config.get("api") or {}).get("library") or self.config["name"]
        try:
            lib = self._library or music_library(name, libraries=self._libraries)
        except MusicLibraryError as e:
            raise SourceConfigurationError(str(e)) from e
        if lib.paid:
            raise SourceConfigurationError(
                f"music library {lib.name!r} is paid: it is not a source"
            )
        return lib

    @functools.cached_property
    def _fetch(self) -> Fetch:
        """``url -> bytes`` over the injected transport, or the polite default."""
        config = music_library_config(self.config)
        if self._http is not None:
            return functools.partial(fetch_audio, http=self._http, config=config)
        return library_fetch(
            config=config,
            what=f"music library {self.config['name']!r}",
            clock=self._clock,
            sleep=self._sleep,
        )

    def search(
        self,
        query: Query,
        *,
        license: Optional[str] = None,
        k: int = 50,
        provider_params: Optional[dict] = None,
        **_affordances,
    ) -> "list[Candidate]":
        """The titles ``query`` names, as candidates (at most ``k``; nothing fetched).

        ``license`` is a licence id (``'cc0'``, ``'CC-BY-4.0'``, ``'cc-by'``): a
        library has one licence, so its titles are all kept or none are (fail
        closed). There are no native params (``provider_params`` is refused).
        """
        check_provider_params(provider_params)
        lib = self.library
        section = {"name": lib.name, "license": license_section(lib)}
        wanted = wanted_license_ids(section, license)
        if wanted is not None and lib.license_id not in wanted:
            return []
        return [self._candidate(lib, t) for t in query_titles(query, lib)[:k]]

    def get(self, source_id: str) -> SoundRecord:
        """The record of one title (``incompetech:Sneaky Snitch`` or the bare title)."""
        lib = self.library
        return self._candidate(lib, self._title(lib, source_id)).sound

    def download(self, source_id: str) -> bytes:
        """The verified bytes of one title, from the first mirror that serves them.

        Raises:
            LookupError: If the title's licence is not one foley verified or lets it
                keep (checked here too, so a direct call cannot fetch what the gate
                would refuse).
            SourceConfigurationError: If the default ``verify`` cannot run here.
            MusicLibraryError: If no mirror serves a file ``verify`` accepts.
        """
        lib = self.library
        title = self._title(lib, source_id)
        lic = track_license(lib, title)
        if not (lic.rights_verified and lic.cache_bytes_ok):
            raise LookupError(
                f"{lib.name} {title!r}: its licence ({lic.license_id}) is not verified "
                "or does not allow keeping the file; refused (fail-closed)."
            )
        if self._verify is probe_verify:
            try:
                require_probe()
            except MusicToolMissing as e:
                raise SourceConfigurationError(str(e)) from e
        data, _seconds, _url, _mirror = fetch_verified(
            lib.track_url(title),
            mirrors=self._mirrors,
            fetch=self._fetch,
            verify=self._verify,
        )
        return data

    @staticmethod
    def _title(lib: MusicLibrary, source_id: str) -> str:
        title = raw_id(f"{lib.name}:", source_id).strip()
        if not title:
            raise LookupError(f"{source_id!r} names no {lib.name} title")
        return title

    @staticmethod
    def _candidate(lib: MusicLibrary, title: str) -> Candidate:
        page = lib.track_url(title)
        lic = track_license(lib, title, page_url=page)
        record = SoundRecord(
            id=f"{lib.name}:{title}",
            uri=page,
            license=lic,
            caption=title,
            tags=["music", lib.name],
        )
        return Candidate(sound=record, origin=CandidateOrigin.retrieved)


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = MusicLibraryAdapter
