"""Regression tests for the post-v1 adversarial-review hardening pass.

One (or two) focused test(s) per CONFIRMED finding from the review — each fails on the
pre-fix code and passes after. Grouped by the finding they pin. Hermetic: injected fakes,
no network / keys / heavy deps (OTIO + sqlite-vec paths importorskip/skip-guard).
"""

import inspect
import os
import sys

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.agent import mcp  # noqa: E402

# Reuse the established fakes from the sibling suites (tests dir is on sys.path).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_agent import DEMO, _lib, _rec  # noqa: E402
from test_mcp import FakeLibrary, _memo_session_factory  # noqa: E402


@pytest.fixture(autouse=True)
def _obs_to_memory():
    """Route any forced-on run manifest to memory and reset obs after each test."""
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


@pytest.fixture
def mcp_wired():
    """Configure the MCP module with an injected fake library + in-memory session."""
    saved = dict(mcp._STATE)
    lib = FakeLibrary()
    mcp._configure(
        library=lib,
        session_factory=_memo_session_factory(),
        byte_store={},
        runtime=foley.RuntimeConfig.default(),
    )
    yield lib
    mcp._STATE.clear()
    mcp._STATE.update(saved)


# --- #1 / #3 — foley_generate MCP tool (Candidate return + GenerationError) ---------


def test_mcp_generate_returns_the_generated_sound_id(mcp_wired, monkeypatch):
    from foley.base import Candidate, CandidateOrigin

    cand = Candidate(sound=mcp_wired.recs["door"], origin=CandidateOrigin.generated)
    monkeypatch.setattr(foley, "generate", lambda prompt, **kw: cand)
    out = mcp.foley_generate("a wooden door creak", backend="stable_audio")
    assert out["ok"] is True
    assert out["sound_ids"] == ["door"]  # pre-fix: always [] (read .results off a Candidate)


def test_mcp_generate_failure_returns_json_not_exception(mcp_wired, monkeypatch):
    from foley.sources.generate import GenerationError

    def boom(prompt, **kw):
        raise GenerationError("QC quarantined", report=None, status="quarantined")

    monkeypatch.setattr(foley, "generate", boom)
    out = mcp.foley_generate("x", backend="stable_audio")  # must not raise
    assert out["ok"] is False
    assert out["status"] == "quarantined" and "quarantined" in out["error"]


# --- #2 — recorder.run() honors force_disabled (offline telemetry leak) --------------


def test_obs_run_scope_suppressed_under_offline():
    from foley.runtime import offline_scope

    d: dict = {}
    with offline_scope():  # sets force_disabled
        with foley.obs.run("find", run_store=d) as rec:
            with rec.span("x"):
                pass
    assert d == {}  # nothing recorded/emitted under offline — pre-fix run() forced obs ON


def test_obs_run_scope_still_emits_when_not_offline():
    d: dict = {}
    with foley.obs.run("find", prefer_otel=False, run_store=d):
        pass
    assert d  # run() force-on still works outside offline mode (positive control)


# --- #4 — SqliteVecIndex.bm25 tolerates FTS5-special query characters ----------------


_FTS5_SPECIAL = ('thunder: distant', 'glass "break', "cat AND", "foo(bar", "a:b:c")


def test_fts5_or_match_neutralizes_metacharacters_on_real_fts5():
    """The crash-safe MATCH builder against a real stdlib FTS5 table (no sqlite-vec needed)."""
    import sqlite3

    from foley.index.indexes import _fts5_or_match

    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    except sqlite3.OperationalError:  # pragma: no cover - FTS5 not compiled in
        pytest.skip("FTS5 not available in this sqlite3 build")
    con.execute("INSERT INTO t(rowid, body) VALUES (1, 'thunder distant storm')")
    for q in _FTS5_SPECIAL:
        match = _fts5_or_match(q)
        # the raw query would raise OperationalError here; the built match never does
        con.execute("SELECT rowid FROM t WHERE t MATCH ?", (match,)).fetchall()
    assert _fts5_or_match("!!!") is None  # no usable token
    hit = con.execute(
        "SELECT rowid FROM t WHERE t MATCH ?", (_fts5_or_match("thunder"),)
    ).fetchall()
    assert hit == [(1,)]
    con.close()


def test_sqlitevec_bm25_tolerates_fts5_special_chars(tmp_path):
    """The same tolerance through the real SqliteVecIndex.bm25 path (when sqlite-vec is present)."""
    from foley.index.indexes import SqliteVecIndex, sqlite_vec_loadable

    if not sqlite_vec_loadable():
        pytest.skip("sqlite-vec not loadable in this interpreter")
    ix = SqliteVecIndex(path=str(tmp_path / "idx.db"), dim=4)
    ix.index("s1", "thunder distant storm", {"id": "s1"})
    for q in _FTS5_SPECIAL:
        assert isinstance(ix.bm25(q, 5), list)  # pre-fix: sqlite3.OperationalError
    assert any(hit[0] == "s1" for hit in ix.bm25("thunder", 5))


