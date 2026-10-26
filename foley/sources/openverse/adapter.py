"""Openverse retrieve adapter: keyless audio search with ready attribution strings.

``search`` calls ``/v1/audio/`` (anonymous: ``page_size`` ≤ 20, Freesound and Jamendo rows
excluded, see the config) with the licence filter pushed into the query, then re-checks
each row's licence fail-closed through :func:`foley.sources._keyless.license_for_item`
(Openverse does not verify licences). Durations arrive in milliseconds. ``download`` fetches
the row's ``url`` (cached from search, else resolved from ``/audio/{id}/``). HTTP and the
429 sleep are injected.
"""

from __future__ import annotations

from typing import Callable, Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from .._keyless import (
    DEFAULT_RETRY_WAITS_S,
    get_bytes,
    get_json,
    license_for_item,
)
from ..base import api_license
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

_PREFIX = "openverse:"


def _raw_id(source_id: str) -> str:
    s = str(source_id)
    return s[len(_PREFIX) :] if s.startswith(_PREFIX) else s


class OpenverseAdapter:
    """Keyless Openverse adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        include_freesound: Keep Freesound rows (stored by reference, bytes never cached);
            off by default: use the ``freesound`` source for those.
        http: The injected :class:`~foley.sources.http.Transport`.
        sleep: Called with the seconds to wait after an HTTP 429.
        retry_waits_s: The waits, one per retry.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        include_freesound: bool = False,
        http: Optional[Transport] = None,
        sleep: Optional[Callable[[float], None]] = None,
        retry_waits_s: "tuple[float, ...]" = DEFAULT_RETRY_WAITS_S,
    ):
        import time

        self.config = config if config is not None else SOURCE_CONFIG
        self._include_freesound = include_freesound
        self._http: Transport = http if http is not None else requests_transport
        self._sleep = sleep if sleep is not None else time.sleep
        self._waits = retry_waits_s
        self._urls: "dict[str, str]" = {}

    @property
    def notice(self) -> str:
        """The sentence Openverse's terms require an app to show prominently."""
        return self.config["notice"]

    def _get_json(self, path: str, params: Optional[dict] = None):
        api = self.config["api"]
        return get_json(
            self._http,
            api["base_url"] + path,
            params=params,
            headers={"User-Agent": api["user_agent"]},
            what="Openverse",
            waits=self._waits,
            sleep=self._sleep,
        )

    def search(
        self, query: str, *, license: Optional[str] = "cc0", k: int = 15, **kw
    ) -> "list[Candidate]":
        """Search Openverse audio for ``query``; return licence-checked candidates.

        Args:
            license: ``'cc0'`` (default) asks for CC0 only; anything else asks for CC0,
                CC-BY and public-domain-mark rows.
            k: Max rows (anonymous limit 20).
        """
        api = self.config["api"]
        filters = api["license_filter"]
        params = {
            "q": query[: api["max_query_chars"]],
            "page_size": min(int(k), api["max_page_size"]),
            "license": filters["cc0"] if license == "cc0" else filters["default"],
        }
        excluded = [
            s
            for s in api["excluded_sources"]
            if not (s == "freesound" and self._include_freesound)
        ]
        if excluded:
            params["excluded_source"] = ",".join(excluded)
        wanted = self.config["license"]["cc0_license_ids"] if license == "cc0" else None
        out = []
        for row in self._get_json(api["search_endpoint"]["path"], params).get(
            "results", []
        ):
            cand = self._candidate(row, only=wanted)
            if cand is not None:
                out.append(cand)
        return out

    def get(self, source_id: str) -> SoundRecord:
        """Resolve one row id (a UUID) to its record.

        Raises:
            LookupError: If its licence is not accepted.
        """
        rid = _raw_id(source_id)
        path = self.config["api"]["detail_endpoint"]["path"].format(id=rid)
        cand = self._candidate(self._get_json(path), only=None)
        if cand is None:
            raise LookupError(
                f"Openverse audio {rid} has a non-accepted licence; refused (fail-closed)."
            )
        return cand.sound

    def download(self, source_id: str) -> bytes:
        """The row's audio bytes (from the URL a search hit gave, else resolved by id)."""
        rid = _raw_id(source_id)
        if rid not in self._urls:
            self.get(rid)
        return get_bytes(
            self._http,
            self._urls[rid],
            headers={"User-Agent": self.config["api"]["user_agent"]},
            what="Openverse",
            waits=self._waits,
            sleep=self._sleep,
        )

    def _candidate(self, row: dict, *, only: Optional[list]) -> Optional[Candidate]:
        if not row.get("id") or not row.get("url"):
            return None
        by_reference = row.get("source") == "freesound"
        if by_reference and not self._include_freesound:
            return None
        found = license_for_item(self.config, row.get("license_url"))
        if found is None or (only is not None and found[0] not in only):
            return None
        license_id, verified = found
        rid = str(row["id"])
        lic = api_license(
            source=self.config["name"],
            source_id=rid,
            source_url=row.get("foreign_landing_url") or row.get("detail_url"),
            license_url=row["license_url"],
            license_id=license_id,
            rights_verified=verified,
            creator_name=row.get("creator"),
            attribution_text=row.get("attribution"),
            # Freesound's terms forbid caching its bytes, even for CC0.
            overrides={"cache_bytes_ok": False} if by_reference else None,
        )
        self._urls[rid] = row["url"]
        duration_ms = row.get("duration")
        record = SoundRecord(
            id=f"{_PREFIX}{rid}",
            uri=lic.source_url,
            license=lic,
            caption=row.get("title"),
            tags=sorted(
                {str(t["name"]) for t in row.get("tags") or [] if t.get("name")}
            ),
            duration_s=None if duration_ms is None else duration_ms / 1000.0,
        )
        return Candidate(
            sound=record, origin=CandidateOrigin.retrieved, preview_uri=row["url"]
        )


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = OpenverseAdapter
