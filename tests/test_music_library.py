"""Acquire a licensed music library with provenance (#201, ported from an#470): offline,
every network step behind its seam (a fake fetch or transport, a fake verify, a fake
clock)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import pytest

import foley.licensing
from foley.base import LicenseRecord
from foley.sources.music_library import (
    ACQUIRED,
    FAILED,
    KEPT,
    MUSIC_LIBRARIES,
    WISHLIST,
    AcquiredTrack,
    MusicLibrary,
    MusicLibraryError,
    MusicToolMissing,
    acquire,
    attribution_text,
    kept_digests,
    probe_verify,
    register_music_library,
    titles_by_library,
    titles_from_json,
    track_license,
    tracks_table,
    wayback,
)


class Fetcher:
    """Serves bytes per URL; a URL it does not know is a 403."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise OSError(f"HTTP Error 403: Forbidden ({url})")
        return self.pages[url]


@dataclass
class Resp:
    status_code: int = 200
    content: bytes = b""
    headers: dict = field(default_factory=lambda: {"Content-Type": "audio/mpeg"})

    def json(self):
        return json.loads(self.content)


class FakeTransport:
    """A foley Transport: answers per URL from a list of responses (the last repeats);
    an unknown URL is a 404."""

    def __init__(self, answers):
        self.answers, self.calls = {k: list(v) for k, v in answers.items()}, []

    def __call__(self, method, url, *, params=None, headers=None, json=None):
        self.calls.append((method, url, dict(headers or {})))
        queue = self.answers.get(url)
        if not queue:
            return Resp(status_code=404, headers={"Content-Type": "text/html"})
        return queue.pop(0) if len(queue) > 1 else queue[0]


class Clock:
    """A fake monotonic clock that only moves when the code sleeps."""

    def __init__(self):
        self.now, self.slept = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def _ok(data):
    """A verifier that accepts any non-empty file as 1.5 s of audio."""
    if not data:
        raise MusicLibraryError("empty")
    return 1.5


def _url(title):
    return MUSIC_LIBRARIES["incompetech"].track_url(title)


def _acquire(titles, fetch, **kw):
    kw.setdefault("out", {})
    return acquire("incompetech", titles, fetch=fetch, verify=_ok, **kw)


def _via_transport(titles, transport, clock=None, **kw):
    clock = clock or Clock()
    kw.setdefault("out", {})
    return acquire(
        "incompetech", titles, transport=transport, verify=_ok,
        clock=clock, sleep=clock.sleep, **kw,
    )  # fmt: skip


# --- ported from an/tests/test_music_library.py --------------------------------------


def test_titles_are_fetched_verified_and_recorded_with_their_licence():
    fetch, store = Fetcher({_url("A"): b"aa", _url("B"): b"bb"}), {}
    rows = _acquire(["A", "B"], fetch, out=store)
    assert [(r.title, r.status, r.file) for r in rows] == [
        ("A", ACQUIRED, "A.mp3"),
        ("B", ACQUIRED, "B.mp3"),
    ]
    assert store == {"A.mp3": b"aa", "B.mp3": b"bb"}
    row = rows[0]
    lic = row.license
    assert isinstance(lic, LicenseRecord)
    assert (lic.license_id, lic.creator_name, row.url) == (
        "CC-BY-4.0",
        "Kevin MacLeod",
        _url("A"),
    )
    assert lic.rights_verified and lic.requires_attribution and lic.commercial_ok
    assert row.sha256 == lic.content_sha256 == hashlib.sha256(b"aa").hexdigest()
    assert lic.source == "incompetech" and lic.source_url == _url("A")
    assert attribution_text(rows).startswith('"A" Kevin MacLeod (incompetech.com)\n')


def test_the_archive_copy_is_recorded_as_where_the_bytes_came_from():
    """The site refuses; the Internet Archive serves. The row says so: `url` is the
    archive's, `page_url` the library's."""
    (row,) = _acquire(["A"], Fetcher({wayback(_url("A")): b"aa"}))
    assert row.status == ACQUIRED
    assert row.url == wayback(_url("A"))
    assert row.page_url == _url("A")
    assert row.mirror == "wayback"
    assert row.row()["source_page_url"] == _url("A")


def test_a_lost_title_is_a_failed_row_and_the_batch_goes_on():
    store = {}
    rows = _acquire(["Gone", "A"], Fetcher({_url("A"): b"aa"}), out=store)
    assert [r.status for r in rows] == [FAILED, ACQUIRED]
    assert "direct: HTTP Error 403" in rows[0].error and "wayback:" in rows[0].error
    assert "Gone.mp3" not in store
    assert attribution_text(rows).count("Kevin MacLeod") == 1, "only what was acquired"


