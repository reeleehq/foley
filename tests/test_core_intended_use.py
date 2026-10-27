"""The core façades take ``intended_use=`` and gate every sound (#208).

``foley.plan`` / ``foley.weave`` refuse (``LicenseRefusal``) under an explicit intent and
warn (``FutureWarning``) under ``None``; ``foley.search`` / ``foley.similar`` drop what an
explicit intent does not keep.
"""

import os
import sys
import warnings

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, os.path.dirname(__file__))

import foley  # noqa: E402
from foley.base import Candidate, LicenseRecord, SoundRecord  # noqa: E402
from test_mcp import FakeLibrary  # noqa: E402

US = foley.IntendedUse(commercial=True, publish=True, territory="US")
GB = foley.IntendedUse(commercial=True, publish=True, territory="GB")


def _relicense(lib, sid, **license_kw):
    rec = lib.recs[sid]
    lib.recs[sid] = SoundRecord(
        **{**rec.__dict__, "license": LicenseRecord(source="user", **license_kw)}
    )


@pytest.fixture
def lib():
    """door: clean CC0; rain: territory-excluded (Hunyuan); thunder: unverified."""
    lib = FakeLibrary()
    _relicense(
        lib,
        "rain",
        license_id="Tencent-Hunyuan-Community",
        commercial_ok=True,
        rights_verified=True,
    )
    _relicense(
        lib, "thunder", license_id="CC0-1.0", commercial_ok=True, rights_verified=False
    )
    return lib


def _cands(lib, ids):
    return [Candidate(sound=lib.recs[i]) for i in ids]


def test_plan_refuses_territory_excluded_and_unverified_under_an_explicit_intent(lib):
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.plan(_cands(lib, ["door", "rain", "thunder"]), intended_use=GB)
    assert set(info.value.refused) == {"rain", "thunder"}
    assert "rain" in str(info.value) and "thunder" in str(info.value)
    assert isinstance(info.value, ValueError)
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)  # an explicit intent never warns
        tl = foley.plan(_cands(lib, ["door"]), intended_use=GB)
    assert [it.clip_ref for it in tl.items] == ["door"]


def test_plan_judges_the_librarys_current_record(lib):
    stale = _cands(lib, ["door"])  # found while door was clean CC0
    _relicense(
        lib,
        "door",
        license_id="CC-BY-NC-4.0",
        commercial_ok=False,
        rights_verified=True,
    )
    with pytest.raises(foley.LicenseRefusal):
        foley.plan(stale, intended_use=US, library=lib)
    assert foley.plan(stale, intended_use=US).items  # no library: the candidate's own


def test_plan_without_intent_warns_once_naming_the_ids(lib):
    with pytest.warns(FutureWarning) as record:
        tl = foley.plan(_cands(lib, ["door", "rain", "thunder"]))
    future = [w for w in record if issubclass(w.category, FutureWarning)]
    assert len(future) == 1
    msg = str(future[0].message)
    assert "rain" in msg and "thunder" in msg and "intended_use=" in msg
    assert future[0].filename == __file__  # points at the caller, not foley
    assert len(tl.items) == 3  # nothing refused yet


def test_weave_refuses_clips_under_an_explicit_intent(lib):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        tl = foley.plan(_cands(lib, ["door", "rain", "thunder"]))
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.weave("nar", tl, library=lib, intended_use=GB)
    assert set(info.value.refused) == {"rain", "thunder"}
    clean = foley.plan(_cands(lib, ["door"]), intended_use=GB)
    assert foley.weave("nar", clean, library=lib, intended_use=GB).audio is not None


def test_weave_judges_only_enabled_clips(lib):
    tl = foley.plan(_cands(lib, ["door", "rain"]), intended_use=US)
    with pytest.raises(foley.LicenseRefusal):
        foley.weave("nar", tl, library=lib, intended_use=GB)
    next(it for it in tl.items if it.clip_ref == "rain").enabled = False  # muted
    assert foley.weave("nar", tl, library=lib, intended_use=GB).audio is not None


def test_weave_refuses_a_library_narration_and_a_clip_with_no_record(lib):
    empty = foley.base.SoundDesignTimeline(items=[])
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.weave("rain", empty, library=lib, intended_use=GB)
    assert set(info.value.refused) == {"rain"}
    assert foley.weave("rain", empty, library=lib, intended_use=US).audio is not None
    # audio-only narration (no record): nothing to check
    assert foley.weave("nar", empty, library=lib, intended_use=GB).audio is not None
    tl = foley.plan(_cands(lib, ["door"]), intended_use=US)
    del lib.recs["door"]  # its audio is still there, its record is not
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.weave("nar", tl, library=lib, intended_use=US)
    assert "no record" in info.value.refused["door"]


def test_weave_without_intent_renders_and_warns_once(lib):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        tl = foley.plan(_cands(lib, ["door", "rain"]))
    with pytest.warns(FutureWarning) as record:
        woven = foley.weave("nar", tl, library=lib)
    future = [w for w in record if issubclass(w.category, FutureWarning)]
    msg = str(future[0].message)
    assert len(future) == 1 and "rain:" in msg and "door:" not in msg
    assert future[0].filename == __file__
    assert woven.audio is not None


