"""Freesound APIv2 retrieve adapter — CC0 (and CC-BY) sounds, stored strictly by-reference.

Freesound (report 01 §Freesound) is foley's anchor retrieve source. This adapter
turns a natural-language query into ranked, license-clean
:class:`~foley.base.Candidate`\\ s over the Freesound APIv2, honoring two
load-bearing constraints:

* **CC0 by default, CC-BY on request, pushed into the query.** The CC0 filter is sent
  as the native ``filter=license:"Creative Commons 0"`` so other sounds never leave the
  server (a ``license`` other than CC0 also asks for ``"Attribution"``: the
  credit-bearing sounds the :func:`~foley.licensing.keep` gate then admits only for a
  caller that can attribute). Each returned item is *also* re-checked fail-closed
  against the ``accepted_license_ids`` allowlist — the server filter is a promise foley
  does not control, so an NC / SA / ND item that slips through is dropped, never indexed.
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

import re
from typing import Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ...licensing import ai_scope_from_gen_ai_preference, wanted_license_ids
from ..base import (
    api_license,
    merge_provider_params,
    native_choice,
    SearchArgumentError,
    page_size,
    paging_params,
    provider_params_policy,
    resolve_source_key,
)
from .._license_gate import is_cc0_only, license_for_item
from ..http import Transport, requests_transport
from .config import SOURCE_CONFIG

#: A double-quoted Solr phrase (a backslash escapes), blanked before a field is looked for.
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"')

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


def _bst_category(config: dict, ucs_category: str) -> Optional[str]:
    """The Broad Sound Taxonomy top-level name for a UCS CatID or category, else ``None``.

    Only the categories the config maps. ``None`` (no pre-filter) for anything else: a
    coarse pre-filter must never hide sounds on a guess.
    """
    from ...index.taxonomy import default_ucs_table

    row = default_ucs_table().get(ucs_category)
    category = (row.category if row is not None else ucs_category).upper()
    return config["param_map"]["ucs_category"]["bst_category_by_ucs_category"].get(
        category
    )


def _category_filter(
    config: dict, kind: str, ucs_category: Optional[str]
) -> Optional[str]:
    """The one Broad Sound Taxonomy top level to pre-filter on (``kind``, ``ucs_category``).

    Both narrow the same ``category`` field, so two different top levels could only
    match nothing: that raises :class:`~foley.sources.base.SearchArgumentError`
    (#169). The same one from both is sent once.
    """
    by_kind = config["param_map"]["kind"]["bst_category"].get(kind)
    by_ucs = _bst_category(config, ucs_category) if ucs_category else None
    if by_kind and by_ucs and by_kind != by_ucs:
        raise SearchArgumentError(
            f"kind={kind!r} asks for Freesound's {by_kind!r} category but "
            f"ucs_category={ucs_category!r} for {by_ucs!r}: a sound has one, so the "
            "two together match nothing; pass one of them"
        )
    return by_kind or by_ucs


def _check_provider_category(
    config: dict, category: Optional[str], provider_filter
) -> None:
    """Refuse a provider ``filter`` with its own category clause when foley sends one.

    The two would be ANDed, and a sound has one top level, so a different one could
    only match nothing (#181), as :func:`_category_filter` refuses for ``kind`` and
    ``ucs_category``. Quoted phrases are not read as clauses.

    >>> from foley.sources.freesound.config import SOURCE_CONFIG as cfg
    >>> _check_provider_category(cfg, "Music", 'tag:"category:x" subcategory:y')
    >>> _check_provider_category(cfg, None, 'category:"Soundscapes"')
    >>> _check_provider_category(cfg, "Music", '-category:"Soundscapes"')
    Traceback (most recent call last):
    ...
    foley.sources.base.SearchArgumentError: provider_params['filter'] names a category, but foley already filters on category:"Music" (from kind= or ucs_category=): pass the category in one place
    """
    if not category or not provider_filter:
        return
    template = config["param_map"]["ucs_category"]["to_native"]
    field = template.split(":", 1)[0]
    if re.search(
        rf"(?<![\w.]){re.escape(field)}\s*:", _QUOTED.sub('""', str(provider_filter))
    ):
        raise SearchArgumentError(
            f"provider_params['filter'] names a {field}, but foley already filters "
            f"on {template.format(category=category)} (from kind= or ucs_category=): "
            f"pass the {field} in one place"
        )


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
        license: Optional[str] = "cc0",
        k: int = 15,
        duration_range: "Optional[tuple[float, float]]" = None,
        sort: Optional[str] = None,
        page: int = 1,
        kind: str = "sfx",
        similar_to: Optional[str] = None,
        ucs_category: Optional[str] = None,
        provider_params: Optional[dict] = None,
        **kw,
    ) -> "list[Candidate]":
        """Search Freesound for ``query``; return license-clean candidates.

        The license filter is pushed into the native Solr ``filter`` so other sounds
        never leave the server; every returned item is still re-checked fail-closed
        before it becomes a candidate.

        Args:
            license: A licence id (``'cc0'`` is an alias for CC0-1.0, ``'cc-by'`` keeps
                the CC-BY ids). ``'cc0'`` (default) sends the CC0 filter; another id asks
                for CC0 + Attribution; ``None`` sends no filter. Whatever the filter, only
                items under the asked id (and the ``accepted_license_ids`` allowlist) are
                kept, so NC / SA / ND never come back.
            k: Max results (Freesound caps ``page_size`` at 150).
            duration_range: Optional ``(min_s, max_s)`` native duration filter.
            sort: ``relevance`` (default) | ``newest`` | ``popular`` | ``duration``,
                translated to Freesound's native key.
            page: The results page (1-based, ``k`` per page).
            kind: ``sfx`` (default, no filter) or ``music`` (the Broad Sound
                Taxonomy's "Music" top level). With a ``ucs_category`` that maps to
                another top level it raises ``SearchArgumentError`` (nothing could match).
            similar_to: A Freesound sound id (either id form): "more like this one".
            ucs_category: A UCS CatID or category, mapped to a coarse Broad Sound
                Taxonomy ``category`` pre-filter (no filter if it is not recognised;
                ``SearchArgumentError`` if ``kind`` asks for another top level).
            provider_params: Native Freesound search params foley has no affordance
                for, merged over the translated ones (#61), e.g.
                ``{"filter": "ac_brightness:[50 TO 100]"}``. Per the config's
                ``provider_params`` policy, a ``filter`` is appended to foley's as one
                group (the licence filter cannot be replaced or widened, and a
                category clause is refused when ``kind`` / ``ucs_category`` already
                send one), ``fields`` are
                appended to foley's (the licence fields cannot be dropped), and
                ``query`` is refused; the per-item licence re-check still applies.
            **kw: Ignored extra affordances (``on_unsupported_param='warn'``).

        Returns:
            Up to ``k`` :class:`~foley.base.Candidate`\\ s (``origin=retrieved``),
            each carrying a by-reference :class:`~foley.base.LicenseRecord`, a
            transient ``preview_uri`` and the item JSON it was parsed from as ``raw``.
        """
        params: dict = {
            "query": query,
            "fields": self.config["fields"],
            "page_size": page_size(self.config, k),
        }
        only = wanted_license_ids(self.config, license)
        if only == []:  # a licence this source does not accept: nothing can match
            return []
        filters: "list[str]" = []
        license_map = self.config["param_map"]["license"]
        if is_cc0_only(self.config, only):
            filters.append(license_map["to_native"])
        elif only is not None:
            filters.append(license_map["to_native_attribution"])
        pm = self.config["param_map"]
        category = _category_filter(self.config, kind, ucs_category)
        if category:
            filters.append(pm["ucs_category"]["to_native"].format(category=category))
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
            params["sort"] = native_choice(self.config, "sort", sort)
        params.update(paging_params(self.config, page, params["page_size"]))
        if similar_to:
            native = self.config["param_map"]["similar_to"]["native_name"]
            params[native] = _raw_id(similar_to)
        params = merge_provider_params(
            params, provider_params, policy=provider_params_policy(self.config)
        )
        _check_provider_category(
            self.config, category, (provider_params or {}).get("filter")
        )

        data = self.invoke_native(
            self.config["api"]["search_endpoint"]["path"], **params
        )
        candidates: "list[Candidate]" = []
        for item in data.get("results", []):
            cand = self._candidate_from_item(item, only=only)
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

    def invoke_native(self, path: str, **params):
        """GET a Freesound APIv2 ``path`` with native ``params``; return the parsed JSON.

        The public escape hatch below foley's translation (#61), e.g.
        ``invoke_native("/search/", query="rain", filter="ac_brightness:[50 TO 100]")``.
        It bypasses the licence filter and the per-item licence re-check that
        :meth:`search` applies: the caller owns licence gating for what it gets back
        (and the dispatch layer's egress check is not run either).

        Raises:
            RuntimeError: On a non-200 response (with Freesound's ``detail``).
        """
        return self._get_json(self._url(path), params=params or None)

    # -- item -> license-checked Candidate ----------------------------------

    def _candidate_from_item(
        self, item: dict, *, only: "Optional[list[str]]" = None
    ) -> "Optional[Candidate]":
        """Build a license-checked :class:`~foley.base.Candidate` (None => drop).

        The per-item fail-closed guard: an item whose license is unverified or not
        in ``accepted_license_ids`` returns ``None`` (dropped, never indexed) even
        if the server-side filter returned it (``only`` narrows the allowlist for a
        CC0-only search). Every kept item gets a
        by-reference :class:`~foley.base.LicenseRecord` (``cache_bytes_ok=False``)
        and a short, case-stable ``freesound:<id>`` canonical id.
        """
        raw_id = item.get("id")
        if raw_id is None:
            return None
        found = license_for_item(self.config, item.get("license"), only=only)
        if found is None or not found[1]:
            return None  # fail-closed: never index a non-accepted-license sound
        license_id, verified = found

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
        cand = Candidate(
            sound=record,
            origin=CandidateOrigin.retrieved,
            preview_uri=preview,
        )
        cand.raw = item  # transient (never serialized): the vendor fields foley skips
        return cand


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = FreesoundAdapter
