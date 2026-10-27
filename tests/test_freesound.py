"""Tests for the Freesound live retrieve adapter + the add_from pull facade (#5).

Hermetic: HTTP is dependency-injected, so every test runs with a
:class:`FakeTransport` returning canned Freesound JSON / bytes — **no network, no
``requests``**. The ``add_from`` keystone decodes real (FLAC) preview bytes and
embeds them with the deterministic ``FakeEmbedder`` (conftest), so the whole
search -> license-gate -> download -> ingest -> by-reference-store path is proven
without CLAP/torch.

The load-bearing assertions: the CC0 filter is pushed into the query; a non-CC0
item that slips past the server filter is dropped fail-closed; ids are minted as
``freesound:<n>`` (never a URL); and an ingested Freesound sound is stored
BY-REFERENCE (no bytes cached, ``cache_bytes_ok=False``, URI + vector only).
"""

import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")  # add_from decodes/encodes real audio bytes

from foley.audio import encode  # noqa: E402
from foley.base import AcquisitionMethod, CandidateOrigin, StorageMode  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.sources import add_from, register_source  # noqa: E402
from foley.sources.base import SourceAdapter  # noqa: E402
from foley.sources.freesound import SOURCE_CONFIG, FreesoundAdapter  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY, discover_sources  # noqa: E402

SR = 48_000


# ---------------------------------------------------------------------------
# audio + HTTP test doubles (no soundfile-encoded bytes on the wire, no requests)
# ---------------------------------------------------------------------------


def _tone(freq=440.0, seconds=1.0, amp=0.5):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _flac(samples):
    return encode(samples, SR)


#: A public CDN preview URL (token-tier; the embedding substitute for #5).
CDN_URL = "https://cdn.freesound.org/previews/12/12345-hq.mp3"

#: One CC0 Freesound sound item (license as a CC URL — exercises the shared mapper).
SOUND_12345 = {
    "id": 12345,
    "name": "rain on window",
    "license": "http://creativecommons.org/publicdomain/zero/1.0/",
    "username": "alice",
    "tags": ["rain", "window", "storm"],
    "description": "gentle rain on a window pane",
    "duration": 6.2,
    "previews": {"preview-hq-mp3": CDN_URL},
    "url": "https://freesound.org/s/12345/",
    "type": "wav",
}
SEARCH_PAGE = {"count": 1, "next": None, "previous": None, "results": [SOUND_12345]}


def _non_cc0_item(license_value):
    """A copy of the CC0 item with a different license (id 999)."""
    item = dict(SOUND_12345)
    item.update(id=999, license=license_value, url="https://freesound.org/s/999/")
    return item


@dataclass
class FakeResponse:
    """A structural :class:`foley.sources.http.Response` (no requests)."""

    status_code: int = 200
    _payload: Any = None
    content: bytes = b""

    def json(self):
        if self._payload is None:
            raise ValueError("response has no JSON body")
        return self._payload


class FakeTransport:
    """Records calls; returns the first route whose needle is a substring of the URL."""

    def __init__(self, routes):
        self.routes = routes  # list[(needle, FakeResponse)]
        self.calls = []

    def __call__(self, method, url, *, params=None, headers=None):
        self.calls.append(
            SimpleNamespace(method=method, url=url, params=params or {}, headers=headers or {})
        )
        for needle, resp in self.routes:
            if needle in url:
                return resp
        return FakeResponse(404, {"detail": "not found"}, b"")


def _transport(*, download_bytes=None, item=SOUND_12345, search_page=SEARCH_PAGE):
    """A FakeTransport wired for search + sound-instance + preview-CDN routes."""
    data = download_bytes if download_bytes is not None else _flac(_tone(440))
    return FakeTransport(
        [
            ("/search/text/", FakeResponse(200, search_page, b"")),
            ("cdn.freesound.org", FakeResponse(200, None, data)),  # preview bytes
            (f"/sounds/{item['id']}/", FakeResponse(200, item, b"")),  # instance
        ]
    )


@pytest.fixture
def library(fake_embedder):
    """A fresh in-memory FakeEmbedder-backed library (no CLAP, no disk)."""
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _adapter(transport, *, config=None):
    return FreesoundAdapter(config, api_key="test-token", http=transport)


# ---------------------------------------------------------------------------
# (a) search parses CC0 candidates
# ---------------------------------------------------------------------------


