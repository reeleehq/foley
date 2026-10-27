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
a 429 is waited out by the resilient transport the registry wraps around ``http``
(see ``retry`` in the config). HTTP is injected.
"""

from __future__ import annotations

import re
from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ...licensing import wanted_license_ids
from .._keyless import get_bytes, get_json, raw_id, strip_html
from .._license_gate import license_for_item
from ..base import api_license, merge_provider_params
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

_PREFIX = "wikimedia_commons:"
_IMAGEINFO = "url|mime|size|mediatype|extmetadata"
_VERSIONED = re.compile(r"\d")


def _clear_label(short: str) -> bool:
    """Whether a licence label alone (no URL) names its licence: CC0, public domain, or a versioned CC."""
    low = short.strip().lower()
    return low in ("cc0", "public domain") or bool(_VERSIONED.search(low))


def _meta(info: dict, key: str) -> str:
    """One ``extmetadata`` value as text (``""`` when absent)."""
    return str((info.get("extmetadata") or {}).get(key, {}).get("value", "") or "")


class WikimediaCommonsAdapter:
    """Keyless Wikimedia Commons adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        http: The injected :class:`~foley.sources.http.Transport`.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        http: Optional[Transport] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        self._http: Transport = http if http is not None else requests_transport
        self._urls: "dict[str, str]" = {}  # id -> file URL, from search hits

    # -- http ---------------------------------------------------------------

    def _headers(self) -> dict:
        return {"User-Agent": self.config["api"]["user_agent"]}

    def invoke_native(self, **params) -> dict:
        """Call the MediaWiki ``action=query`` API with native ``params`` (#61).

        Returns the JSON response.

        It bypasses the licence filter and the per-item licence check that
        :meth:`search` applies: the caller owns licence gating for what comes back.
        """
        api = self.config["api"]
        return get_json(
            self._http,
            api["base_url"],
            params={"action": "query", "format": "json", **params},
            headers=self._headers(),
            what="Wikimedia Commons",
        )

    # -- SourceAdapter surface ----------------------------------------------

    def search(
        self,
        query: str,
        *,
        license: Optional[str] = "cc0",
        k: int = 15,
        page: int = 1,
        provider_params: Optional[dict] = None,
        **kw,
    ) -> "list[Candidate]":
        """Search Commons audio for ``query``; return licence-checked candidates.

        Args:
            license: A licence id (``'cc0'`` is an alias for CC0-1.0; ``'cc-by'`` the
                CC-BY ids) keeps only files under it; ``None`` also keeps CC-BY and the
                unverified public-domain claims.
            k: Max files requested (the API's limit is 50).
            page: The results page (1-based, ``k`` per page), sent as an offset.
            provider_params: Native search params merged over the translated ones
                (#61); the per-item licence check still applies.
        """
        wanted = wanted_license_ids(self.config, license)
        if wanted == []:  # a licence this source does not accept: nothing can match
            return []
        api = self.config["api"]
        params = dict(
            generator="search",
            gsrnamespace=api["namespace_file"],
            gsrsearch=query + api["search_suffix"],
            gsrlimit=min(int(k), api["max_page_size"]),
            prop="imageinfo",
            iiprop=_IMAGEINFO,
        )
        if page != 1:
            offset = (int(page) - 1) * params["gsrlimit"]
            params[self.config["param_map"]["page"]["native_name"]] = offset
        data = self.invoke_native(
            **merge_provider_params(
                params, provider_params, policy=self.config.get("provider_params")
            )
        )
        pages = sorted(
            ((data.get("query") or {}).get("pages") or {}).values(),
            key=lambda p: p.get("index", 0),  # the search rank
        )
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
        rid = raw_id(_PREFIX, source_id)
        pages = (
            self.invoke_native(pageids=rid, prop="imageinfo", iiprop=_IMAGEINFO).get(
                "query"
            )
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
        rid = raw_id(_PREFIX, source_id)
        if rid not in self._urls:
            self.get(rid)  # fills the URL cache, or raises
        return get_bytes(
            self._http,
            self._urls[rid],
            headers=self._headers(),
            what="Wikimedia Commons",
        )

    # -- page -> licence-checked Candidate ----------------------------------

    def _candidate(self, page: dict, *, only: Optional[list]) -> Optional[Candidate]:
        infos = page.get("imageinfo") or []
        if not infos or not page.get("pageid"):
            return None
        info = infos[0]
        if str(info.get("mediatype", "")).upper() != "AUDIO":
            return None  # a picture, a video, an .ogv served as application/ogg
        url, short = _meta(info, "LicenseUrl"), _meta(info, "LicenseShortName")
        if not url and not _clear_label(short):
            return None  # a bare "Attribution" label is Commons' own, not a CC licence
        found = license_for_item(self.config, url, short, only=only)
        if found is None:
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
