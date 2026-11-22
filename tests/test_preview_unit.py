"""Unit tests for ``foley.agent.preview`` branches (fake library, no audio extras needed)."""

import pytest

np = pytest.importorskip("numpy")

from foley.agent import preview as pv  # noqa: E402
from foley.base import Candidate, LicenseRecord, SoundRecord  # noqa: E402


def _rec(sid):
    return SoundRecord(
        id=sid,
        license=LicenseRecord(source="user", license_id="CC0-1.0"),
    )


class FakeLib:
    def __init__(self):
        self.calls = []

    def __getitem__(self, sid):
        return _rec(sid)

    def array(self, sid, *, sr, mono):
        self.calls.append(("array", sid, sr, mono))
        return np.zeros(sr * 10, dtype="float32")

    def similar(self, sid, *, k):
        self.calls.append(("similar", sid, k))
        return [Candidate(sound=_rec("n1"))]

    def search_clip(self, clip, *, k):
        self.calls.append(("search_clip", k))
        return [Candidate(sound=_rec("c1"))]

    def search(self, q, *, k):
        self.calls.append(("search", q, k))
        return [Candidate(sound=_rec(f"{q}-1"), rrf_score=0.5)]


def test_preview_without_store_leaves_uri_none():
    cand = pv.preview("a", library=FakeLib())
    assert cand.sound.id == "a" and cand.preview_uri is None


def test_preview_accepts_candidate_and_degrades_on_failure():
    class Broken(FakeLib):
        def array(self, *a, **k):
            raise RuntimeError("no codec")

    cand = Candidate(sound=_rec("x"))
    out = pv.preview(cand, library=Broken(), byte_store={})
    assert out is cand and out.preview_uri is None


def test_preview_writes_to_store(monkeypatch):
    monkeypatch.setattr("foley.audio.encode", lambda clip, sr, fmt: b"FLAC" + bytes(len(clip) % 7))
    store = {}
    lib = FakeLib()
    out = pv.preview("a", seconds=1, library=lib, byte_store=store)
    assert out.preview_uri in store and store[out.preview_uri].startswith(b"FLAC")


def test_default_library_is_used(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr("foley.index.library.default_library", lambda: lib)
    assert pv.preview("z").sound.id == "z"


def test_similar_to_dispatch():
    lib = FakeLib()
    assert pv.similar_to("a", k=3, library=lib)[0].sound.id == "n1"
    assert pv.similar_to(Candidate(sound=_rec("b")), library=lib)[0].sound.id == "n1"
    assert pv.similar_to(b"raw", library=lib)[0].sound.id == "c1"
    assert ("similar", "a", 3) in lib.calls and ("similar", "b", 10) in lib.calls


def test_score_prefers_rerank_then_rrf_then_clap():
    c = Candidate(sound=_rec("a"), clap_score=0.1, rrf_score=0.2, rerank_score=0.3)
    assert pv._score(c) == 0.3
    c.rerank_score = None
    assert pv._score(c) == 0.2
    c.rrf_score = None
    assert pv._score(c) == 0.1
    c.clap_score = None
    assert pv._score(c) == 0.0


def test_rerank_by_feedback_drops_rejected_and_sorts():
    cs = [
        Candidate(sound=_rec("a"), rrf_score=0.1),
        Candidate(sound=_rec("b"), rrf_score=0.9),
        Candidate(sound=_rec("c"), rrf_score=0.5),
    ]
    out = pv._rerank_by_feedback(cs, picked=set(), rejected={"c"})
    assert [c.sound.id for c in out] == ["b", "a"]


def test_refine_without_query_uses_picks_and_rejects():
    lib = FakeLib()
    out = pv.refine(picked_ids=("p",), rejected_ids=("n1",), library=lib)
    assert out.queries == [] and out.results == []


def test_refine_uses_session_feedback_and_expands_query(monkeypatch):
    lib = FakeLib()
    monkeypatch.setattr("foley.agent.refine.refine_query", lambda q, **kw: [q, q + " more"])

    class Sess:
        def picked_ids(self):
            return ["p"]

        def rejected_ids(self):
            return []

    out = pv.refine(Sess(), query="door", k=5, library=lib)
    assert out.queries == ["door", "door more"]
    ids = [c.sound.id for c in out.results]
    assert "door-1" in ids and "n1" in ids