def test_search_cc0_parses_candidates():
    adapter = _adapter(_transport())
    cands = adapter.search("rain", license="cc0", k=10)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.origin == CandidateOrigin.retrieved
    assert cand.sound.id == "freesound:12345"
    lic = cand.sound.license
    assert lic.license_id == "CC0-1.0"
    assert lic.source == "freesound"
    assert lic.source_id == "12345"
    assert lic.source_url == "https://freesound.org/s/12345/"
    assert lic.rights_verified is True
    assert lic.cache_bytes_ok is False  # by-reference override
    assert cand.preview_uri == CDN_URL


# ---------------------------------------------------------------------------
# (b) the CC0 filter is actually sent (into the query), path comes from config
# ---------------------------------------------------------------------------


def test_cc0_filter_is_pushed_into_the_query():
    transport = _transport()
    _adapter(transport).search("rain", license="cc0")
    call = transport.calls[0]
    assert 'license:"Creative Commons 0"' in call.params["filter"]
    # asserted against config, never a hard-coded literal (endpoint is SSOT-owned)
    assert SOURCE_CONFIG["api"]["search_endpoint"]["path"] in call.url
    assert call.headers["Authorization"].startswith("Token ")


def test_duration_range_filter_is_native():
    transport = _transport()
    _adapter(transport).search("rain", license=None, duration_range=(1.0, 8.0))
    flt = transport.calls[0].params["filter"]
    assert "duration:[1.0 TO 8.0]" in flt
    assert "license:" not in flt  # license=None => no license filter sent


# ---------------------------------------------------------------------------
# (c) get + download flow
# ---------------------------------------------------------------------------


def test_get_resolves_record_and_download_returns_preview_bytes():
    payload = _flac(_tone(330))
    transport = _transport(download_bytes=payload)
    adapter = _adapter(transport)

    rec = adapter.get("freesound:12345")
    assert rec.id == "freesound:12345"
    assert rec.license.license_id == "CC0-1.0"
    assert {"rain", "window"}.issubset(set(rec.tags))
    assert rec.uri == "https://freesound.org/s/12345/"

    # download without a known preview URL resolves it via the instance, then fetches
    got = adapter.download("12345")
    assert got == payload
    assert transport.calls[-1].url == CDN_URL
    assert transport.calls[-1].headers["Authorization"].startswith("Token ")


def test_download_uses_known_preview_url_without_extra_instance_fetch():
    transport = _transport()
    adapter = _adapter(transport)
    adapter.download("12345", preview_url=CDN_URL)
    # only the CDN was hit — no /sounds/12345/ instance round-trip
    assert transport.calls[-1].url == CDN_URL
    assert all("/sounds/12345/" not in c.url for c in transport.calls)


# ---------------------------------------------------------------------------
# (d) KEYSTONE — add_from indexes the sound BY-REFERENCE
# ---------------------------------------------------------------------------


def test_add_from_indexes_by_reference(library):
    transport = _transport()
    adapter = _adapter(transport)
    report = add_from("freesound", query="rain", library=library, adapter=adapter, limit=5)

    assert len(report.ingested) == 1
    rec = report.ingested[0].record
    assert rec.id == "freesound:12345"

    # BY-REFERENCE: no bytes cached, but a provenance hash + fetchable uri are set
    assert rec.storage_mode == StorageMode.by_reference
    assert len(library.sounds) == 0
    assert rec.content_sha256 is not None
    assert rec.content_sha256 not in library.sounds
    assert rec.uri == "https://freesound.org/s/12345/"

    lic = rec.license
    assert lic.cache_bytes_ok is False
    assert lic.redistribute_standalone_ok is True  # CC0 copyright allows it...
    assert lic.commercial_ok is True
    assert lic.ai_training_ok is True
    assert lic.source == "freesound"
    assert lic.source_id == "12345"
    assert lic.acquisition_method == AcquisitionMethod.api

    # ...yet it IS retrievable: the vector was indexed (retrieval-first)
    assert rec.embedding_ref == rec.id
    hits = library.search("rain window", k=3)
    assert hits and hits[0].sound.id == rec.id

    # the bytes are NOT locally available (a remote by-reference sound)
    with pytest.raises(LookupError):
        library.audio(rec.id)


