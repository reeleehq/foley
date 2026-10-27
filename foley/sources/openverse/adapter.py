"""Openverse retrieve adapter: keyless audio search with ready attribution strings.

``search`` calls ``/v1/audio/`` (anonymous: ``page_size`` ≤ 20, Freesound and Jamendo rows
excluded, see the config) with the licence filter pushed into the query, then re-checks
each row's licence fail-closed through :func:`foley.sources._license_gate.license_for_item`
(Openverse does not verify licences: a row's licence is the one its origin provider
reported, trusted like Freesound's own field; the landing page is the check for anything
that matters). The terms' "made using Openverse" notice is stamped on each licence record
(``notice_text_required``), so the credits carry it. Durations arrive in milliseconds. ``download`` fetches
the row's ``url`` (cached from search, else resolved from ``/audio/{id}/``). HTTP and the
429 sleep are injected.
"""

from __future__ import annotations

from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ...licensing import wanted_license_ids
from .._keyless import get_bytes, get_json, raw_id
from .._license_gate import license_for_item, native_license_filter
from ..base import api_license, merge_provider_params
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

_PREFIX = "openverse:"


class OpenverseAdapter:
    """Keyless Openverse adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        include_freesound: Keep Freesound rows (stored by reference, bytes never cached);
            off by default: use the ``freesound`` source for those.
        http: The injected :class:`~foley.sources.http.Transport`.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        include_freesound: bool = False,
        http: Optional[Transport] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        self._include_freesound = include_freesound
        self._http: Transport = http if http is not None else requests_transport
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
        )

    def search(
        self,
        query: str,
        *,
        license: Optional[str] = "cc0",
        k: int = 15,
        page: int = 1,
        include_explicit: bool = False,
        sources: Optional[list] = None,
        kind: str = "sfx",
        provider_params: Optional[dict] = None,
        **kw,
    ) -> "list[Candidate]":
        """Search Openverse audio for ``query``; return licence-checked candidates.

        Args:
            license: A licence id (``'cc0'`` is an alias for CC0-1.0) keeps only rows
                under it, and is pushed into the native ``license`` filter (CC0, CC-BY or
                PDM); ``None`` asks for CC0, CC-BY and public-domain-mark rows.
            k: Max rows (anonymous limit 20).
            page: The results page (1-based, ``k`` per page).
            include_explicit: Also return rows Openverse marks mature.
            sources: Only these Openverse providers (``wikimedia_audio``, …); the
                excluded ones (Freesound, Jamendo) stay excluded, so asking only for
                them returns nothing.
            kind: ``sfx`` (default, no category filter) or ``music``.
            provider_params: Native search params merged over the translated ones
                (#61); the per-item licence check still applies.
        """
        api = self.config["api"]
        wanted = wanted_license_ids(self.config, license)
        if wanted == []:  # a licence this source does not accept: nothing can match
            return []
        params = {
            "q": query[: api["max_query_chars"]],
            "page_size": min(int(k), api["max_page_size"]),
            "license": native_license_filter(
                wanted, api["license_native"], default=api["license_default"]
            ),
        }
        excluded = [
            s
            for s in api["excluded_sources"]
            if not (s == "freesound" and self._include_freesound)
        ]
        pm = self.config["param_map"]
        if sources:
            allowed = [s for s in sources if s not in excluded]
            if not allowed:  # only excluded providers asked for: nothing can match
                return []
            params[pm["sources"]["native_name"]] = ",".join(allowed)
        elif excluded:
            params["excluded_source"] = ",".join(excluded)
        if page != 1:
            params[pm["page"]["native_name"]] = int(page)
        if include_explicit:
            params[pm["include_explicit"]["native_name"]] = "true"
        category = pm["kind"]["to_native"].get(kind)
        if category:
            params[pm["kind"]["native_name"]] = category
        params = merge_provider_params(
            params, provider_params, policy=self.config.get("provider_params")
        )
        out = []
        for row in self.invoke_native(api["search_endpoint"]["path"], **params).get(
            "results", []
        ):
            cand = self._candidate(row, only=wanted)
            if cand is not None:
                out.append(cand)
        return out

    def invoke_native(self, path: str, **params) -> dict:
        """GET an Openverse API ``path`` with native ``params``; return the parsed JSON (#61).

        It bypasses the licence filter and the per-item licence check that
        :meth:`search` applies: the caller owns licence gating for what comes back.
        """
        return self._get_json(path, params)

    def get(self, source_id: str) -> SoundRecord:
        """Resolve one row id (a UUID) to its record.

        Raises:
            LookupError: If its licence is not accepted.
        """
        rid = raw_id(_PREFIX, source_id)
        path = self.config["api"]["detail_endpoint"]["path"].format(id=rid)
        cand = self._candidate(self._get_json(path), only=None)
        if cand is None:
            raise LookupError(
                f"Openverse audio {rid} has a non-accepted licence; refused (fail-closed)."
            )
        return cand.sound

    def download(self, source_id: str) -> bytes:
        """The row's audio bytes (from the URL a search hit gave, else resolved by id)."""
        rid = raw_id(_PREFIX, source_id)
        if rid not in self._urls:
            self.get(rid)
        return get_bytes(
            self._http,
            self._urls[rid],
            headers={"User-Agent": self.config["api"]["user_agent"]},
            what="Openverse",
        )

    def _candidate(self, row: dict, *, only: Optional[list]) -> Optional[Candidate]:
        if not row.get("id") or not row.get("url"):
            return None
        by_reference = row.get("source") == "freesound"
        if by_reference and not self._include_freesound:
            return None
        found = license_for_item(self.config, row.get("license_url"), only=only)
        if found is None:
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
        # Their terms: say "made using Openverse, not endorsed" wherever the sound is credited.
        lic.notice_text_required = self.config["notice"]
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
