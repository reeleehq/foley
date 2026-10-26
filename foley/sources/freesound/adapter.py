"""Freesound APIv2 retrieve adapter — CC0 sounds, stored strictly by-reference.

Freesound (report 01 §Freesound) is foley's anchor retrieve source. This adapter
turns a natural-language query into ranked, license-clean
:class:`~foley.base.Candidate`\\ s over the Freesound APIv2, honoring two
load-bearing constraints:

* **CC0-only (for #5), pushed into the query.** The CC0 filter is sent as the
  native ``filter=license:"Creative Commons 0"`` so non-CC0 sounds never leave the
  server; each returned item is *also* re-checked fail-closed against the
  ``accepted_license_ids`` allowlist — the server filter is a promise foley does
  not control, so a non-CC0 item that slips through is dropped, never indexed.
* **By-reference storage (TOS).** The Freesound API TOS forbids caching the audio
  bytes even for CC0, so every sound is licensed ``cache_bytes_ok=False`` (a
  per-item override on top of its own CC id — see
  :func:`~foley.sources.base.api_license`). foley keeps the stable sound-page URI
  + provenance + the CLAP vector; the bytes fetched here (a token-tier preview
  transcode) are transient — embedded once by :func:`~foley.index.ingest.ingest_one`,
  then discarded, never persisted.

HTTP is dependency-injected (a :class:`~foley.sources.http.Transport`), so the
adapter is fully testable with no network and ``import foley`` stays dol-only; the
real ``requests`` lives only behind
:func:`~foley.sources.http.requests_transport` (the ``foley[freesound]`` extra).
Ingestion (decode / QC / embed / tag / store) is NOT reimplemented here — the
:func:`foley.sources.pull.add_from` façade routes every hit through the shared
``ingest_one`` pipeline (it wraps the corpus machinery, it does not fork it).
"""

from __future__ import annotations

from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ...licensing import ai_scope_from_gen_ai_preference, license_id_from_cc_url
from ..base import api_license, resolve_source_key
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

#: Preview keys in the Freesound ``previews`` object, best (highest fidelity) first.
_PREVIEW_KEYS = (
    "preview-hq-mp3",
    "preview-hq-ogg",
    "preview-lq-mp3",
    "preview-lq-ogg",
)


def _raw_id(source_id: str) -> str:
    """Strip the ``freesound:`` namespace prefix (accept either id form)."""
    s = str(source_id)
    return s.split(":", 1)[1] if s.startswith("freesound:") else s


def _preview_url(item: dict) -> Optional[str]:
    """The best available preview URL for a sound item (token-tier, public CDN)."""
    previews = item.get("previews") or {}
    for key in _PREVIEW_KEYS:
        if previews.get(key):
            return previews[key]
    return None


def _safe_detail(resp) -> str:
    """Best-effort extract of the Freesound error ``detail`` (never raises)."""
    try:
        body = resp.json()
    except Exception:
        return "<no detail>"
    if isinstance(body, dict):
        return str(body.get("detail", body))
    return str(body)


