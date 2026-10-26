"""Wikimedia Commons retrieve adapter: audio files with their licence, keyless.

``search`` turns a query into ``list=search`` over the File namespace restricted to audio
(``filetype:audio``), asking for each file's URL, size, duration and ``extmetadata`` in
the same call (the generator form). Each file's licence is read from ``extmetadata``
(``LicenseUrl``, else ``LicenseShortName``) through the one licence SSOT, so:

* CC0 and CC-BY become candidates, verified; a request for CC0 only (the façade's
  default ``license='cc0'``) keeps CC0 alone;
* "Public domain" becomes ``PDM-1.0`` with ``rights_verified=False``: a claim, never
  cleared by the licence field alone (Commons also holds impressions of copyrighted
  characters labelled public domain), so the pull gate stops it until a person confirms;
* share-alike, no-derivatives and anything unrecognised are dropped (fail closed).

The bytes come from ``upload.wikimedia.org`` with the same descriptive ``User-Agent``;
a 429 is waited out (:mod:`foley.sources._keyless`). HTTP and the sleep are injected.
"""

from __future__ import annotations

from typing import Callable, Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from .._keyless import (
    DEFAULT_RETRY_WAITS_S,
    get_bytes,
    get_json,
    license_for_item,
    strip_html,
)
from ..base import api_license
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

_PREFIX = "wikimedia_commons:"
_IMAGEINFO = "url|mime|size|extmetadata"


def _raw_id(source_id: str) -> str:
    s = str(source_id)
    return s[len(_PREFIX) :] if s.startswith(_PREFIX) else s


def _meta(info: dict, key: str) -> str:
    """One ``extmetadata`` value as text (``""`` when absent)."""
    return str((info.get("extmetadata") or {}).get(key, {}).get("value", "") or "")


class WikimediaCommonsAdapter:
    """Keyless Wikimedia Commons adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        http: The injected :class:`~foley.sources.http.Transport`.
        sleep: Called with the seconds to wait after an HTTP 429 (default ``time.sleep``).
        retry_waits_s: The waits, one per retry.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        http: Optional[Transport] = None,
        sleep: Optional[Callable[[float], None]] = None,
        retry_waits_s: "tuple[float, ...]" = DEFAULT_RETRY_WAITS_S,
    ):
        import time

        self.config = config if config is not None else SOURCE_CONFIG
        self._http: Transport = http if http is not None else requests_transport
        self._sleep = sleep if sleep is not None else time.sleep
        self._waits = retry_waits_s
        self._urls: "dict[str, str]" = {}  # id -> file URL, from search hits

    # -- http ---------------------------------------------------------------

    def _headers(self) -> dict:
        return {"User-Agent": self.config["api"]["user_agent"]}

    def _query(self, **params) -> dict:
        api = self.config["api"]
        return get_json(
            self._http,
            api["base_url"],
            params={"action": "query", "format": "json", **params},
            headers=self._headers(),
            what="Wikimedia Commons",
            waits=self._waits,
            sleep=self._sleep,
        )

    # -- SourceAdapter surface ----------------------------------------------

    def search(
        self, query: str, *, license: Optional[str] = "cc0", k: int = 15, **kw
    ) -> "list[Candidate]":
        """Search Commons audio for ``query``; return licence-checked candidates.

        Args:
            license: ``'cc0'`` (default) keeps CC0 files only; anything else (``None``,
                ``'cc-by'``) also keeps CC-BY and the unverified public-domain claims.
            k: Max files requested (the API's limit is 50).
        """
        api = self.config["api"]
        data = self._query(
            generator="search",
            gsrnamespace=api["namespace_file"],
            gsrsearch=query + api["search_suffix"],
            gsrlimit=min(int(k), api["max_page_size"]),
            prop="imageinfo",
            iiprop=_IMAGEINFO,
        )
        pages = sorted(
            ((data.get("query") or {}).get("pages") or {}).values(),
            key=lambda p: p.get("index", 0),  # the search rank
        )
        wanted = self.config["license"]["cc0_license_ids"] if license == "cc0" else None
        out = []
        for page in pages:
            cand = self._candidate(page, only=wanted)
            if cand is not None:
                out.append(cand)
        return out

    def get(self, source_id: str) -> SoundRecord:
        """Resolve one file (page id) to its record.

        Raises:
            LookupError: If the file is missing or its licence is not accepted.
        """
        rid = _raw_id(source_id)
        pages = (
            self._query(pageids=rid, prop="imageinfo", iiprop=_IMAGEINFO).get("query")
            or {}
        ).get("pages") or {}
        cand = self._candidate(pages.get(rid) or {}, only=None)
        if cand is None:
            raise LookupError(
                f"Wikimedia Commons file {rid} is missing or has a non-accepted "
                "licence; refused (fail-closed)."
            )
        return cand.sound

    def download(self, source_id: str) -> bytes:
        """The file's audio bytes (from the URL a search hit gave, else resolved by id)."""
        rid = _raw_id(source_id)
        if rid not in self._urls:
            self.get(rid)  # fills the URL cache, or raises
        return get_bytes(
            self._http,
            self._urls[rid],
            headers=self._headers(),
            what="Wikimedia Commons",
            waits=self._waits,
            sleep=self._sleep,
        )

    # -- page -> licence-checked Candidate ----------------------------------

    def _candidate(self, page: dict, *, only: Optional[list]) -> Optional[Candidate]:
        infos = page.get("imageinfo") or []
        if not infos or not page.get("pageid"):
            return None
        info = infos[0]
        if not str(info.get("mime", "")).startswith(("audio/", "application/ogg")):
            return None
        found = license_for_item(
            self.config, _meta(info, "LicenseUrl"), _meta(info, "LicenseShortName")
        )
        if found is None or (only is not None and found[0] not in only):
            return None
        license_id, verified = found
        pid = str(page["pageid"])
        title = str(page.get("title", ""))
        description = strip_html(_meta(info, "ImageDescription"))
        artist = strip_html(_meta(info, "Artist"))
        credit = strip_html(_meta(info, "Credit"))
        lic = api_license(
            source=self.config["name"],
            source_id=pid,
            source_url=info.get("descriptionurl")
            or f"https://commons.wikimedia.org/?curid={pid}",
            license_url=_meta(info, "LicenseUrl") or _meta(info, "LicenseShortName"),
            license_id=license_id,
            rights_verified=verified,
            creator_name=artist or None,
            attribution_text=(f"{artist}, {credit}".strip(", ") or None),
        )
        self._urls[pid] = info["url"]
        record = SoundRecord(
            id=f"{_PREFIX}{pid}",
            uri=lic.source_url,
            license=lic,
            caption=description or title.removeprefix("File:").rsplit(".", 1)[0],
            duration_s=info.get("duration"),
        )
        return Candidate(
            sound=record, origin=CandidateOrigin.retrieved, preview_uri=info["url"]
        )


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = WikimediaCommonsAdapter
