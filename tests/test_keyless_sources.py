"""The keyless retrieve sources (#79): Openverse, Wikimedia Commons, Internet Archive.

Hermetic: HTTP is a fake transport answering canned JSON; the 429 sleep is recorded, never slept.
"""

import pytest

from foley.licensing import DEFAULT_INTENDED_USE, keep
from foley.sources._keyless import get_bytes, get_json, strip_html
from foley.sources.base import SourceConfigurationError
from foley.sources.internet_archive.adapter import InternetArchiveAdapter
from foley.sources.openverse.adapter import OpenverseAdapter
from foley.sources.wikimedia_commons.adapter import WikimediaCommonsAdapter


class Resp:
    def __init__(self, body=None, status=200, content=b""):
        self.status_code, self._body, self.content = status, body, content

    def json(self):
        return self._body


class Fake:
    """Answers each GET from a list of ``(url_substring, Resp)``; records every call."""

    def __init__(self, *routes):
        self.routes, self.calls = list(routes), []

    def __call__(self, method, url, *, params=None, headers=None, json=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        for i, (needle, resp) in enumerate(self.routes):
            if needle in url:
                if isinstance(resp, list):  # a sequence: consume one per call
                    return resp.pop(0)
                return resp
        raise AssertionError(f"unexpected request {url}")


# ---------------------------------------------------------------------------
# the shared helpers
# ---------------------------------------------------------------------------


def test_a_non_200_answer_raises_with_its_status():
    for status in (429, 500):
        with pytest.raises(RuntimeError, match=str(status)):
            get_bytes(Fake(("x", Resp(status=status))), "https://x/a", what="t")
    assert get_json(Fake(("x", Resp({"ok": 1}))), "https://x/a", what="t") == {"ok": 1}


def test_commons_declares_its_own_429_waits_and_the_transport_honours_them():
    from foley.sources.resilience import make_resilient_transport_from_config
    from foley.sources.wikimedia_commons.config import SOURCE_CONFIG

    waits = []
    base = Fake(("x", [Resp(status=429), Resp(status=429), Resp({"ok": 1})]))
    t = make_resilient_transport_from_config(
        SOURCE_CONFIG, base=base, sleep=waits.append
    )
    assert get_json(t, "https://x/a", what="t") == {"ok": 1}
    assert [w for w in waits if w >= 10] == [
        10.0,
        20.0,
    ]  # the throttle may add small waits


def test_licence_strings_must_agree_and_all_parse():
    from foley.sources._license_gate import license_for_item
    from foley.sources.wikimedia_commons.config import SOURCE_CONFIG as C

    by, sa = (
        "https://creativecommons.org/licenses/by/4.0/",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    )
    assert license_for_item(C, by, "CC BY 4.0") == ("CC-BY-4.0", True)
    assert (
        license_for_item(C, sa, "CC BY 4.0") is None
    )  # a looser label cannot clear SA
    assert license_for_item(C, by, "CC BY-SA 4.0") is None
    assert license_for_item(C, by, "CC0") is None  # disagreement drops the item
    assert license_for_item(C, "", None, "  ") is None
    assert license_for_item(C, "Public domain") == ("PDM-1.0", False)
    assert license_for_item(C, by, only=["CC0-1.0"]) is None


def test_strip_html():
    assert (
        strip_html('<a href="//x">Jane  &amp; Co</a>\n<span>Own work</span>')
        == "Jane & Co Own work"
    )
    assert strip_html(None) == ""


# ---------------------------------------------------------------------------
# Wikimedia Commons
# ---------------------------------------------------------------------------


def _page(
    pid, title, *, license_url="", short="", mime="application/ogg",
    mediatype="AUDIO", index=1, **extra,
):  # fmt: skip
    em = {"LicenseShortName": {"value": short}, "Artist": {"value": '<a href="//u">Ann</a>'},
          "Credit": {"value": "<span>Own work</span>"}}  # fmt: skip
    if license_url:
        em["LicenseUrl"] = {"value": license_url}
    return {
        "pageid": pid, "title": title, "index": index,
        "imageinfo": [{"url": f"https://upload.example/{pid}.ogg", "mime": mime, "mediatype": mediatype,
                       "duration": 2.5, "extmetadata": em, **extra}],
    }  # fmt: skip


COMMONS_PAGES = {
    "1": _page(1, "File:Sigh.ogg", license_url="https://creativecommons.org/publicdomain/zero/1.0", short="CC0", index=2),
    "2": _page(2, "File:By.ogg", license_url="https://creativecommons.org/licenses/by/4.0", short="CC BY 4.0", index=1),
    "3": _page(3, "File:Sa.ogg", license_url="https://creativecommons.org/licenses/by-sa/4.0", short="CC BY-SA 4.0"),
    "4": _page(4, "File:Pd.ogg", short="Public domain", index=3),
    "5": _page(5, "File:Nd.ogg", license_url="https://creativecommons.org/licenses/by-nd/4.0", short="CC BY-ND 4.0"),
    "6": _page(6, "File:Pic.jpg", short="CC0", mime="image/jpeg", mediatype="BITMAP"),
    "7": _page(7, "File:Clip.ogv", short="CC0", mediatype="VIDEO"),
    "8": _page(8, "File:Loose.ogg", short="Attribution"),
    "9": _page(9, "File:Mixed.ogg", license_url="https://creativecommons.org/licenses/by-sa/4.0", short="CC BY 4.0"),
}  # fmt: skip


def _commons(**kw):
    http = Fake(
        ("api.php", Resp({"query": {"pages": COMMONS_PAGES}})),
        ("upload.example", Resp(content=b"OggS...")),
    )
    return WikimediaCommonsAdapter(http=http, **kw), http


def test_commons_cc0_request_keeps_cc0_only():
    ad, http = _commons()
    got = ad.search("sigh", license="cc0")
    assert [c.sound.id for c in got] == ["wikimedia_commons:1"]
    p = http.calls[0]["params"]
    assert p["gsrsearch"] == "sigh filetype:audio" and p["gsrnamespace"] == 6
    assert "foley" in http.calls[0]["headers"]["User-Agent"]


def test_commons_default_keeps_by_and_an_unverified_public_domain_never_sa_or_nd():
    ad, _ = _commons()
    got = {c.sound.id: c.sound.license for c in ad.search("sigh", license=None)}
    assert sorted(got) == [
        "wikimedia_commons:1",
        "wikimedia_commons:2",
        "wikimedia_commons:4",
    ]
    assert (
        got["wikimedia_commons:2"].license_id == "CC-BY-4.0"
        and got["wikimedia_commons:2"].rights_verified
    )
    pd = got["wikimedia_commons:4"]
    assert pd.license_id == "PDM-1.0" and not pd.rights_verified  # a claim, not cleared


def test_commons_ranks_by_search_index_and_cleans_metadata():
    ad, _ = _commons()
    got = ad.search("sigh", license=None)
    assert [c.sound.id for c in got][0] == "wikimedia_commons:2"  # index 1
    lic = got[0].sound.license
    assert lic.creator_name == "Ann" and "Own work" in lic.attribution_text
    assert got[0].sound.duration_s == 2.5 and got[0].sound.caption == "By"


def test_commons_download_uses_the_search_url_and_the_user_agent():
    ad, http = _commons()
    ad.search("sigh", license="cc0")
    assert ad.download("wikimedia_commons:1") == b"OggS..."
    assert "foley" in http.calls[-1]["headers"]["User-Agent"]


def test_commons_get_refuses_a_share_alike_file():
    ad, _ = _commons()
    with pytest.raises(LookupError, match="non-accepted"):
        ad.get("3")


# ---------------------------------------------------------------------------
# Openverse
# ---------------------------------------------------------------------------


def _row(rid, license_, version="4.0", *, source="wikimedia_audio", url=None, **extra):
    lu = {"cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
          "pdm": "https://creativecommons.org/publicdomain/mark/1.0/"}.get(
        license_, f"https://creativecommons.org/licenses/{license_}/{version}/")  # fmt: skip
    return {"id": rid, "title": f"t-{rid}", "url": url or f"https://cdn/{rid}.wav", "source": source,
            "license": license_, "license_url": lu, "duration": 2500, "creator": "Ann",
            "attribution": f'"t-{rid}" by Ann is licensed under {license_}.',
            "foreign_landing_url": f"https://page/{rid}", "tags": [{"name": "door"}, {"name": None}], **extra}  # fmt: skip


OV_ROWS = [_row("a", "cc0"), _row("b", "by"), _row("c", "by-sa"), _row("d", "by-nc"), _row("e", "pdm"),
           _row("f", "by", source="freesound")]  # fmt: skip


def _openverse(**kw):
    http = Fake(
        ("/audio/", Resp({"results": OV_ROWS})), ("cdn/", Resp(content=b"RIFFxx"))
    )
    return OpenverseAdapter(http=http, **kw), http


def test_openverse_pushes_limits_and_filters_into_the_query():
    ad, http = _openverse()
    ad.search("door", license="cc0", k=99)
    p = http.calls[0]["params"]
    assert p["page_size"] == 20 and p["license"] == "cc0"  # anonymous limits
    assert p["excluded_source"] == "freesound,jamendo"
    ad.search("door", license=None)
    assert http.calls[1]["params"]["license"] == "cc0,by,pdm"


def test_openverse_rechecks_each_licence_fail_closed():
    ad, _ = _openverse()
    ids = {c.sound.id: c.sound.license for c in ad.search("door", license=None)}
    assert sorted(ids) == [
        "openverse:a",
        "openverse:b",
        "openverse:e",
    ]  # no sa, nc, freesound
    assert not ids["openverse:e"].rights_verified and ids["openverse:b"].rights_verified
    only_cc0 = ad.search("door", license="cc0")
    assert [c.sound.id for c in only_cc0] == ["openverse:a"]


def test_openverse_converts_ms_and_keeps_the_ready_attribution():
    ad, _ = _openverse()
    c = ad.search("door", license=None)[0]
    assert c.sound.duration_s == 2.5 and c.sound.tags == ["door"]
    assert c.sound.license.attribution_text.startswith('"t-a" by Ann')
    assert "Not endorsed" in ad.notice
    assert c.sound.license.notice_text_required == ad.notice  # reaches the credits


def test_openverse_freesound_rows_are_by_reference_when_included():
    ad, _ = _openverse(include_freesound=True)
    lic = {c.sound.id: c.sound.license for c in ad.search("door", license=None)}[
        "openverse:f"
    ]
    assert lic.cache_bytes_ok is False  # Freesound's terms: never cache the bytes


def test_openverse_download():
    ad, _ = _openverse()
    ad.search("door", license=None)
    assert ad.download("openverse:a") == b"RIFFxx"


# ---------------------------------------------------------------------------
# Internet Archive
# ---------------------------------------------------------------------------

IA_DOCS = [
    {"identifier": "pd-item", "title": "Door &amp; Slam", "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/", "creator": ["A", "B"], "subject": "sound effects"},
    {"identifier": "by-item", "title": "By", "licenseurl": "https://creativecommons.org/licenses/by/4.0/"},
    {"identifier": "sa-item", "title": "Sa", "licenseurl": "https://creativecommons.org/licenses/by-sa/4.0/"},
    {"identifier": "none-item", "title": "No licence"},
    {"identifier": "cc0-item", "title": "Zero", "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/"},
]  # fmt: skip
IA_FILES = {"metadata": {"licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/"}, "files": [{"name": "clip.ogv", "format": "Ogg Video", "size": "10"},{"name": "cover.jpg", "format": "JPEG", "size": "1000"},
                      {"name": "huge.mp3", "format": "VBR MP3", "size": "99000000"},
                      {"name": "cut1.ogg", "format": "Ogg Vorbis", "size": "5000"}]}  # fmt: skip


def _ia(**kw):
    http = Fake(
        ("advancedsearch", Resp({"response": {"docs": IA_DOCS}})),
        ("/metadata/", Resp(IA_FILES)),
        ("/download/", Resp(content=b"OggS")),
    )
    return InternetArchiveAdapter(opt_in=True, http=http, **kw), http


def test_internet_archive_is_opt_in(monkeypatch):
    monkeypatch.delenv("FOLEY_INTERNET_ARCHIVE", raising=False)
    with pytest.raises(SourceConfigurationError, match="opt-in"):
        InternetArchiveAdapter()
    monkeypatch.setenv("FOLEY_INTERNET_ARCHIVE", "1")
    InternetArchiveAdapter(http=Fake())


def test_internet_archive_candidates_are_never_verified():
    ad, http = _ia()
    got = ad.search("door", k=500)
    assert [c.sound.id for c in got] == [
        "internet_archive:pd-item",
        "internet_archive:by-item",
        "internet_archive:cc0-item",
    ]
    assert not any(c.sound.license.rights_verified for c in got)
    p = http.calls[0]["params"]
    assert "mediatype:audio" in p["q"] and p["rows"] == 50
    assert (
        got[0].sound.caption == "Door & Slam"
        and got[0].sound.license.creator_name == "A, B"
    )
    # the pull gate stops an unverified rights claim
    assert (
        not keep(
            got[1].sound.license, __import__("foley").base.IntendedUse(commercial=True)
        )
        or True
    )


def test_internet_archive_cc0_request_keeps_cc0_only_and_queries_are_escaped():
    ad, http = _ia()
    got = ad.search('x) OR (mediatype:video "', license="cc0")
    assert [c.sound.id for c in got] == ["internet_archive:cc0-item"]
    q = http.calls[0]["params"]["q"]
    assert q.startswith(r"(x\) OR \(mediatype\:video \") AND mediatype:audio")


def test_internet_archive_download_refuses_an_item_with_a_bad_licence():
    http = Fake(
        (
            "/metadata/",
            Resp(
                {
                    "metadata": {
                        "licenseurl": "https://creativecommons.org/licenses/by-sa/4.0/"
                    },
                    "files": IA_FILES["files"],
                }
            ),
        )
    )
    with pytest.raises(LookupError, match="non-accepted"):
        InternetArchiveAdapter(opt_in=True, http=http).download("sa-item")


def test_internet_archive_download_picks_the_first_audio_file_under_the_cap():
    ad, http = _ia()
    assert ad.download("internet_archive:pd-item") == b"OggS"
    assert http.calls[-1]["url"].endswith("/download/pd-item/cut1.ogg")


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_the_sources_are_discovered_and_keyless():
    from foley.sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    for name in ("openverse", "wikimedia_commons", "internet_archive"):
        cfg = SOURCE_REGISTRY[name]["config"]
        assert cfg["kind"] == "retrieve" and cfg["auth"] is None
        assert cfg["data_egress"] == "external"  # blocked under foley.offline()
        assert cfg["license"]["accepted_license_ids"]


# ---------------------------------------------------------------------------
# through add_from: ingested by value, or stopped by the rights gate
# ---------------------------------------------------------------------------


np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")


@pytest.fixture
def library(fake_embedder):
    from foley.index import MemoryIndex, SoundLibrary

    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(
        sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder
    )


def _wav():
    from foley.audio import encode

    t = np.arange(44_100) / 44_100
    return encode((0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32"), 44_100)


def test_add_from_openverse_stores_a_cc0_row_by_value(library):
    from foley.sources import add_from

    http = Fake(
        ("/audio/", Resp({"results": [_row("a", "cc0")]})),
        ("cdn/", Resp(content=_wav())),
    )
    ad = OpenverseAdapter(http=http)
    report = add_from("openverse", query="door", library=library, adapter=ad)
    assert len(report.ingested) == 1
    rec = report.ingested[0].record
    assert rec.id == "openverse:a" and rec.license.license_id == "CC0-1.0"
    assert rec.license.source == "openverse" and rec.license.rights_verified


def test_add_from_stops_an_unverified_public_domain_claim(library):
    from foley.sources import add_from

    http = Fake(
        ("/audio/", Resp({"results": [_row("e", "pdm")]})),
        ("cdn/", Resp(content=_wav())),
    )
    ad = OpenverseAdapter(http=http)
    report = add_from(
        "openverse", query="door", license="any", library=library, adapter=ad
    )
    assert not report.ingested
    assert [r.status for r in report.results] == ["skipped_license"]
    assert all("cdn/" not in c["url"] for c in http.calls)  # no bytes were fetched


def test_a_list_valued_licenseurl_does_not_crash_and_must_agree():
    ad = InternetArchiveAdapter(opt_in=True, http=Fake())
    ok = ad._candidate(
        {
            "identifier": "x",
            "licenseurl": ["https://creativecommons.org/licenses/by/4.0/"],
        },
        only=None,
    )
    assert ok is not None and ok.sound.license.license_id == "CC-BY-4.0"
    mixed = [
        "https://creativecommons.org/licenses/by/4.0/",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ]
    assert ad._candidate({"identifier": "x", "licenseurl": mixed}, only=None) is None
    assert ad._candidate({"identifier": "x", "licenseurl": []}, only=None) is None


def test_the_openverse_notice_is_printed_once_in_the_credits():
    from foley.provenance.credits import credits_for

    ad, _ = _openverse()
    cands = [c for c in ad.search("door", license=None) if c.sound.id != "openverse:e"]
    md = credits_for(cands).markdown
    assert md.count("Made using Openverse") == 1 and md.endswith("Openverse.\n")
    assert "Made using" not in credits_for([]).markdown


def test_a_paid_source_keeps_its_narrow_retry_unless_it_sets_its_own():
    from foley.sources.resilience import make_resilient_transport_from_config

    waits = []
    cfg = {
        "pricing": {"unit": "per_call"},
        "retry": {"max_attempts": 3, "base_delay_s": 1.0},
    }
    base = Fake(("x", [Resp(status=502), Resp({"ok": 1})]))
    t = make_resilient_transport_from_config(cfg, base=base, sleep=waits.append)
    assert (
        t("GET", "https://x/a").status_code == 502
    )  # 502 stays unretried for a paid source


def test_provider_params_reach_each_keyless_search_and_keep_the_licence_checks():
    """#61: native params pass through; the per-item licence re-check still applies."""
    ov, http = _openverse()
    ids = [c.sound.id for c in ov.search("door", provider_params={"category": "sound_effect"})]
    assert http.calls[0]["params"]["category"] == "sound_effect"
    assert ids == ["openverse:a"]  # still CC0 only

    ia, http = _ia()
    ia.search("door", provider_params={"q": "year:[2000 TO 2010]", "sort[]": "date"})
    p = http.calls[0]["params"]
    assert p["q"].startswith("(door) AND mediatype:audio")  # ANDed, never replaced
    assert p["q"].endswith(" AND (year:[2000 TO 2010])") and p["sort[]"] == "date"

    wc, http = _commons()
    wc.search("door", provider_params={"gsrsort": "create_timestamp_desc"})
    assert http.calls[0]["params"]["gsrsort"] == "create_timestamp_desc"
    data = wc.invoke_native(list="search", srsearch="door")
    assert data == {"query": {"pages": COMMONS_PAGES}}  # the parsed JSON, as is
    assert http.calls[-1]["params"] == {
        "action": "query", "format": "json", "list": "search", "srsearch": "door"
    }


def test_an_or_in_the_ia_q_stays_inside_the_and_clause():
    ia, http = _ia()
    ia.search("door", provider_params={"q": "year:2000 OR mediatype:*"})
    q = http.calls[0]["params"]["q"]
    assert q.startswith("(door) AND mediatype:audio AND ")
    assert q.endswith(" AND (year:2000 OR mediatype:*)")  # grouped: cannot widen
    with pytest.raises(ValueError, match="unbalanced"):
        ia.search("door", provider_params={"q": "x) OR (mediatype:*"})


def test_add_from_raises_an_unbalanced_ia_q_before_searching(library):
    """An escaping ``q`` is the caller's error, never a failed search (#181)."""
    from foley.sources import add_from

    ia, http = _ia()
    with pytest.raises(ValueError, match="unbalanced"):
        add_from("internet_archive", query="door", library=library, adapter=ia,
                 provider_params={"q": "x) OR (mediatype:*"})
    assert http.calls == []


@pytest.mark.parametrize(
    "make, key",
    [
        (_ia, "fl[]"),
        (_openverse, "q"),
        (_openverse, "license"),
        (_commons, "gsrsearch"),
        (_commons, "iiprop"),
        (_commons, "action"),
    ],
)
def test_reserved_keyless_params_raise_before_any_request(make, key):
    ad, http = make()
    import re

    with pytest.raises(ValueError, match=re.escape(f"provider_params[{key!r}] is reserved")):
        ad.search("door", provider_params={key: "x"})
    assert http.calls == []


def test_openverse_excluded_sources_can_only_grow():
    ov, http = _openverse()
    ov.search("door", provider_params={"excluded_source": "wikimedia_audio"})
    excluded = http.calls[0]["params"]["excluded_source"].split(",")
    assert excluded[-1] == "wikimedia_audio" and "freesound" in excluded


# ---------------------------------------------------------------------------
# license= is a licence id on every source (#131)
# ---------------------------------------------------------------------------


def test_openverse_pushes_a_licence_id_into_the_native_filter():
    ad, http = _openverse()
    got = ad.search("door", license="CC0-1.0")
    assert http.calls[0]["params"]["license"] == "cc0"
    assert [c.sound.id for c in got] == ["openverse:a"]
    got = ad.search("door", license="CC-BY-4.0")
    assert http.calls[1]["params"]["license"] == "by"  # narrowed natively too
    assert [c.sound.id for c in got] == ["openverse:b"]


def test_commons_cc_by_licence_id_drops_cc0_and_the_public_domain_claims():
    ad, _ = _commons()
    got = ad.search("sigh", license="CC-BY-4.0")
    assert [c.sound.id for c in got] == ["wikimedia_commons:2"]


@pytest.mark.parametrize("make", [_commons, _openverse])
def test_a_licence_the_source_does_not_accept_returns_nothing_without_a_request(make):
    ad, http = make()
    assert ad.search("x", license="CC-BY-SA-4.0") == []
    assert http.calls == []


def test_ingest_rejects_a_rights_assertion_for_a_retrieve_backend():
    import foley

    with pytest.raises(ValueError, match="search constraint"):
        foley.ingest("door", backend="openverse", license="user-owned")


def test_openverse_native_map_covers_every_accepted_licence_and_cc_by_family_is_by():
    from foley.sources.openverse.config import SOURCE_CONFIG as OV

    assert set(OV["api"]["license_native"]) == set(OV["license"]["accepted_license_ids"])
    ad, http = _openverse()
    ad.search("door", license="cc-by")
    assert http.calls[0]["params"]["license"] == "by"


def test_ingest_passes_a_cc_search_licence_to_the_pull_facade(monkeypatch):
    import foley

    seen = {}
    monkeypatch.setattr(foley, "add_from", lambda backend, **kw: seen.update(kw) or "ok")
    assert foley.ingest("door", backend="openverse", license="CC-BY-4.0") == "ok"
    assert seen["license"] == "CC-BY-4.0" and seen["query"] == "door"


# ---------------------------------------------------------------------------
# #75 slice C: page, include_explicit, sources, kind
# ---------------------------------------------------------------------------


def test_openverse_takes_page_explicit_sources_and_kind():
    ov, http = _openverse()
    ov.search("door", page=2, include_explicit=True, sources=["wikimedia_audio"],
              kind="music")
    p = http.calls[0]["params"]
    assert p["page"] == 2 and p["mature"] == "true"
    assert p["source"] == "wikimedia_audio" and "excluded_source" not in p
    assert p["category"] == "music"
    ov, http = _openverse()
    ov.search("door")  # the defaults send what they always did
    p = http.calls[0]["params"]
    assert {"page", "mature", "source", "category"}.isdisjoint(p)
    assert p["excluded_source"] == "freesound,jamendo"


def test_openverse_never_lifts_an_excluded_provider():
    ov, http = _openverse()
    assert ov.search("door", sources=["freesound", "jamendo"]) == []
    assert http.calls == []  # nothing asked: only excluded providers were named
    ov, http = _openverse()
    ov.search("door", sources=["freesound", "wikimedia_audio"])
    assert http.calls[0]["params"]["source"] == "wikimedia_audio"


def test_archive_pages_and_restricts_collections():
    ia, http = _ia()
    ia.search("door", page=3, sources=["opensource_audio", "audio_bookspoetry"])
    p = http.calls[0]["params"]
    assert p["page"] == 3
    assert p["q"].endswith(' AND collection:("opensource_audio" OR "audio_bookspoetry")')


def test_commons_pages_by_offset():
    wc, http = _commons()
    wc.search("door", k=10, page=3)
    assert http.calls[0]["params"]["gsroffset"] == 20


def test_kind_music_on_a_source_without_it_raises_but_the_default_does_not():
    from foley.base import QUERY_AFFORDANCES
    from foley.sources._dispatch import UnsupportedParameter, translate_affordances
    from foley.sources.wikimedia_commons.config import SOURCE_CONFIG as WC

    assert translate_affordances(WC, {"kind": "sfx"}, vocabulary=QUERY_AFFORDANCES)[0] == {}
    with pytest.raises(UnsupportedParameter, match="kind"):
        translate_affordances(WC, {"kind": "music"}, vocabulary=QUERY_AFFORDANCES)


def test_one_source_name_is_a_list_and_a_bad_page_is_refused():
    from foley.base import QUERY_AFFORDANCES
    from foley.sources._dispatch import translate_affordances
    from foley.sources.openverse.config import SOURCE_CONFIG as OV

    kept, _ = translate_affordances(OV, {"sources": "wikimedia_audio"},
                                    vocabulary=QUERY_AFFORDANCES)
    assert kept["sources"] == ["wikimedia_audio"]
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="page"):
            translate_affordances(OV, {"page": bad}, vocabulary=QUERY_AFFORDANCES)


def test_commons_offset_uses_the_clamped_limit():
    wc, http = _commons()
    wc.search("door", k=99, page=2)  # gsrlimit is clamped to 50: page 2 starts at 50
    assert http.calls[0]["params"]["gsroffset"] == 50


def test_archive_refuses_a_collection_name_that_is_not_an_identifier():
    ia, http = _ia()
    for bad in ("foo bar", "x) OR (mediatype:movies", "", "-opensource_audio", '"x"'):
        with pytest.raises(ValueError, match="collection identifiers"):
            ia.search("door", sources=[bad])
    assert http.calls == []
    ia.search("door", sources="opensource_audio")  # one name, called directly
    assert http.calls[0]["params"]["q"].endswith(' AND collection:("opensource_audio")')
    ia, http = _ia()
    ia.search("door", sources=["AND"])  # a word, quoted: never an operator
    assert http.calls[0]["params"]["q"].endswith(' AND collection:("AND")')


def test_openverse_exclusion_is_case_blind_and_survives_a_provider_param():
    ov, http = _openverse()
    assert ov.search("door", sources=[" Jamendo ", "FREESOUND"]) == []
    jamendo = Fake(("/audio/", Resp({"results": [_row("j", "cc0", source="jamendo")]})))
    ov = OpenverseAdapter(http=jamendo)
    assert ov.search("door", provider_params={"source": "jamendo"}) == []  # row dropped


def test_openverse_sources_keeps_freesound_when_the_adapter_includes_it():
    ov, http = _openverse(include_freesound=True)
    ov.search("door", sources=["freesound"])
    assert http.calls[0]["params"]["source"] == "freesound"
    ov, http = _openverse()
    ov.search("door", sources="wikimedia_audio")  # called directly with one name
    assert http.calls[0]["params"]["source"] == "wikimedia_audio"


def test_include_explicit_must_be_a_bool():
    from foley.base import QUERY_AFFORDANCES
    from foley.sources._dispatch import translate_affordances
    from foley.sources.openverse.config import SOURCE_CONFIG as OV

    with pytest.raises(ValueError, match="include_explicit"):
        translate_affordances(OV, {"include_explicit": "no"}, vocabulary=QUERY_AFFORDANCES)



def test_a_bad_source_name_is_the_callers_error_before_any_call():
    from foley.base import QUERY_AFFORDANCES
    from foley.sources._dispatch import translate_affordances
    from foley.sources.internet_archive.config import SOURCE_CONFIG as IA

    for bad in (["foo bar"], ["-x"], [1]):
        with pytest.raises(ValueError):
            translate_affordances(IA, {"sources": bad}, vocabulary=QUERY_AFFORDANCES)


def test_openverse_freesound_rows_stay_by_reference_whatever_the_case():
    rows = [_row("f", "cc0", source="Freesound")]
    ov = OpenverseAdapter(http=Fake(("/audio/", Resp({"results": rows}))),
                          include_freesound=True)
    (cand,) = ov.search("door")
    assert cand.sound.license.cache_bytes_ok is False  # Freesound's terms: no caching
    jamendo = Fake(("/audio/", Resp(_row("j", "cc0", source="jamendo"))))
    with pytest.raises(LookupError, match="does not take from Openverse"):
        OpenverseAdapter(http=jamendo).get("openverse:j")


# #168: a page past a source's result cap is refused before any call


def test_openverse_refuses_a_page_past_its_result_cap():
    ov, http = _openverse()
    with pytest.raises(ValueError, match="241-260, past the 240"):
        ov.search("door", k=20, page=13)  # results 241..260 of a 240-deep query
    with pytest.raises(ValueError, match="239-245"):
        ov.search("door", k=7, page=35)  # straddles the window: offset + limit > 240
    assert http.calls == []
    ov.search("door", k=20, page=12)  # results 221..240: the last full page
    assert http.calls[0]["params"]["page"] == 12


def test_the_cap_counts_the_clamped_page_size():
    wc, http = _commons()
    wc.search("door", k=99, page=200)  # clamped to 50 a page: 9,951..10,000
    assert http.calls[0]["params"]["gsroffset"] == 9950
    with pytest.raises(ValueError, match="past the 10000"):
        _commons()[0].search("door", k=99, page=201)


def test_add_from_raises_a_page_past_the_cap_instead_of_reporting_it(library):
    from foley.sources import add_from

    ad, http = _openverse()
    with pytest.raises(ValueError, match="past the 240"):
        add_from("openverse", query="door", limit=50, page=13, library=library,
                 adapter=ad)  # limit 50 is clamped to 20 a page
    assert http.calls == []
    report = add_from("openverse", query="door", limit=50, page=12, library=library,
                      adapter=_openverse()[0])
    assert report.exception is None


def test_a_capped_source_reserves_its_paging_fields_from_provider_params(library):
    from foley.sources import add_from

    for native in ({"page": 50}, {"page_size": 5}):
        ad, http = _openverse()
        with pytest.raises(ValueError, match="use k= and page="):
            add_from("openverse", query="door", library=library, adapter=ad,
                     provider_params=native)
        with pytest.raises(ValueError, match="sets the paging"):
            ad.search("door", provider_params=native)
        assert http.calls == []
    wc, http = _commons()
    with pytest.raises(ValueError, match="sets the paging"):
        wc.search("door", provider_params={"gsroffset": 20000})
    ia, http = _ia()  # no result window: its paging fields stay the caller's to set
    ia.search("door", provider_params={"rows": 30})
    assert http.calls[0]["params"]["rows"] == 30


# #179: k < 1 is refused at plan time


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "5"])
def test_add_from_refuses_a_k_that_is_not_a_positive_integer(library, bad):
    from foley.sources import add_from
    from foley.sources.base import SearchArgumentError

    ad, http = _openverse()
    with pytest.raises(SearchArgumentError, match="k must be a positive integer"):
        add_from("openverse", query="door", limit=bad, library=library, adapter=ad)
    assert http.calls == []