def test_a_file_that_is_not_audio_is_not_kept():
    fetch = Fetcher({_url("A"): b"", wayback(_url("A")): b""})
    store = {}
    (row,) = _acquire(["A"], fetch, out=store)
    assert row.status == FAILED and "empty" in row.error and store == {}


def test_a_store_that_refuses_a_file_fails_that_title_only():
    class Refusing(dict):
        def __setitem__(self, k, v):
            if k.startswith("Bad"):
                raise KeyError(f"cannot store {k}")
            super().__setitem__(k, v)

    store = Refusing()
    rows = _acquire(
        ["Bad", "Good"], Fetcher({_url("Bad"): b"b", _url("Good"): b"g"}), out=store
    )
    assert [r.status for r in rows] == [FAILED, ACQUIRED]
    assert list(store) == ["Good.mp3"]


def test_a_title_with_a_path_in_it_stays_in_the_folder(tmp_path):
    rows = _acquire(
        ["AC/DC", "../../escape"],
        Fetcher({_url("AC/DC"): b"a", _url("../../escape"): b"e"}),
        out=tmp_path / "o",
    )
    assert [r.file for r in rows] == ["AC-DC.mp3", "-..-escape.mp3"]
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == [
        "-..-escape.mp3",
        "AC-DC.mp3",
    ]


def test_two_titles_that_share_a_file_are_refused():
    with pytest.raises(MusicLibraryError, match="both be saved"):
        _acquire(["Song", "SONG"], Fetcher({}))


def test_a_rerun_keeps_only_what_the_previous_table_recorded():
    fetch = Fetcher({_url("A"): b"aa", _url("B"): b"new"})
    store = {"A.mp3": b"aa", "B.mp3": b"someone else's file"}
    kept = {"A.mp3": hashlib.sha256(b"aa").hexdigest()}
    rows = _acquire(["A", "B"], fetch, out=store, kept=kept)
    assert [r.status for r in rows] == [KEPT, ACQUIRED]
    assert fetch.calls == [_url("B")], "A not fetched again"
    assert rows[0].sha256 == kept["A.mp3"]
    assert rows[0].license.license_id == "CC-BY-4.0"
    assert store["B.mp3"] == b"new", "an unrecorded file is not stamped with a licence"
    assert kept_digests(tracks_table(rows)) == {
        "A.mp3": kept["A.mp3"],
        "B.mp3": hashlib.sha256(b"new").hexdigest(),
    }


def test_a_paid_library_is_a_wishlist_and_downloads_nothing():
    fetch = Fetcher({})
    rows = acquire("epidemic_sound", ["Night Owl"], out={}, fetch=fetch, verify=_ok)
    assert [(r.status, r.license.license_id, r.file) for r in rows] == [
        (WISHLIST, "unknown", None)
    ]
    lic = rows[0].license
    assert not (lic.rights_verified or lic.commercial_ok or lic.cache_bytes_ok)
    assert lic.attribution_text is None
    assert fetch.calls == [] and attribution_text(rows) == ""


def test_metadata_rides_the_row_into_the_tracks_table():
    titles = {
        "A": {"credited_by": ["vid1", "vid2"], "feel": "Bright", "tags": {"k": 1}}
    }
    (track,) = _acquire(titles, Fetcher({_url("A"): b"aa"}))
    assert track.credited_by == ("vid1", "vid2")
    assert track.metadata == {"feel": "Bright", "tags": {"k": 1}}
    (row,) = csv.DictReader(io.StringIO(tracks_table([track])))
    assert row["credited_by"] == "vid1; vid2" and row["feel"] == "Bright"
    assert row["tags"] == '{"k": 1}'
    assert row["license"] == "CC-BY-4.0" and row["duration_s"] == "1.5"
    assert row["rights_verified"] == "True"
    for clash in ({"license": "cc0-1.0"}, {"status": "acquired"}, {"sha256": "x"}):
        with pytest.raises(MusicLibraryError, match="drop them"):
            _acquire({"A": clash}, Fetcher({}))


@pytest.mark.parametrize("bad", ["Sneaky Snitch", ["A", ""], {"A": "Bright"}])
def test_titles_of_the_wrong_shape_are_refused(bad):
    with pytest.raises(MusicLibraryError):
        _acquire(bad, Fetcher({}))