@pytest.mark.parametrize("call", ["search", "similar"])
def test_search_and_similar_drop_what_an_explicit_intent_refuses(lib, call):
    def run(**kw):
        if call == "search":
            return foley.search("x", k=5, library=lib, **kw)
        return foley.similar("door", k=5, library=lib, **kw)

    rows = run(intended_use=US)
    assert "rain" in [c.sound.id for c in rows]  # US: Hunyuan grants it
    assert "thunder" not in [c.sound.id for c in rows]  # unverified: dropped
    assert all(c.license_ok is True for c in rows)
    gb = [c.sound.id for c in run(intended_use=GB)]
    assert "rain" not in gb and "thunder" not in gb
    with pytest.raises(ValueError):  # a contradicting shorthand is refused
        run(intended_use=US, commercial_ok=False)


class _CorruptRecord(FakeLibrary):
    """A library whose stored record for ``rain`` cannot be read (a corrupt dol JSON)."""

    def __getitem__(self, key):
        if key == "rain":
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return super().__getitem__(key)


def _corrupt():
    lib = _CorruptRecord()
    lib.recs.update(FakeLibrary().recs)
    return lib


def test_an_unreadable_record_warns_without_intent_and_is_refused_with_one(lib):
    bad = _corrupt()
    tl = foley.plan(_cands(lib, ["door", "rain"]), intended_use=US)
    with pytest.warns(FutureWarning, match="rain: it has no record"):
        assert foley.weave("nar", tl, library=bad).audio is not None  # main renders
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.weave("nar", tl, library=bad, intended_use=US)
    assert set(info.value.refused) == {"rain"}
    with pytest.warns(FutureWarning, match="rain: it has no record"):
        foley.plan(_cands(lib, ["door", "rain"]), library=bad)  # not its own record
    with pytest.raises(foley.LicenseRefusal):
        foley.plan(_cands(lib, ["rain"]), intended_use=US, library=bad)


def test_a_plain_mapping_library_renders_without_intent_and_cannot_pass_one(lib):
    tl = foley.plan(_cands(lib, ["door"]), intended_use=US)
    arrays = {
        "door": np.zeros(4800, dtype="float32"),
        "nar": np.zeros(48000, dtype="float32"),
    }
    with pytest.warns(FutureWarning, match="door"):
        assert foley.weave("nar", tl, library=arrays).audio is not None
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.weave("nar", tl, library=arrays, intended_use=US)
    assert set(info.value.refused) == {"door"}  # the audio narration is not judged
    empty = foley.base.SoundDesignTimeline(items=[])
    assert foley.weave("nar", empty, library=arrays, intended_use=US).audio is not None


def test_score_passes_its_intent_through_to_plan_and_weave(lib, monkeypatch):
    monkeypatch.setattr(foley, "find", lambda seg, **kw: _cands(lib, ["door", "rain"]))
    with pytest.raises(foley.LicenseRefusal) as info:
        foley.score("a door, then rain", library=lib, intended_use=GB)
    assert set(info.value.refused) == {"rain"}

    seen = {}

    def fake_weave(audio, timeline, **kw):
        seen.update(kw)
        raise RuntimeError("stop")

    monkeypatch.setattr(foley, "weave", fake_weave)
    monkeypatch.setattr(foley.index, "default_library", lambda: lib)
    with pytest.raises(RuntimeError, match="stop"):
        foley.score("a door, then rain", audio="nar", intended_use=US)
    assert seen["library"] is lib and seen["intended_use"] == US


@pytest.fixture
def wired(lib):
    from foley.agent import verbs as mcp
    from test_mcp import _memo_session_factory

    saved = dict(mcp._STATE)
    mcp._configure(
        library=lib,
        session_factory=_memo_session_factory(),
        byte_store={},
        runtime=foley.RuntimeConfig.default(),
    )
    yield mcp
    mcp._STATE.clear()
    mcp._STATE.update(saved)


def test_foley_score_answers_a_refusal_with_the_refused_row(wired, monkeypatch):
    def refuse(*args, **kwargs):
        raise foley.LicenseRefusal({"rain": "no grant in GB"})

    monkeypatch.setattr(foley, "score", refuse)
    row = wired.foley_score("rain", territory="GB")
    assert row == {
        "ok": False,
        "status": "refused",
        "error": "not licensed for this use: rain: no grant in GB",
        "refused": {"rain": "no grant in GB"},
    }


def test_a_licence_refusal_is_not_swallowed_as_invalid_input(wired):
    # LicenseRefusal is a ValueError: a bad-input wrapper must answer it as refused.
    @wired._invalid_on_bad_input
    def tool():
        raise foley.LicenseRefusal({"rain": "no grant in GB"})

    row = tool()
    assert row["status"] == "refused" and row["refused"] == {"rain": "no grant in GB"}