# --- #5 — per-event Budget + generation-failure fallback -----------------------------


def test_budget_reset_zeroes_the_per_event_counters():
    from foley.agent.policy import Budget

    b = Budget(max_refine_loops=1, max_generations=1)
    b.spend_refine()
    b.spend_gen()
    assert not b.refine_ok() and not b.gen_ok()
    b.reset()
    assert b.refine_ok() and b.gen_ok()


def test_find_falls_back_to_best_verified_when_generation_unavailable():
    lib = _lib(
        [
            _rec("door", "heavy wooden door creaking open", ["door", "wood"]),
            _rec("rain", "steady rain ambience on a window", ["rain", "weather"]),
            _rec("thunder", "distant thunder rumble in a storm", ["thunder", "storm"]),
        ]
    )
    cands = foley.find(DEMO, library=lib)
    ids = {c.sound.id for c in cands}
    assert ids == {"door", "rain", "thunder"}  # rain not starved/dropped
    rain = next(c for c in cands if c.sound.id == "rain")
    # It fell back to the verified retrieval (generation is unavailable here), not dropped.
    assert rain.origin.value == "retrieved"


# --- #6 — foley_plan honors the pick's layer/onset -----------------------------------


def test_mcp_plan_honors_pick_layer_and_onset(mcp_wired):
    mcp.foley_search("x", k=3)  # cache candidates in the session
    mcp.foley_pick("rain", layer="ambience", onset=1.2)
    tl = mcp.foley_plan()
    item = next(i for i in tl["items"] if i["clip_ref"] == "rain")
    assert item["layer"] == "ambience"  # pre-fix: sfx_fg default (pick layer dropped)
    assert item["onset"] == "1.2"  # numeric pick onset → absolute-seconds anchor string


# --- #7 — OTIO export preserves overlapping/close same-layer onsets ------------------


def test_otio_export_preserves_overlapping_onsets():
    otio = pytest.importorskip("opentimelineio")
    from foley.base import Anchor, Layer, Placement, SoundDesignTimeline, TimelineItem
    from foley.weave.render import to_otio

    tl = SoundDesignTimeline(
        items=[
            TimelineItem(
                clip_ref="a", onset="0", layer=Layer.sfx_fg, id="a",
                placement=Placement(anchor=Anchor.absolute, onset=1.0),
            ),
            TimelineItem(
                clip_ref="b", onset="0", layer=Layer.sfx_fg, id="b",
                placement=Placement(anchor=Anchor.absolute, onset=1.4),
            ),
        ]
    )
    doc = otio.adapters.read_from_string(to_otio(tl), "otio_json")
    starts = {}
    for track in doc.tracks:
        for child in track:
            if isinstance(child, otio.schema.Clip):
                starts[child.name] = track.range_of_child(child).start_time.to_seconds()
    assert abs(starts["a"] - 1.0) < 0.02
    assert abs(starts["b"] - 1.4) < 0.02  # pre-fix: b silently pushed to ~2.0 (playhead)


# --- #8 — nudge() resolves the symbolic anchor against word_timeline -----------------


def test_nudge_resolves_symbolic_anchor_against_word_timeline():
    from foley.base import Layer, SoundDesignTimeline, TimelineItem
    from foley.weave.timeline import nudge

    wt = [
        {"word": "the", "start": 0.0, "end": 0.5},
        {"word": "door", "start": 1.0, "end": 1.4},
    ]
    tl = SoundDesignTimeline(
        items=[TimelineItem(clip_ref="door", onset="on 'door'", layer=Layer.sfx_fg, id="d1")],
        word_timeline=wt,
    )
    out = nudge(tl, "d1", 0.25)
    onset = out.items[0].placement.onset
    assert abs(onset - 1.25) < 1e-6  # from resolved 1.0 — pre-fix: 0.25 (from zero)


# --- #9 — MCP --offline enforces telemetry-off; status reports effective posture -----


def test_run_server_applies_offline_posture_and_restores():
    from foley.runtime import RuntimeConfig

    seen = {}

    class FakeServer:
        def run(self):
            seen["during"] = foley.obs.is_enabled()

    foley.obs.enable()
    try:
        mcp._run_server(FakeServer(), RuntimeConfig.offline_local())
        assert seen["during"] is False  # telemetry off during the offline serve
        assert foley.obs.is_enabled() is True  # restored after the scope
    finally:
        foley.obs.disable()