@pytest.mark.parametrize(
    "text", ['"Sneaky Snitch"', "3", '{"A": "Bright"}', "[1, 2]", "{nope"]
)
def test_a_titles_file_names_the_shapes_it_accepts(text):
    with pytest.raises(MusicLibraryError):
        titles_from_json(text)


def test_an_unknown_library_names_the_registered_ones():
    with pytest.raises(MusicLibraryError, match="incompetech"):
        acquire("audionautix", ["A"], out={})


def test_without_a_probe_nothing_is_downloaded(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setitem(sys.modules, "mixing.video.shot_boundaries", None)
    fetch = Fetcher({_url("A"): b"aa"})
    with pytest.raises(MusicToolMissing, match="ffprobe"):
        acquire("incompetech", ["A"], out={}, fetch=fetch)
    assert fetch.calls == []


@pytest.mark.parametrize(
    "description, expected",
    [
        (  # the attribution form the licence asks for: what attribution_text writes
            MUSIC_LIBRARIES["incompetech"].attribution_for("Sneaky Snitch"),
            {"incompetech": ["Sneaky Snitch"]},
        ),
        (
            "Music by Kevin MacLeod (incompetech.com):\n0:00 Sneaky Snitch\n"
            "1:23 - Fluffing a Duck\nhttps://incompetech.com\n\nSubscribe!",
            {"incompetech": ["Sneaky Snitch", "Fluffing a Duck"]},
        ),
        (
            'Music: Kevin MacLeod\nSong: "Monkeys Spinning Monkeys"\n'
            "Licensed under Creative Commons: By Attribution 4.0",
            {"incompetech": ["Monkeys Spinning Monkeys"]},
        ),
        (
            "From Artlist:\n• Golden Hour\n\nThanks for watching",
            {"artlist": ["Golden Hour"]},
        ),
        ("No credits here.\nJust words.", {}),
    ],
)
def test_titles_by_library_reads_real_credit_formats(description, expected):
    assert titles_by_library(description) == expected


def test_titles_by_library_reads_only_the_libraries_it_is_given():
    text = "From Artlist:\nGolden Hour"
    only = {"incompetech": MUSIC_LIBRARIES["incompetech"]}
    assert titles_by_library(text, libraries=only) == {}


def _mp3(tmp_path):
    path = tmp_path / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", str(path)],
        check=True,
    )
    return path.read_bytes()


@pytest.mark.skipif(
    not (shutil.which("ffprobe") and shutil.which("ffmpeg")), reason="no ffmpeg"
)
def test_probe_verify_reads_audio_and_refuses_an_error_page(tmp_path):
    assert probe_verify(_mp3(tmp_path)) == pytest.approx(1.0, abs=0.1)
    for bad in (b"<html>403 Forbidden</html>", b""):
        with pytest.raises(MusicLibraryError):
            probe_verify(bad)


def test_probe_verify_uses_the_injected_probe_on_a_file():
    seen = []

    def probe(path):
        seen.append(open(path, "rb").read())
        return 2.25

    assert probe_verify(b"abc", probe=probe) == 2.25 and seen == [b"abc"]


# --- foley's machinery: the transport, resilience, licensing SSOT --------------------


def test_a_429_with_retry_after_is_retried_after_the_advertised_wait():
    url = _url("A")
    throttled = Resp(status_code=429, headers={"Retry-After": "37"})
    transport = FakeTransport({url: [throttled, Resp(content=b"aa")]})
    clock = Clock()
    (row,) = _via_transport(["A"], transport, clock=clock)
    assert row.status == ACQUIRED and row.mirror == "direct"
    assert [c[1] for c in transport.calls] == [url, url]
    assert 37.0 in clock.slept, clock.slept
    assert transport.calls[0][2]["User-Agent"].startswith("foley-music-library")


def test_a_long_retry_after_is_honoured_up_to_the_configured_cap():
    url = _url("A")
    throttled = Resp(status_code=429, headers={"Retry-After": "600"})
    transport = FakeTransport({url: [throttled, Resp(content=b"aa")]})
    clock = Clock()
    (row,) = _via_transport(["A"], transport, clock=clock)
    assert row.status == ACQUIRED and 120.0 in clock.slept


