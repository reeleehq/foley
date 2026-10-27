"""Acquire a licensed music library with provenance (#201, ported from an#470): offline,
every network step behind its seam (a fake fetch or transport, a fake verify, a fake
clock)."""

from __future__ import annotations

import csv
import functools
import hashlib
import io
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import pytest

import foley.licensing
from foley.base import IntendedUse, LicenseRecord
from foley.sources import video
from foley.sources.music_library import (
    ACQUIRED,
    FAILED,
    KEPT,
    MUSIC_LIBRARIES,
    REFUSED,
    TRACK_COLUMNS,
    WISHLIST,
    AcquiredTrack,
    MusicLibrary,
    MusicLibraryError,
    MusicToolMissing,
    acquire,
    attribution_text,
    kept_digests,
    kept_sources,
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


def _acquire(titles, fetch, clock=None, **kw):
    """``acquire`` over a fake ``fetch``, timed by a fake clock (the pace costs no time)."""
    clock = clock or Clock()
    kw.setdefault("out", {})
    return acquire(
        "incompetech", titles, fetch=fetch, verify=_ok,
        clock=clock, sleep=clock.sleep, **kw,
    )  # fmt: skip


def _via_transport(titles, transport, clock=None, **kw):
    clock = clock or Clock()
    kw.setdefault("out", {})
    return acquire(
        "incompetech", titles, transport=transport, verify=_ok,
        clock=clock, sleep=clock.sleep, **kw,
    )  # fmt: skip


# --- ported from an/tests/test_music_library.py --------------------------------------


def test_titles_are_fetched_verified_and_recorded_with_their_licence():
    fetch, store, clock = Fetcher({_url("A"): b"aa", _url("B"): b"bb"}), {}, Clock()
    rows = _acquire(["A", "B"], fetch, out=store, clock=clock)
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
    assert clock.slept == [2.0], "one pause: the second request to the same host"
    assert attribution_text(rows).startswith('"A" Kevin MacLeod (incompetech.com)\n')


def test_the_archive_copy_is_recorded_as_where_the_bytes_came_from():
    """The site refuses; the Internet Archive serves. The row says so: `url` is the
    archive's, `page_url` the library's, and no pause is spent switching hosts."""
    clock = Clock()
    (row,) = _acquire(["A"], Fetcher({wayback(_url("A")): b"aa"}), clock=clock)
    assert row.status == ACQUIRED and clock.slept == []
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
    assert row["tags"] == '{"k": 1}' and "extra" not in row
    assert row["license"] == "CC-BY-4.0" and row["duration_s"] == "1.5"
    assert row["rights_verified"] == "True" and row["commercial_ok"] == "True"
    for clash in (
        {"license": "cc0-1.0"},
        {"status": "acquired"},
        {"sha256": "x"},
        {"commercial_ok": True},  # a licence flag: the library states it
        {"cache_bytes_ok": True},
    ):
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


_needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffprobe") and shutil.which("ffmpeg")), reason="no ffmpeg"
)


@_needs_ffmpeg
def test_probe_verify_reads_audio_and_refuses_an_error_page(tmp_path):
    assert probe_verify(_mp3(tmp_path)) == pytest.approx(1.0, abs=0.1)
    for bad in (b"<html>403 Forbidden</html>", b""):
        with pytest.raises(MusicLibraryError):
            probe_verify(bad)


@_needs_ffmpeg
@pytest.mark.parametrize("suffix", [".mp4", ".gif"])
def test_probe_verify_refuses_a_real_video_without_audio(tmp_path, suffix):
    path = tmp_path / f"picture{suffix}"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=5",
         str(path)],
        check=True,
    )  # fmt: skip
    assert video.has_audio_stream(str(path)) is False
    assert video.default_probe(str(path)) > 0, "it has a duration"
    with pytest.raises(MusicLibraryError, match="no audio stream"):
        probe_verify(path.read_bytes(), suffix=suffix)


def test_probe_verify_uses_the_injected_probe_on_a_file():
    seen = []

    def probe(path):
        seen.append(open(path, "rb").read())
        return 2.25

    def has_audio(path):
        seen.append(path)
        return True

    assert probe_verify(b"abc", probe=probe, has_audio=has_audio) == 2.25
    assert seen[1:] == [b"abc"] and seen[0].endswith(".mp3")