def test_run_server_leaves_obs_alone_when_online():
    from foley.runtime import RuntimeConfig

    seen = {}

    class FakeServer:
        def run(self):
            seen["during"] = foley.obs.is_enabled()

    foley.obs.enable()
    try:
        mcp._run_server(FakeServer(), RuntimeConfig.default())
        assert seen["during"] is True
    finally:
        foley.obs.disable()


def test_status_reports_effective_redaction_mode(mcp_wired):
    from foley.obs.redact import RedactionMode

    foley.obs.configure(redaction_mode=RedactionMode.off)
    st = mcp.foley_status()
    assert st["redaction_mode"] == "off"  # effective recorder mode, not the RuntimeConfig


# --- #11 — license_id_from_cc_url: NonCommercial labels never fail open --------------


def test_noncommercial_labels_map_to_nc_not_plain_by():
    from foley.licensing import derive_license_flags, license_id_from_cc_url

    for label in ("Attribution-NonCommercial", "Attribution NonCommercial"):
        assert license_id_from_cc_url(label) == ("CC-BY-NC-4.0", True), label
    # a bare "noncommercial" names no licence family: it fails closed (never commercial)
    assert license_id_from_cc_url("noncommercial") == ("unknown", False)
    # the NC flag is genuinely non-commercial (pre-fix mapped to CC-BY-4.0 → commercial_ok)
    assert derive_license_flags("CC-BY-NC-4.0").commercial_ok is False
    # ND/SA compounds still fail closed (the guard runs before the NC needle)
    assert license_id_from_cc_url("Attribution-NonCommercial-NoDerivatives") == ("unknown", False)


# --- #12 — resolve_master returns an independent copy --------------------------------


def test_resolve_master_returns_independent_copy():
    from foley.base import resolve_master

    p = resolve_master("podcast")
    p.target_lufs = -99.0
    assert resolve_master("podcast").target_lufs == -16.0  # global uncorrupted


# --- #13 — _TokenBucket per_day is a rolling daily cap, not a lifetime one -----------


def test_token_bucket_daily_cap_rolls_over_after_a_day():
    from foley.sources.resilience import SECONDS_PER_DAY, SourceUnavailable, _TokenBucket

    clk = [0.0]
    bucket = _TokenBucket(per_day=2, clock=lambda: clk[0])
    noop = lambda _s: None  # noqa: E731
    bucket.take(noop)
    bucket.take(noop)
    with pytest.raises(SourceUnavailable):
        bucket.take(noop)  # 3rd within the same day exceeds the cap
    clk[0] += SECONDS_PER_DAY + 1.0  # a full day elapses
    bucket.take(noop)  # rolled over — allowed again (pre-fix: stayed over-cap forever)


# --- #14 — render() aligner parameter carries the Aligner annotation -----------------


def test_render_aligner_annotation_is_aligner_not_apply_strategy():
    from foley.weave.render import render

    ann = inspect.signature(render).parameters["aligner"].annotation
    assert "Aligner" in ann and "ApplyStrategy" not in ann


# --- #15 — to_qrels scopes each event to its own answer clips ------------------------


def test_to_qrels_scopes_answer_clips_per_event():
    from foley.eval.golden import GoldenItem, to_qrels

    item = GoldenItem(
        id="gld_multi",
        context="door then rain",
        expected_events=[
            {"query": "door slam", "ucs_catid": "DOORSlam"},
            {"query": "rain", "ucs_catid": "RAINGnrl"},
        ],
        answer_clip_ids={"DOORSlam": ["ring0:door_slam"], "RAINGnrl": ["ring0:rain"]},
        grade={"ring0:door_slam": 2, "ring0:rain": 2},
        negatives=[],
        labeler="test",
        schema_version=1,
    )
    q = to_qrels([item])
    assert q["gld_multi::0"] == {"ring0:door_slam": 2}  # NOT the union of both events
    assert q["gld_multi::1"] == {"ring0:rain": 2}


# --- #16 — precision_at_k(k=0) is defined, not a crash ------------------------------


def test_precision_at_k_zero_returns_zero():
    from foley.eval.retrieval import precision_at_k

    assert precision_at_k({"a": 2}, {"a": 0.9}, 0) == 0.0  # pre-fix: ZeroDivisionError


# --- #10 / #17 — README no longer claims design-stage / uses a bad backend name ------


def test_readme_reflects_v1_and_valid_backend():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
    assert "design-stage" not in readme
    assert "stable_audio_open" not in readme  # the registered backend is "stable_audio"