# ---------------------------------------------------------------------------
# (e) fail-closed: a non-CC0 item that slips past the server filter is dropped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "license_value",
    [
        "https://creativecommons.org/licenses/by-sa/4.0/",  # -> unknown
        "https://creativecommons.org/licenses/by-nc/4.0/",  # -> CC-BY-NC (not accepted)
        "https://creativecommons.org/licenses/by/4.0/",  # -> CC-BY (only on request, #78)
    ],
)
def test_non_cc0_is_dropped_fail_closed(library, license_value):
    page = {"count": 1, "results": [_non_cc0_item(license_value)]}
    transport = _transport(item=_non_cc0_item(license_value), search_page=page)
    adapter = _adapter(transport)

    # search-level per-item guard: never becomes a candidate
    assert adapter.search("rain", license="cc0") == []

    # add_from-level: nothing embedded or stored
    report = add_from("freesound", query="rain", library=library, adapter=adapter)
    assert report.ingested == []
    assert len(library.sounds) == 0
    assert len(library) == 0


def test_keep_gate_drops_accepted_but_noncommercial(library):
    """Layer-2 defense: a license on the allowlist but failing intended-use is skipped."""
    # widen the allowlist to admit CC-BY-NC past the per-item guard...
    config = dict(SOURCE_CONFIG)
    config["license"] = dict(SOURCE_CONFIG["license"], accepted_license_ids=["CC0-1.0", "CC-BY-NC-4.0"])
    item = _non_cc0_item("https://creativecommons.org/licenses/by-nc/4.0/")
    page = {"count": 1, "results": [item]}
    adapter = _adapter(_transport(item=item, search_page=page), config=config)

    # ...it survives search, but add_from's fail-closed keep(commercial) drops it
    assert len(adapter.search("rain", license=None)) == 1
    report = add_from(
        "freesound", query="rain", license=None, library=library, adapter=adapter
    )
    assert [r.status for r in report.results] == ["skipped_license"]
    assert len(library.sounds) == 0


# ---------------------------------------------------------------------------
# (f) ids are namespaced, never a URL or a content hash
# ---------------------------------------------------------------------------


def test_id_is_namespaced_not_url_or_hash(library):
    adapter = _adapter(_transport())
    cand = adapter.search("rain")[0]
    assert cand.sound.id == "freesound:12345"
    assert "http" not in cand.sound.id
    report = add_from("freesound", query="rain", library=library, adapter=adapter)
    assert report.ingested[0].record.id == "freesound:12345"  # not a PCM hash


# ---------------------------------------------------------------------------
# (g) registry auto-discovery + register_source round-trip + protocol conformance
# ---------------------------------------------------------------------------


def test_registry_autodiscovers_freesound():
    discover_sources()
    assert "freesound" in SOURCE_REGISTRY
    assert SOURCE_REGISTRY["freesound"]["config"]["kind"] == "retrieve"


def test_register_source_round_trip():
    sentinel = object()
    register_source("dummy_src", {"name": "dummy_src", "kind": "retrieve"}, sentinel)
    assert SOURCE_REGISTRY["dummy_src"]["adapter"] is sentinel
    del SOURCE_REGISTRY["dummy_src"]  # keep global registry clean for other tests


def test_freesound_adapter_satisfies_source_protocol():
    assert isinstance(_adapter(_transport()), SourceAdapter)


# ---------------------------------------------------------------------------
# hermeticity guards — the fake path never imports/uses requests
# ---------------------------------------------------------------------------


def test_fake_path_never_calls_requests_transport(monkeypatch):
    import foley.sources.http as http_mod

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("requests_transport was called on the injected-fake path")

    monkeypatch.setattr(http_mod, "requests_transport", boom)
    adapter = _adapter(_transport())
    assert adapter.search("rain")  # works entirely on the injected FakeTransport


def test_importing_freesound_does_not_import_requests():
    # a fresh interpreter: importing the adapter package must stay dol-only
    code = "import foley.sources.freesound, sys; assert 'requests' not in sys.modules"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    adapter = FreesoundAdapter(http=_transport())  # no api_key, no env var
    with pytest.raises(RuntimeError, match="FREESOUND_API_KEY"):
        adapter.search("rain")


# ---------------------------------------------------------------------------
# the LIVE label-string license form (search API returns a label, not a URL)
# ---------------------------------------------------------------------------