@pytest.mark.parametrize(
    "has_audio, message",
    [(False, "no audio stream"), (None, "cannot tell whether the file has an audio")],
)
def test_a_file_without_an_audio_stream_is_refused_even_with_a_duration(
    has_audio, message
):
    """A video-only mp4 or a gif has a duration but no audio: an's ffprobe_verify
    refused it, and so does probe_verify (an unknown answer refuses too)."""
    verify = functools.partial(
        probe_verify, probe=lambda path: 2.0, has_audio=lambda path: has_audio
    )
    with pytest.raises(MusicLibraryError, match=message):
        verify(b"GIF89a...")
    store = {}
    (row,) = acquire(
        "incompetech", ["A"], out=store, fetch=Fetcher({_url("A"): b"GIF89a"}),
        verify=verify, sleep=lambda s: None,
    )  # fmt: skip
    assert row.status == FAILED and message in row.error and store == {}


def _fake_ffprobe(tmp_path, *, stdout, code=0):
    """An executable that answers like ffprobe: prints ``stdout``, exits ``code``."""
    exe = tmp_path / "ffprobe"
    exe.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout!r})\nsys.exit({code})\n"
    )
    exe.chmod(0o755)
    return str(exe)


@pytest.mark.parametrize(
    "stdout, code, expected",
    [
        ("audio\n", 0, True),
        ("", 0, False),
        ("video\n", 0, False),
        ("audio\n", 1, False),
    ],
)
@pytest.mark.skipif(
    sys.platform == "win32", reason="the fake ffprobe is a #! script (POSIX only)"
)
def test_has_audio_stream_reads_ffprobe_streams(tmp_path, stdout, code, expected):
    exe = _fake_ffprobe(tmp_path, stdout=stdout, code=code)
    assert video.has_audio_stream(str(tmp_path), ffprobe=exe) is expected


def test_has_audio_stream_without_ffprobe_falls_back_to_soundfile(
    tmp_path, monkeypatch
):
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    wav, junk = tmp_path / "tone.wav", tmp_path / "page.mp3"
    sf.write(str(wav), np.zeros(4800, dtype="float32"), 48000)
    junk.write_bytes(b"<html>403</html>")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert video.has_audio_stream(str(wav)) is True
    assert video.has_audio_stream(str(junk)) is None, "cannot tell, not 'no'"
    monkeypatch.setitem(sys.modules, "soundfile", None)
    assert video.has_audio_stream(str(wav)) is None, "no decoder: cannot tell"


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


def test_a_retry_after_over_the_cap_moves_on_to_the_next_mirror():
    """Waiting the 120 s cap again and again for a server that asked for 600 s is
    wasted: the archive is asked instead, at once."""
    url = _url("A")
    throttled = Resp(status_code=429, headers={"Retry-After": "600"})
    transport = FakeTransport(
        {url: [throttled, Resp(content=b"aa")], wayback(url): [Resp(content=b"aa")]}
    )
    clock = Clock()
    (row,) = _via_transport(["A"], transport, clock=clock)
    assert (row.status, row.mirror) == (ACQUIRED, "wayback")
    assert [c[1] for c in transport.calls] == [url, wayback(url)]
    assert clock.slept == []


def test_a_retry_after_within_the_cap_is_waited_on_the_same_mirror():
    url = _url("A")
    throttled = Resp(status_code=429, headers={"Retry-After": "120"})
    transport = FakeTransport({url: [throttled, Resp(content=b"aa")]})
    clock = Clock()
    (row,) = _via_transport(["A"], transport, clock=clock)
    assert (row.status, row.mirror) == (ACQUIRED, "direct") and clock.slept == [120.0]


def test_a_failed_row_names_the_long_retry_after_of_every_mirror():
    url = _url("A")
    throttled = Resp(status_code=429, headers={"Retry-After": "3600"})
    transport = FakeTransport({url: [throttled], wayback(url): [throttled]})
    clock = Clock()
    (row,) = _via_transport(["A"], transport, clock=clock)
    assert row.status == FAILED and row.error.count("3600 s") == 2
    assert "next mirror" in row.error and clock.slept == []


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


def _rule(title):
    return f"https://x.org/{title}.mp3"


@pytest.mark.parametrize(
    "url, message",
    [
        ("https://x.org/our-licence", "cannot read a licence"),  # not a CC URL
        ("https://creativecommons.org/licenses/by-nd/4.0/", "NoDerivatives terms"),
        ("https://creativecommons.org/licenses/by-sa/4.0/", "ShareAlike terms"),
    ],
)
def test_a_library_whose_files_may_not_be_kept_is_refused(url, message):
    """Registration checks keeping the files only; ShareAlike / NoDerivatives are a
    deliberate refusal, said as such (not "cannot read")."""
    with pytest.raises(MusicLibraryError, match=message) as info:
        register_music_library(MusicLibrary("x", "X", license_url=url, track_url=_rule))
    if "creativecommons" in url:
        assert "on purpose" in str(info.value)
        assert "cannot read" not in str(info.value)
    assert "x" not in MUSIC_LIBRARIES