class FreesoundAdapter:
    """Live Freesound APIv2 retrieve adapter (a :class:`~foley.sources.base.SourceAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (defaults to the module's). Passed positionally
            by the registry's lazy loader (the arioso ``Adapter(config)`` convention).
        api_key: The Freesound token. Defaults to ``$FREESOUND_API_KEY``.
        http: The injected :class:`~foley.sources.http.Transport` (defaults to
            :func:`~foley.sources.http.requests_transport`); tests pass a fake.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        api_key: Optional[str] = None,
        http: Optional[Transport] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        self._api_key = api_key
        self._http: Transport = http if http is not None else requests_transport
        # id -> preview URL, populated as search hits are parsed, so a subsequent
        # download(id) needs no extra sound-instance round-trip (the pull path calls
        # download with only the id — the SourceAdapter contract).
        self._preview_cache: "dict[str, str]" = {}

    # -- auth / http helpers ------------------------------------------------

    @property
    def api_key(self) -> str:
        """The Freesound token (constructor, else a bound key, else ``$FREESOUND_API_KEY``)."""
        return resolve_source_key(self.config, self._api_key)

    def _headers(self) -> dict:
        scheme = self.config["auth"].get("scheme", "Token ")
        return {"Authorization": f"{scheme}{self.api_key}"}

    def _url(self, path: str) -> str:
        return self.config["api"]["base_url"] + path

    def _get_json(self, url: str, *, params: Optional[dict] = None):
        resp = self._http("GET", url, params=params, headers=self._headers())
        if resp.status_code != 200:
            raise RuntimeError(
                f"Freesound GET {url} -> {resp.status_code}: {_safe_detail(resp)}"
            )
        return resp.json()

    def _get_bytes(self, url: str) -> bytes:
        resp = self._http("GET", url, params=None, headers=self._headers())
        if resp.status_code != 200:
            raise RuntimeError(f"Freesound byte fetch {url} -> {resp.status_code}")
        return resp.content

    # -- SourceAdapter surface ----------------------------------------------

    def search(
        self,
        query: str,
        *,
        license: str = "cc0",
        k: int = 15,
        duration_range: "Optional[tuple[float, float]]" = None,
        sort: Optional[str] = None,
        **kw,
    ) -> "list[Candidate]":
        """Search Freesound for ``query``; return license-clean candidates.

        The ``license='cc0'`` filter is pushed into the native Solr ``filter`` so
        non-CC0 sounds never leave the server; every returned item is still
        re-checked fail-closed before it becomes a candidate.

        Args:
            license: License constraint. ``'cc0'`` (default) sends the CC0 filter;
                ``None`` sends none (the per-item guard still enforces the
                ``accepted_license_ids`` allowlist, so results stay CC0 for #5).
            k: Max results (Freesound caps ``page_size`` at 150).
            duration_range: Optional ``(min_s, max_s)`` native duration filter.
            sort: Optional native sort key (default: Freesound relevance).
            **kw: Ignored extra affordances (``on_unsupported_param='warn'``).

        Returns:
            Up to ``k`` :class:`~foley.base.Candidate`\\ s (``origin=retrieved``),
            each carrying a by-reference :class:`~foley.base.LicenseRecord` and a
            transient ``preview_uri``.
        """
        params: dict = {
            "query": query,
            "fields": self.config["fields"],
            "page_size": min(int(k), 150),
        }
        filters: "list[str]" = []
        if license == "cc0":
            filters.append(self.config["param_map"]["license"]["to_native"])
        if duration_range is not None:
            lo, hi = duration_range
            filters.append(
                self.config["param_map"]["duration_range"]["to_native"].format(
                    lo=lo, hi=hi
                )
            )
        if filters:
            params["filter"] = " ".join(filters)
        if sort is not None:
            params["sort"] = sort

        data = self._get_json(
            self._url(self.config["api"]["search_endpoint"]["path"]), params=params
        )
        candidates: "list[Candidate]" = []
        for item in data.get("results", []):
            cand = self._candidate_from_item(item)
            if cand is not None:  # None => fail-closed drop (non-accepted license)
                candidates.append(cand)
        return candidates

    def get(self, source_id: str) -> SoundRecord:
        """Resolve one Freesound id (``'12345'`` or ``'freesound:12345'``) to a record.

        Raises:
            LookupError: If the sound's license is not in the accepted allowlist.
        """
        rid = _raw_id(source_id)
        path = self.config["api"]["sound_endpoint"]["path"].format(id=rid)
        item = self._get_json(self._url(path))
        cand = self._candidate_from_item(item)
        if cand is None:
            raise LookupError(
                f"Freesound sound {rid} has a non-accepted license; refused (fail-closed)."
            )
        return cand.sound

    def download(self, source_id: str, *, preview_url: Optional[str] = None) -> bytes:
        """Return a sound's transient preview bytes (token-tier; never cached).

        Args:
            source_id: The Freesound id (either id form).
            preview_url: Optional known preview URL (from a prior search hit) — used
                directly to save a round-trip; otherwise the sound instance is
                fetched to resolve it.

        Returns:
            The preview audio bytes (embedded once, then discarded — see the
            by-reference storage contract).

        Raises:
            LookupError: If the sound exposes no preview.
        """
        rid = _raw_id(source_id)
        url = preview_url or self._preview_cache.get(rid)
        if url is None:  # not from a prior search hit -> resolve via the instance
            path = self.config["api"]["sound_endpoint"]["path"].format(id=rid)
            url = _preview_url(self._get_json(self._url(path)))
        if not url:
            raise LookupError(f"Freesound sound {rid} exposes no downloadable preview.")
        return self._get_bytes(url)

    # -- item -> license-checked Candidate ----------------------------------

    def _candidate_from_item(self, item: dict) -> "Optional[Candidate]":
        """Build a license-checked :class:`~foley.base.Candidate` (None => drop).

        The per-item fail-closed guard: an item whose license is unverified or not
        in ``accepted_license_ids`` returns ``None`` (dropped, never indexed) even
        if the server-side filter returned it. Every kept item gets a
        by-reference :class:`~foley.base.LicenseRecord` (``cache_bytes_ok=False``)
        and a short, case-stable ``freesound:<id>`` canonical id.
        """
        raw_id = item.get("id")
        if raw_id is None:
            return None
        license_id, verified = license_id_from_cc_url(item.get("license"))
        accepted = self.config["license"]["accepted_license_ids"]
        if not verified or license_id not in accepted:
            return None  # fail-closed: never index a non-accepted-license sound

        overrides = {"cache_bytes_ok": False}  # TOS: by-reference even for CC0
        # Honor the uploader's AI-use preference (all four values, #69): CLAP-
        # embedding + persisting IS AI use, so ingest_one's gate reads the scope
        # (ai_use_permitted) and 'no-gen-ai' also clears ai_training_ok.
        preference = item.get("gen_ai_preference")
        ai_ok, ai_scope = ai_scope_from_gen_ai_preference(preference)
        if ai_ok is not None:
            overrides["ai_training_ok"] = ai_ok

        page = item.get("url") or f"https://freesound.org/s/{raw_id}/"
        lic = api_license(
            source="freesound",
            source_id=str(raw_id),
            source_url=page,  # stable human page = the by-reference re-fetch handle
            license_url=item.get("license"),  # the CC URL/label as served
            license_id=license_id,
            rights_verified=verified,  # True — required or keep() rejects
            creator_name=item.get("username"),
            overrides=overrides,
        )
        lic.gen_ai_preference = preference
        lic.ai_training_scope = ai_scope
        record = SoundRecord(
            id=f"freesound:{raw_id}",  # short, case-stable, no URL
            uri=page,
            license=lic,
            caption=item.get("name"),
            tags=sorted({str(t) for t in item.get("tags", []) if t}),
            duration_s=item.get("duration"),
        )
        preview = _preview_url(item)
        if preview:  # remember it so download(id) needs no extra instance fetch
            self._preview_cache[str(raw_id)] = preview
        return Candidate(
            sound=record,
            origin=CandidateOrigin.retrieved,
            preview_uri=preview,
        )


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = FreesoundAdapter