def test_search_maps_label_form_license():
    item = dict(SOUND_12345, license="Creative Commons 0")  # the live search label form
    adapter = _adapter(_transport(item=item, search_page={"count": 1, "results": [item]}))
    cands = adapter.search("rain", license="cc0")
    assert len(cands) == 1
    assert cands[0].sound.license.license_id == "CC0-1.0"
    assert cands[0].sound.license.rights_verified is True


@pytest.mark.parametrize("label", ["Attribution", "Attribution NonCommercial", "Sampling+"])
def test_label_form_non_cc0_is_dropped_fail_closed(label):
    item = _non_cc0_item(label)
    adapter = _adapter(_transport(item=item, search_page={"count": 1, "results": [item]}))
    assert adapter.search("rain", license="cc0") == []


# ---------------------------------------------------------------------------
# HTTP error paths + missing preview
# ---------------------------------------------------------------------------


def test_search_non_200_raises_with_detail():
    transport = FakeTransport(
        [("/search/text/", FakeResponse(429, {"detail": "Rate limit exceeded"}, b""))]
    )
    with pytest.raises(RuntimeError, match="429"):
        _adapter(transport).search("rain")


def test_download_missing_preview_raises_lookup():
    item = dict(SOUND_12345, previews={})  # sound instance exposes no preview
    adapter = _adapter(_transport(item=item, search_page={"count": 1, "results": [item]}))
    with pytest.raises(LookupError):
        adapter.download("12345")


def test_download_non_200_bytes_raises_runtime():
    transport = FakeTransport(
        [
            ("/sounds/12345/", FakeResponse(200, SOUND_12345, b"")),
            ("cdn.freesound.org", FakeResponse(500, None, b"")),
        ]
    )
    with pytest.raises(RuntimeError, match="500"):
        _adapter(transport).download("12345")


# ---------------------------------------------------------------------------
# add_from batch resilience + stable-id dedup on re-pull
# ---------------------------------------------------------------------------


def test_add_from_undecodable_200_bytes_is_error_not_crash(library):
    # a preview URL that returns HTTP 200 but non-audio bytes (HTML error page,
    # truncated audio) must be recorded as an error, never crash the whole pull.
    adapter = _adapter(_transport(download_bytes=b"NOT_AUDIO_BYTES" * 20))
    report = add_from("freesound", query="rain", library=library, adapter=adapter)
    assert [r.status for r in report.results] == ["error"]
    assert len(library.sounds) == 0 and len(library) == 0


def test_add_from_one_bad_hit_does_not_abort_batch(library):
    bad = dict(
        SOUND_12345,
        id=777,
        url="https://freesound.org/s/777/",
        previews={"preview-hq-mp3": "https://cdn.freesound.org/previews/77/777-bad.mp3"},
    )
    page = {"count": 2, "results": [bad, SOUND_12345]}
    transport = FakeTransport(
        [
            ("/search/text/", FakeResponse(200, page, b"")),
            ("777-bad.mp3", FakeResponse(404, {"detail": "gone"}, b"")),  # bad hit 404s
            ("cdn.freesound.org", FakeResponse(200, None, _flac(_tone(440)))),  # good hit
        ]
    )
    report = add_from("freesound", query="rain", library=library, adapter=_adapter(transport))
    assert "error" in {r.status for r in report.results}  # the bad hit recorded
    assert len(report.ingested) == 1  # the good hit still stored
    assert report.ingested[0].record.id == "freesound:12345"


def test_add_from_search_error_returns_report_not_exception(library):
    transport = FakeTransport(
        [("/search/text/", FakeResponse(429, {"detail": "throttled"}, b""))]
    )
    report = add_from("freesound", query="rain", library=library, adapter=_adapter(transport))
    assert [r.status for r in report.results] == ["error"]  # inspectable, not raised
    assert len(library) == 0


def test_add_from_second_pull_dedups_on_stable_id(library):
    adapter = _adapter(_transport())
    r1 = add_from("freesound", query="rain", library=library, adapter=adapter)
    assert r1.ingested and r1.results[0].status in ("pass", "warn")
    r2 = add_from("freesound", query="rain", library=library, adapter=adapter)
    assert [r.status for r in r2.results] == ["skipped_dup"]  # stable-id dedup
    assert len(library) == 1


# ---------------------------------------------------------------------------
# discovery stays light — importing config.py must not load adapter.py / requests
# ---------------------------------------------------------------------------