_NC_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
_NON_COMMERCIAL = IntendedUse(commercial=False, publish=True, can_attribute=True)


def test_a_non_commercial_library_registers_but_its_titles_are_refused_by_default():
    lib = MusicLibrary("nc_lib", "N", license_url=_NC_URL, track_url=_rule)
    register_music_library(lib, replace=True)
    try:
        fetch, store = Fetcher({_rule("A"): b"aa"}), {}
        (row,) = acquire("nc_lib", ["A"], out=store, fetch=fetch, verify=_ok)
        assert row.status == REFUSED and "commercial use" in row.error
        assert fetch.calls == [] and store == {}, "a refused title is not fetched"
        assert row.license.license_id == "CC-BY-NC-4.0" and row.page_url == _rule("A")
        assert attribution_text([row]) == "" and kept_digests([row]) == {}
        (csv_row,) = csv.DictReader(io.StringIO(tracks_table([row])))
        assert csv_row["status"] == REFUSED and csv_row["commercial_ok"] == "False"
        (row,) = acquire(
            "nc_lib", ["A"], out=store, fetch=fetch, verify=_ok,
            intended_use=_NON_COMMERCIAL, sleep=lambda s: None,
        )  # fmt: skip
        assert row.status == ACQUIRED and store == {"A.mp3": b"aa"}
    finally:
        MUSIC_LIBRARIES.pop("nc_lib", None)


def test_a_refused_batch_needs_no_probe_and_no_egress(monkeypatch):
    import foley

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setitem(sys.modules, "mixing.video.shot_boundaries", None)
    lib = MusicLibrary("nc_lib", "N", license_url=_NC_URL, track_url=_rule)
    transport = FakeTransport({})
    with foley.offline():
        rows = acquire(lib, ["A", "B"], out={}, transport=transport)
    assert [r.status for r in rows] == [REFUSED, REFUSED] and transport.calls == []


def test_the_licence_gate_fails_closed(monkeypatch):
    def broken(record, intended_use):
        raise TypeError("a gate bug")

    monkeypatch.setattr(
        "foley.sources.music_library.acquisition.refusal_reason", broken
    )
    fetch = Fetcher({_url("A"): b"aa"})
    (row,) = _acquire(["A"], fetch)
    assert row.status == REFUSED and "could not decide" in row.error
    assert fetch.calls == []


def test_a_public_domain_mark_library_is_refused_its_rights_unverified():
    """The Public Domain Mark is a claim, never verified: foley's gate refuses it."""
    lib = MusicLibrary(
        "pdm_lib",
        "Someone",
        license_url="https://creativecommons.org/publicdomain/mark/1.0/",
        track_url=lambda t: f"https://pd.example/{t}.mp3",
    )
    fetch = Fetcher({"https://pd.example/A.mp3": b"aa"})
    (row,) = acquire(lib, ["A"], out={}, fetch=fetch, verify=_ok)
    assert row.status == REFUSED and "not verified" in row.error and fetch.calls == []
    assert row.license.license_id == "PDM-1.0" and not row.license.rights_verified


def test_the_tracks_table_has_a_commercial_ok_column():
    assert (
        TRACK_COLUMNS.index("commercial_ok")
        == TRACK_COLUMNS.index("rights_verified") + 1
    )


def test_a_body_declared_over_max_bytes_is_refused_before_it_is_read():
    class Huge:
        status_code = 200
        headers = {"Content-Type": "audio/mpeg", "Content-Length": "999999999"}

        @property
        def content(self):
            raise AssertionError("the body was read")

    url = _url("A")
    huge = Huge()
    transport = FakeTransport({url: [huge]})
    (row,) = _via_transport(["A"], transport)
    assert row.status == FAILED and "declares 999999999 bytes" in row.error


def test_a_body_over_max_bytes_without_a_header_is_refused_after_it_is_read():
    """A partial config is laid over the defaults (the user agent is still there)."""
    url = _url("A")
    transport = FakeTransport({url: [Resp(content=b"aaaa")]})
    (row,) = _via_transport(["A"], transport, config={"max_bytes": 3})
    assert row.status == FAILED and "is over 3 bytes" in row.error
    assert transport.calls[0][2]["User-Agent"].startswith("foley-music-library")


def test_a_config_rate_paces_a_fetch_of_ones_own():
    clock = Clock()
    rows = _acquire(
        ["A", "B"], Fetcher({_url("A"): b"a", _url("B"): b"b"}),
        clock=clock, config={"rate": {"per_min": 6}},
    )  # fmt: skip
    assert [r.status for r in rows] == [ACQUIRED, ACQUIRED] and clock.slept == [10.0]


