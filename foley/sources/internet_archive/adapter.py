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
from typing import Callable, Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from .._keyless import (
    DEFAULT_RETRY_WAITS_S,
    get_bytes,
    get_json,
    license_for_item,
    strip_html,
)
from ..base import SourceConfigurationError, api_license
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

_PREFIX = "internet_archive:"
_FIELDS = ("identifier", "title", "licenseurl", "creator", "description", "subject")


def _raw_id(source_id: str) -> str:
    s = str(source_id)
    return s[len(_PREFIX) :] if s.startswith(_PREFIX) else s


class InternetArchiveAdapter:
    """Opt-in Internet Archive adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        opt_in: Use the archive. Default: whether ``$FOLEY_INTERNET_ARCHIVE`` is set to 1.
        http: The injected :class:`~foley.sources.http.Transport`.
        sleep: Called with the seconds to wait after an HTTP 429.
        retry_waits_s: The waits, one per retry.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        opt_in: Optional[bool] = None,
        http: Optional[Transport] = None,
        sleep: Optional[Callable[[float], None]] = None,
        retry_waits_s: "tuple[float, ...]" = DEFAULT_RETRY_WAITS_S,
    ):
        import time

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
        self._sleep = sleep if sleep is not None else time.sleep
        self._waits = retry_waits_s

    def _json(self, url: str, params: Optional[dict] = None):
        return get_json(
            self._http, url, params=params, what="Internet Archive",
            waits=self._waits, sleep=self._sleep,
        )  # fmt: skip

    def search(
        self, query: str, *, license: Optional[str] = None, k: int = 15, **kw
    ) -> "list[Candidate]":
        """Search archive audio for ``query``; return candidates (all unverified).

        ``license`` is accepted for the façade's sake and ignored: the query always asks
        for items with a ``licenseurl``, and the allowlist decides which stay.
        """
        api = self.config["api"]
        params = {
            "q": f"({query}) AND mediatype:audio AND {api['licensed_clause']}",
            "fl[]": list(_FIELDS),
            "rows": min(int(k), api["max_rows"]),
            "output": "json",
        }
        docs = (self._json(api["search_url"], params).get("response") or {}).get(
            "docs", []
        )
        return [c for c in (self._candidate(d) for d in docs) if c is not None]

    def get(self, source_id: str) -> SoundRecord:
        """Resolve one item identifier to its record.

        Raises:
            LookupError: If the item is missing or its licence is not accepted.
        """
        rid = _raw_id(source_id)
        meta = self._json(self.config["api"]["metadata_url"].format(id=rid)).get(
            "metadata"
        )
        cand = self._candidate({**(meta or {}), "identifier": rid}) if meta else None
        if cand is None:
            raise LookupError(
                f"Internet Archive item {rid} is missing or has a non-accepted licence; "
                "refused (fail-closed)."
            )
        return cand.sound

    def download(self, source_id: str) -> bytes:
        """The first audio file of the item under ``max_file_bytes`` (see the config)."""
        api = self.config["api"]
        rid = _raw_id(source_id)
        files = self._json(api["metadata_url"].format(id=rid)).get("files") or []
        for f in files:
            fmt = str(f.get("format", "")).lower()
            if (
                any(a in fmt for a in api["audio_formats"])
                and 0 < int(f.get("size") or 0) <= api["max_file_bytes"]
            ):
                url = api["download_url"].format(id=rid, name=f["name"])
                return get_bytes(
                    self._http, url, what="Internet Archive",
                    waits=self._waits, sleep=self._sleep,
                )  # fmt: skip
        raise LookupError(
            f"Internet Archive item {rid} has no audio file under "
            f"{api['max_file_bytes']} bytes."
        )

    def _candidate(self, doc: dict) -> Optional[Candidate]:
        ident = doc.get("identifier")
        found = license_for_item(self.config, doc.get("licenseurl")) if ident else None
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
            license_url=doc["licenseurl"],
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