def test_one_host_is_paced_and_switching_to_the_archive_costs_no_pause():
    a, b = _url("A"), _url("B")
    transport = FakeTransport(
        {a: [Resp(content=b"aa")], wayback(b): [Resp(content=b"bb")]}
    )
    clock = Clock()
    rows = _via_transport(["A", "B"], transport, clock=clock)
    assert [(r.status, r.mirror) for r in rows] == [
        (ACQUIRED, "direct"),
        (ACQUIRED, "wayback"),
    ]
    # A, then B on the same host (paced 2 s), then B on the archive (its own host)
    assert clock.slept == [2.0]


def test_an_error_page_served_with_200_is_not_a_track():
    url = _url("A")
    page = Resp(content=b"<html>", headers={"content-type": "text/html; charset=utf-8"})
    transport = FakeTransport({url: [page]})
    (row,) = _via_transport(["A"], transport)
    assert row.status == FAILED
    assert "text/html page" in row.error and "wayback: HTTP 404" in row.error


def test_a_rerun_with_kept_digests_fetches_nothing(tmp_path):
    transport = FakeTransport({_url("A"): [Resp(content=b"aa")]})
    out = tmp_path / "lib"
    first = _via_transport(["A"], transport, out=out)
    table = tracks_table(first)
    transport.calls.clear()
    again = _via_transport(["A"], transport, out=out, kept=kept_digests(table))
    assert [r.status for r in again] == [KEPT] and transport.calls == []
    assert kept_digests(again) == kept_digests(table)
    rows = json.loads(json.dumps([r.row() for r in again]))
    assert kept_digests(rows) == kept_digests(table), "rows read back from JSON"


def test_a_wishlist_library_never_fetches_even_through_a_transport():
    transport = FakeTransport({})
    rows = acquire("artlist", ["Golden Hour"], out={}, transport=transport)
    assert [r.status for r in rows] == [WISHLIST] and transport.calls == []


def test_licence_ids_come_from_license_id_from_cc_url(monkeypatch):
    calls = []
    real = foley.licensing.license_id_from_cc_url

    def spy(url):
        calls.append(url)
        return real(url)

    monkeypatch.setattr(
        "foley.sources.music_library.libraries.license_id_from_cc_url", spy
    )
    lic = track_license(MUSIC_LIBRARIES["incompetech"], "A")
    assert calls and set(calls) == {"http://creativecommons.org/licenses/by/4.0/"}
    assert (lic.license_id, lic.rights_verified) == real(calls[0])


def test_a_library_whose_licence_foley_cannot_read_is_refused():
    def rule(title):
        return f"https://x.org/{title}.mp3"

    for url in (
        "https://x.org/our-licence",  # not a CC URL
        "https://creativecommons.org/licenses/by-nd/4.0/",  # ND: fails closed
    ):
        with pytest.raises(MusicLibraryError, match="cannot read a licence"):
            register_music_library(
                MusicLibrary("x", "X", license_url=url, track_url=rule)
            )
    assert "x" not in MUSIC_LIBRARIES


def test_a_public_domain_mark_library_is_acquired_but_never_verified():
    lib = MusicLibrary(
        "pdm_lib",
        "Someone",
        license_url="https://creativecommons.org/publicdomain/mark/1.0/",
        track_url=lambda t: f"https://pd.example/{t}.mp3",
    )
    (row,) = acquire(lib, ["A"], out={}, fetch=lambda url: b"aa", verify=_ok)
    assert row.status == ACQUIRED
    assert row.license.license_id == "PDM-1.0" and not row.license.rights_verified


def test_fetch_and_transport_are_one_seam_or_the_other():
    with pytest.raises(ValueError, match="not both"):
        acquire(
            "incompetech", ["A"], out={}, fetch=Fetcher({}),
            transport=FakeTransport({}), verify=_ok,
        )  # fmt: skip


def test_the_transport_path_honours_offline():
    import foley
    from foley.runtime import EgressBlocked

    transport = FakeTransport({_url("A"): [Resp(content=b"aa")]})
    with foley.offline(), pytest.raises(EgressBlocked):
        _via_transport(["A"], transport)
    assert transport.calls == []


def test_a_row_round_trips_through_json():
    (track,) = _acquire({"A": {"credited_by": ["v"]}}, Fetcher({_url("A"): b"aa"}))
    back = AcquiredTrack.from_json(track.to_json())
    assert back == track


def test_importing_the_package_does_not_import_requests():
    code = (
        "import sys, foley.sources.music_library as m; "
        "from foley.sources.registry import list_sources; "
        "assert 'requests' not in sys.modules, 'requests leaked'; "
        "assert 'music_library' not in list_sources(), 'not a live source'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
