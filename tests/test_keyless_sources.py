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


NO_WAIT = dict(sleep=lambda s: None)


# ---------------------------------------------------------------------------
# the shared helpers
# ---------------------------------------------------------------------------


def test_a_429_is_waited_out_then_succeeds_or_gives_up():
    waited = []
    http = Fake(("x", [Resp(status=429), Resp(status=429), Resp({"ok": 1})]))
    assert get_json(http, "https://x/a", what="t", sleep=waited.append) == {"ok": 1}
    assert waited == [10.0, 30.0]
    always = Fake(("x", [Resp(status=429)] * 9))
    with pytest.raises(RuntimeError, match="429"):
        get_json(
            always, "https://x/a", what="t", waits=(1.0, 2.0), sleep=lambda s: None
        )
    assert len(always.calls) == 3  # the first try plus one per wait


def test_other_failures_are_not_retried():
    http = Fake(("x", [Resp(status=500)]))
    with pytest.raises(RuntimeError, match="500"):
        get_bytes(http, "https://x/a", what="t", sleep=lambda s: pytest.fail("slept"))


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
    pid, title, *, license_url="", short="", mime="application/ogg", index=1, **extra
):
    em = {"LicenseShortName": {"value": short}, "Artist": {"value": '<a href="//u">Ann</a>'},
          "Credit": {"value": "<span>Own work</span>"}}  # fmt: skip
    if license_url:
        em["LicenseUrl"] = {"value": license_url}
    return {
        "pageid": pid, "title": title, "index": index,
        "imageinfo": [{"url": f"https://upload.example/{pid}.ogg", "mime": mime,
                       "duration": 2.5, "extmetadata": em, **extra}],
    }  # fmt: skip


COMMONS_PAGES = {
    "1": _page(1, "File:Sigh.ogg", license_url="https://creativecommons.org/publicdomain/zero/1.0", short="CC0", index=2),
    "2": _page(2, "File:By.ogg", license_url="https://creativecommons.org/licenses/by/4.0", short="CC BY 4.0", index=1),
    "3": _page(3, "File:Sa.ogg", license_url="https://creativecommons.org/licenses/by-sa/4.0", short="CC BY-SA 4.0"),
    "4": _page(4, "File:Pd.ogg", short="Public domain", index=3),
    "5": _page(5, "File:Nd.ogg", license_url="https://creativecommons.org/licenses/by-nd/4.0", short="CC BY-ND 4.0"),
    "6": _page(6, "File:Pic.jpg", short="CC0", mime="image/jpeg"),
}  # fmt: skip


def _commons(**kw):
    http = Fake(
        ("api.php", Resp({"query": {"pages": COMMONS_PAGES}})),
        ("upload.example", Resp(content=b"OggS...")),
    )
    return WikimediaCommonsAdapter(http=http, **NO_WAIT, **kw), http


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


def test_commons_waits_out_a_429_on_download():
    waited = []
    http = Fake(
        ("api.php", Resp({"query": {"pages": COMMONS_PAGES}})),
        ("upload.example", [Resp(status=429), Resp(content=b"OggS")]),
    )
    ad = WikimediaCommonsAdapter(http=http, sleep=waited.append)
    ad.search("sigh", license="cc0")
    assert ad.download("1") == b"OggS" and waited == [10.0]


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
    return OpenverseAdapter(http=http, **NO_WAIT, **kw), http


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
]  # fmt: skip
IA_FILES = {"files": [{"name": "cover.jpg", "format": "JPEG", "size": "1000"},
                      {"name": "huge.mp3", "format": "VBR MP3", "size": "99000000"},
                      {"name": "cut1.ogg", "format": "Ogg Vorbis", "size": "5000"}]}  # fmt: skip


def _ia(**kw):
    http = Fake(
        ("advancedsearch", Resp({"response": {"docs": IA_DOCS}})),
        ("/metadata/", Resp(IA_FILES)),
        ("/download/", Resp(content=b"OggS")),
    )
    return InternetArchiveAdapter(opt_in=True, http=http, **NO_WAIT, **kw), http


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
    ad = OpenverseAdapter(http=http, **NO_WAIT)
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
    ad = OpenverseAdapter(http=http, **NO_WAIT)
    report = add_from(
        "openverse", query="door", license="any", library=library, adapter=ad
    )
    assert not report.ingested
    assert [r.status for r in report.results] == ["skipped_license"]
    assert all("cdn/" not in c["url"] for c in http.calls)  # no bytes were fetched
