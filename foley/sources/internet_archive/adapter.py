"""Internet Archive retrieve adapter: opt-in discovery of archival sounds, never auto-verified.

Items come from ``advancedsearch.php`` restricted to audio with a ``licenseurl``. Each
item's licence string goes through the one licence SSOT and the config's allowlist, and
every candidate gets ``rights_verified=False`` whatever it says: the field is what the
uploader asserted. So :func:`foley.sources.pull.add_from` skips these until a person has
confirmed an item; the adapter is for finding and fetching, not for clearing.
Constructing it without the opt-in raises :class:`~foley.sources.base.SourceConfigurationError`.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from .._keyless import get_bytes, get_json, raw_id, strip_html
from .._license_gate import license_for_item, wanted_license_ids
from ..base import SourceConfigurationError, api_license, merge_provider_params
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

_PREFIX = "internet_archive:"
_FIELDS = ("identifier", "title", "licenseurl", "creator", "description", "subject")


_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def _lucene_escape(text: str) -> str:
    """``text`` with Lucene's query syntax characters escaped (a query stays one phrase)."""
    return _LUCENE_SPECIAL.sub(r"\\\1", text)


class InternetArchiveAdapter:
    """Opt-in Internet Archive adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        opt_in: Use the archive. Default: whether ``$FOLEY_INTERNET_ARCHIVE`` is set to 1.
        http: The injected :class:`~foley.sources.http.Transport`.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        opt_in: Optional[bool] = None,
        http: Optional[Transport] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        env = self.config["api"]["opt_in_env"]
        if opt_in is None:
            opt_in = os.environ.get(env, "").strip().lower() in ("1", "true", "yes")
        if not opt_in:
            raise SourceConfigurationError(
                "internet_archive is opt-in: its licences are what uploaders asserted, so "
                f"nothing it returns is verified. Set ${env}=1 (or pass opt_in=True) to use it."
            )
        self._http: Transport = http if http is not None else requests_transport

    def _json(self, url: str, params: Optional[dict] = None):
        return get_json(self._http, url, params=params, what="Internet Archive")

    def search(
        self,
        query: str,
        *,
        license: Optional[str] = None,
        k: int = 15,
        provider_params: Optional[dict] = None,
        **kw,
    ) -> "list[Candidate]":
        """Search archive audio for ``query``; return candidates (all unverified).

        ``license`` is a licence id (``'CC0-1.0'``; ``'cc0'`` is an alias) and keeps only
        items under it; ``None`` keeps every accepted licence. The query always asks for items with a ``licenseurl``.
        ``provider_params`` are native advancedsearch params merged over the
        translated ones (#61); a ``q`` is ANDed onto foley's as one group, never
        replaces it (the config's ``provider_params`` policy).
        """
        only = wanted_license_ids(self.config, license)
        if only == []:  # a licence this source does not accept: nothing can match
            return []
        api = self.config["api"]
        params = {
            "q": f"({_lucene_escape(query)}) AND mediatype:audio AND {api['licensed_clause']}",
            "fl[]": list(_FIELDS),
            "rows": min(int(k), api["max_rows"]),
            "output": "json",
        }
        params = merge_provider_params(
            params, provider_params, policy=self.config.get("provider_params")
        )
        docs = (
            self.invoke_native(api["search_url"], **params).get("response") or {}
        ).get("docs", [])
        return [
            c for c in (self._candidate(d, only=only) for d in docs) if c is not None
        ]

    def invoke_native(self, url: str, **params) -> dict:
        """GET an Internet Archive ``url`` with native ``params``; return the parsed JSON (#61).

        It bypasses the licence filter and the per-item licence check that
        :meth:`search` applies: the caller owns licence gating for what comes back.
        """
        return self._json(url, params)

    def get(self, source_id: str) -> SoundRecord:
        """Resolve one item identifier to its record.

        Raises:
            LookupError: If the item is missing or its licence is not accepted.
        """
        rid = raw_id(_PREFIX, source_id)
        meta = self._json(self.config["api"]["metadata_url"].format(id=rid)).get(
            "metadata"
        )
        cand = (
            self._candidate({**(meta or {}), "identifier": rid}, only=None)
            if meta
            else None
        )
        if cand is None:
            raise LookupError(
                f"Internet Archive item {rid} is missing or has a non-accepted licence; "
                "refused (fail-closed)."
            )
        return cand.sound

    def download(self, source_id: str) -> bytes:
        """The first audio file of the item under ``max_file_bytes`` (see the config).

        Raises:
            LookupError: If the item's licence is not accepted (checked here too, so a
                direct call cannot fetch what a search would have dropped), or it has no
                suitable audio file.
        """
        api = self.config["api"]
        rid = raw_id(_PREFIX, source_id)
        data = self._json(api["metadata_url"].format(id=rid))
        if (
            self._candidate(
                {**(data.get("metadata") or {}), "identifier": rid}, only=None
            )
            is None
        ):
            raise LookupError(
                f"Internet Archive item {rid} is missing or has a non-accepted licence; "
                "refused (fail-closed)."
            )
        for f in data.get("files") or []:
            fmt = str(f.get("format", "")).lower()
            audio = any(a in fmt for a in api["audio_formats"]) and "video" not in fmt
            if audio and 0 < int(f.get("size") or 0) <= api["max_file_bytes"]:
                url = api["download_url"].format(id=rid, name=f["name"])
                return get_bytes(self._http, url, what="Internet Archive")
        raise LookupError(
            f"Internet Archive item {rid} has no audio file under "
            f"{api['max_file_bytes']} bytes."
        )

    def _candidate(self, doc: dict, *, only: Optional[list]) -> Optional[Candidate]:
        ident = doc.get("identifier")
        urls = doc.get("licenseurl")  # archive metadata fields can be lists
        urls = [urls] if isinstance(urls, str) else [str(u) for u in urls or []]
        found = license_for_item(self.config, *urls, only=only) if ident else None
        if found is None:
            return None
        license_id, _ = found
        creator = doc.get("creator")
        if isinstance(creator, list):
            creator = ", ".join(map(str, creator))
        lic = api_license(
            source=self.config["name"],
            source_id=str(ident),
            source_url=self.config["api"]["item_url"].format(id=ident),
            license_url=urls[0],
            license_id=license_id,
            rights_verified=False,  # uploader-asserted: a person confirms
            creator_name=creator or None,
        )
        subject = doc.get("subject") or []
        subjects = [subject] if isinstance(subject, str) else subject
        record = SoundRecord(
            id=f"{_PREFIX}{ident}",
            uri=lic.source_url,
            license=lic,
            caption=strip_html(doc.get("title") or "") or None,
            tags=sorted({str(s) for s in subjects if s}),
        )
        return Candidate(sound=record, origin=CandidateOrigin.retrieved)


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = InternetArchiveAdapter