def test_a_bug_in_the_fetch_stops_the_batch():
    """A ``KeyError`` from a fetch is a bug (a config without a key), not a lost title."""

    def fetch(url):
        return {}["user_agent"]

    with pytest.raises(KeyError):
        _acquire(["A", "B"], fetch)


def test_a_store_refusal_names_no_local_directory(tmp_path):
    lib = MusicLibrary(
        "x", "X", license_url="https://creativecommons.org/licenses/by/4.0/",
        track_url=_rule, file_name=lambda t: "../../evil_" + t,
    )  # fmt: skip
    out = tmp_path / "o"
    (row,) = acquire(
        lib, ["A"], out=out, fetch=Fetcher({_rule("A"): b"a"}), verify=_ok,
        sleep=lambda s: None,
    )  # fmt: skip
    assert row.status == FAILED and row.error.startswith("could not save")
    assert str(tmp_path) not in row.error and "/tmp" not in row.error
    assert not list(tmp_path.rglob("evil*"))
    (row,) = _acquire(["x" * 300], Fetcher({_url("x" * 300): b"a"}), out=out)
    assert row.status == FAILED and row.error.startswith("could not save")
    assert str(tmp_path) not in row.error and str(tmp_path).replace("\\", "\\\\") not in row.error


@pytest.mark.parametrize(
    "reason",
    [
        "[Errno 36] File name too long: '/home/u/o/x.mp3'",
        "[Errno 22] Invalid argument: 'C:\\Users\\u\\o\\x.mp3'",
        "[Errno 22] Invalid argument: 'C:\\\\Users\\\\u\\\\o\\\\x.mp3'",
    ],
)
def test_a_store_error_keeps_the_file_name_and_drops_every_local_directory(reason):
    from foley.sources.music_library.acquisition import _store_error

    error = _store_error(KeyError(reason), name="x.mp3")
    assert "x.mp3'" in error and "Users" not in error and "home" not in error


def test_a_kept_row_keeps_the_url_and_mirror_that_served_it(tmp_path):
    url = _url("A")
    transport = FakeTransport({wayback(url): [Resp(content=b"aa")]})
    out = tmp_path / "lib"
    table = tracks_table(_via_transport(["A"], transport, out=out))
    transport.calls.clear()
    (row,) = _via_transport(["A"], transport, out=out, kept=kept_sources(table))
    assert (row.status, row.url, row.mirror) == (KEPT, wayback(url), "wayback")
    assert transport.calls == [] and row.page_url == url
    (row,) = _via_transport(["A"], transport, out=out, kept=kept_digests(table))
    assert (row.status, row.url, row.mirror) == (KEPT, None, None), "a digest only"
    with pytest.raises(MusicLibraryError, match="kept value"):
        _via_transport(["A"], transport, out=out, kept={"A.mp3": {"url": url}})


def test_acquire_reads_a_library_from_the_libraries_it_is_given():
    lib = MusicLibrary(
        "mine", "Me", license_url="https://creativecommons.org/licenses/by/4.0/",
        track_url=_rule,
    )  # fmt: skip
    rows = acquire(
        "mine", ["A"], libraries={"mine": lib}, out={},
        fetch=Fetcher({_rule("A"): b"a"}), verify=_ok, sleep=lambda s: None,
    )  # fmt: skip
    assert [(r.library, r.status) for r in rows] == [("mine", ACQUIRED)]
    with pytest.raises(MusicLibraryError, match="no music library 'incompetech'"):
        acquire("incompetech", ["A"], libraries={"mine": lib}, out={})


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


def test_a_body_shorter_than_its_content_length_is_refused():
    """A cut download: its header alone could still probe as audio."""
    url = _url("A")
    cut = Resp(content=b"aaa", headers={"Content-Type": "audio/mpeg", "Content-Length": "16000"})
    (row,) = _via_transport(["A"], FakeTransport({url: [cut]}))
    assert row.status == FAILED and "truncated: 3 of the 16000" in row.error


def test_registering_a_library_whose_rights_foley_never_verifies_is_refused():
    lib = MusicLibrary(
        "pdm_lib",
        "Someone",
        license_url="https://creativecommons.org/publicdomain/mark/1.0/",
        track_url=lambda t: f"https://pd.example/{t}.mp3",
    )
    with pytest.raises(MusicLibraryError, match="refuse every title"):
        register_music_library(lib)
    assert "pdm_lib" not in MUSIC_LIBRARIES