def test_discovery_config_import_stays_light():
    code = (
        "import importlib, sys; "
        "importlib.import_module('foley.sources.freesound.config'); "
        "assert 'foley.sources.freesound.adapter' not in sys.modules, 'adapter eagerly loaded'; "
        "assert 'requests' not in sys.modules, 'requests eagerly loaded'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# CC-BY admitted when the caller can attribute (#78): SA / ND / NC stay out
# ---------------------------------------------------------------------------

BY_4 = "https://creativecommons.org/licenses/by/4.0/"


def _by_item(license_value=BY_4, id_=777):
    item = dict(SOUND_12345)
    item.update(id=id_, license=license_value, url=f"https://freesound.org/s/{id_}/")
    return item


def test_attribution_search_asks_for_cc0_and_attribution_only():
    transport = _transport()
    _adapter(transport).search("rain", license="cc-by")
    flt = transport.calls[0].params["filter"]
    assert '"Creative Commons 0" OR "Attribution"' in flt
    assert "NonCommercial" not in flt


def test_cc_by_is_admitted_on_request_with_credit_fields():
    page = {"count": 1, "results": [_by_item()]}
    adapter = _adapter(_transport(item=_by_item(), search_page=page))
    (cand,) = adapter.search("rain", license="cc-by")
    lic = cand.sound.license
    assert lic.license_id == "CC-BY-4.0"
    assert lic.requires_attribution
    assert lic.cache_bytes_ok is False  # the TOS applies to every Freesound licence


def test_cc_by_is_not_returned_by_the_default_cc0_search():
    page = {"count": 1, "results": [_by_item()]}
    adapter = _adapter(_transport(item=_by_item(), search_page=page))
    assert adapter.search("rain") == []


@pytest.mark.parametrize(
    "license_value",
    [
        "https://creativecommons.org/licenses/by-sa/4.0/",
        "https://creativecommons.org/licenses/by-nd/4.0/",
        "https://creativecommons.org/licenses/by-nc/4.0/",
        "https://creativecommons.org/licenses/by-nc-sa/3.0/",
        "https://creativecommons.org/licenses/sampling+/1.0/",
        "https://creativecommons.org/licenses/by/2.0/de/",
    ],
)
def test_sa_nd_nc_and_ports_stay_fail_closed_even_when_attribution_is_asked(
    license_value,
):
    item = _by_item(license_value, id_=888)
    adapter = _adapter(_transport(item=item, search_page={"results": [item]}))
    assert adapter.search("rain", license="cc-by") == []
    assert adapter.search("rain", license=None) == []


def test_add_from_keeps_cc_by_only_for_a_caller_that_can_attribute(library):
    from foley.base import IntendedUse

    item = _by_item()
    adapter = _adapter(_transport(item=item, search_page={"results": [item]}))
    cannot = add_from(
        "freesound",
        query="rain",
        license="cc-by",
        intended_use=IntendedUse(commercial=True, publish=True, can_attribute=False),
        library=library,
        adapter=adapter,
    )
    assert [r.status for r in cannot.results] == ["skipped_license"]
    assert len(library.sounds) == 0

    can = add_from(
        "freesound", query="rain", license="cc-by", library=library, adapter=adapter
    )
    assert len(can.ingested) == 1
    rec = can.ingested[0].record
    assert rec.id == "freesound:777"
    assert rec.license.license_id == "CC-BY-4.0"
    assert rec.license.requires_attribution


def test_similar_to_sends_the_native_param_with_either_id_form():
    for given in ("12345", "freesound:12345"):
        transport = _transport()
        _adapter(transport).search("rain", similar_to=given)
        assert transport.calls[0].params["similar_to"] == "12345"
    transport = _transport()
    _adapter(transport).search("rain")
    assert "similar_to" not in transport.calls[0].params


@pytest.mark.parametrize(
    "ucs, bst",
    [
        ("AMBIENCE", "Soundscapes"),
        ("ambience", "Soundscapes"),
        ("MUSIC", "Music"),
    ],
)
def test_ucs_category_becomes_a_bst_category_prefilter(ucs, bst):
    transport = _transport()
    _adapter(transport).search("rain", ucs_category=ucs)
    assert f'category:"{bst}"' in transport.calls[0].params["filter"]


@pytest.mark.parametrize("ucs", ["NOPE", "WEATHRain", "WEATHER", "DOORS", 'x" OR a:"b'])
def test_an_unmapped_ucs_category_sends_no_prefilter(ucs):
    """Rain may be filed as a sound effect or a soundscape: no guess, no filter."""
    transport = _transport()
    _adapter(transport).search("rain", license=None, ucs_category=ucs)
    assert "filter" not in transport.calls[0].params


def test_the_new_affordances_flow_through_add_from(library):
    transport = _transport()
    add_from(
        "freesound",
        query="rain",
        similar_to="freesound:1",
        ucs_category="AMBIENCE",
        library=library,
        adapter=_adapter(transport),
    )
    params = transport.calls[0].params
    assert params["similar_to"] == "1"
    assert 'category:"Soundscapes"' in params["filter"]


def test_cc_by_3_0_is_admitted_and_get_resolves_a_cc_by_id():
    item = _by_item("http://creativecommons.org/licenses/by/3.0/", id_=555)
    adapter = _adapter(_transport(item=item, search_page={"results": [item]}))
    (cand,) = adapter.search("rain", license="cc-by")
    assert cand.sound.license.license_id == "CC-BY-3.0"
    assert adapter.get("freesound:555").license.license_id == "CC-BY-3.0"


# ---------------------------------------------------------------------------
# (#61) provider_params, raw, invoke_native
# ---------------------------------------------------------------------------

BRIGHT = "ac_brightness:[50 TO 100]"


def test_provider_params_filter_is_appended_and_licence_still_enforced():
    """Acceptance (#61): a Freesound-only filter passes without editing foley."""
    page = dict(SEARCH_PAGE, results=[SOUND_12345, _non_cc0_item(
        "http://creativecommons.org/licenses/by-nc/4.0/")])
    transport = _transport(search_page=page)
    cands = _adapter(transport).search(
        "rain", provider_params={"filter": BRIGHT, "group_by_pack": 1}
    )
    sent = transport.calls[0].params
    assert SOURCE_CONFIG["param_map"]["license"]["to_native"] in sent["filter"]
    assert BRIGHT in sent["filter"]  # both: the licence filter cannot be replaced
    assert sent["group_by_pack"] == 1  # any other native param passes through
    assert [c.sound.id for c in cands] == ["freesound:12345"]  # NC dropped, fail-closed


def test_provider_params_must_be_a_mapping():
    with pytest.raises(TypeError, match="provider_params"):
        _adapter(_transport()).search("rain", provider_params=[("filter", BRIGHT)])


def test_add_from_passes_provider_params_to_search(library):
    transport = _transport()
    report = add_from(
        "freesound",
        query="rain",
        library=library,
        adapter=_adapter(transport),
        provider_params={"filter": BRIGHT},
    )
    licence = SOURCE_CONFIG["param_map"]["license"]["to_native"]
    assert transport.calls[0].params["filter"] == f"{licence} ({BRIGHT})"
    assert report.ingested


def test_an_or_in_the_filter_stays_inside_the_and_clause():
    transport = _transport()
    _adapter(transport).search(
        "rain", provider_params={"filter": 'tag:x OR license:"Attribution NonCommercial"'}
    )
    licence = SOURCE_CONFIG["param_map"]["license"]["to_native"]
    assert transport.calls[0].params["filter"] == (
        f'{licence} (tag:x OR license:"Attribution NonCommercial")'
    )
    for escape in ("x) OR (license:*", 'x ")" ) OR (license:*', "x\\"):
        with pytest.raises(ValueError, match="unbalanced"):
            _adapter(_transport()).search("rain", provider_params={"filter": escape})


@pytest.mark.parametrize("fields", ["id,name", "", None, "id"])
def test_a_fields_override_cannot_drop_the_licence_fields(fields):
    """``fields`` is append-only: the licence and AI-preference fields always go."""
    transport = _transport()
    cands = _adapter(transport).search("rain", provider_params={"fields": fields})
    sent = transport.calls[0].params["fields"].split(",")
    required = SOURCE_CONFIG["fields"].split(",")
    assert sent[: len(required)] == required
    for name in ("id", "license", "gen_ai_preference", "username", "url", "previews"):
        assert name in required
    assert cands and cands[0].sound.license.gen_ai_preference == SOUND_12345.get(
        "gen_ai_preference"
    )


def test_add_from_raises_for_a_reserved_key_before_searching(library):
    transport = _transport()
    with pytest.raises(ValueError, match="provider_params\\['query'\\] is reserved"):
        add_from(
            "freesound",
            query="rain",
            library=library,
            adapter=_adapter(transport),
            provider_params={"query": "x"},
        )
    assert transport.calls == []


@pytest.mark.parametrize("key", ["query", "token"])
def test_reserved_search_params_raise(key):
    transport = _transport()
    with pytest.raises(ValueError, match=f"provider_params\\[{key!r}\\] is reserved"):
        _adapter(transport).search("rain", provider_params={key: "x"})
    assert transport.calls == []


def test_provider_params_keys_must_be_str():
    transport = _transport()
    with pytest.raises(TypeError, match="keys must be str"):
        _adapter(transport).search("rain", provider_params={1: "x"})
    assert transport.calls == []


def test_candidates_carry_the_item_json_as_transient_raw():
    cand = _adapter(_transport()).search("rain")[0]
    assert cand.raw == SOUND_12345
    assert "raw" not in cand.to_dict()  # never serialized into the meta store


def test_invoke_native_returns_the_parsed_json():
    transport = _transport()
    data = _adapter(transport).invoke_native("/search/text/", query="rain", filter=BRIGHT)
    assert data == SEARCH_PAGE
    assert transport.calls[0].params == {"query": "rain", "filter": BRIGHT}
    assert transport.calls[0].headers["Authorization"].endswith("test-token")


# ---------------------------------------------------------------------------
# license= is a licence id (#131)
# ---------------------------------------------------------------------------


def test_a_cc0_licence_id_keeps_cc0_only_and_sends_the_cc0_filter():
    page = {"count": 1, "results": [_by_item()]}
    transport = _transport(item=_by_item(), search_page=page)
    assert _adapter(transport).search("rain", license="CC0-1.0") == []
    flt = transport.calls[0].params["filter"]
    assert 'license:"Creative Commons 0"' in flt and "Attribution" not in flt


def test_a_cc_by_licence_id_keeps_that_licence_only():
    page = {"count": 1, "results": [_by_item()]}
    adapter = _adapter(_transport(item=_by_item(), search_page=page))
    got = adapter.search("rain", license="CC-BY-4.0")
    assert [c.sound.license.license_id for c in got] == ["CC-BY-4.0"]
    assert adapter.search("rain", license="CC-BY-3.0") == []


def test_license_none_admits_every_accepted_licence():
    page = {"count": 1, "results": [_by_item()]}
    adapter = _adapter(_transport(item=_by_item(), search_page=page))
    assert len(adapter.search("rain", license=None)) == 1


def test_a_cc_by_licence_id_asks_for_cc0_and_attribution_and_a_refused_one_sends_nothing():
    transport = _transport()
    adapter = _adapter(transport)
    adapter.search("rain", license="CC-BY-4.0")
    assert '"Attribution"' in transport.calls[0].params["filter"]
    assert adapter.search("rain", license="CC-BY-SA-4.0") == []
    assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# #75 slice C: the search vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sort, native",
    [("relevance", "score"), ("newest", "created_desc"),
     ("popular", "downloads_desc"), ("duration", "duration_asc")],
)
def test_canonical_sort_values_reach_freesound_natively(sort, native):
    transport = _transport()
    _adapter(transport).search("rain", sort=sort)
    assert transport.calls[0].params["sort"] == native


def test_page_and_kind_reach_freesound():
    transport = _transport()
    _adapter(transport).search("rain", page=3, kind="music")
    params = transport.calls[0].params
    assert params["page"] == 3 and 'category:"Music"' in params["filter"]
    transport = _transport()
    _adapter(transport).search("rain")  # page 1 and sfx send nothing, as before
    params = transport.calls[0].params
    assert "page" not in params and "category:" not in params.get("filter", "")


def test_search_vocabulary_is_validated_before_any_call():
    from foley.base import QUERY_AFFORDANCES
    from foley.sources._dispatch import translate_affordances

    for bad in ({"sort": "score"}, {"kind": "speech"}):
        with pytest.raises(ValueError, match="must be one of"):
            translate_affordances(SOURCE_CONFIG, bad, vocabulary=QUERY_AFFORDANCES)
    with pytest.raises(TypeError, match="text= was renamed query="):
        translate_affordances(SOURCE_CONFIG, {"text": "rain"}, vocabulary=QUERY_AFFORDANCES)
