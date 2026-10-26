"""#12 MCP surface + preview UX — hermetic (injected fakes; no real server/network)."""

import json
import os
import pathlib
import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.agent import mcp  # noqa: E402
from foley.agent.session import SessionStore  # noqa: E402
from foley.base import (  # noqa: E402
    Candidate,
    LicenseRecord,
    SoundRecord,
    StorageMode,
)

SR = 48000


class FakeLibrary:
    """A tiny in-memory library: canned candidates + real audio for every id."""

    def __init__(self):
        self.recs = {
            sid: SoundRecord(
                id=sid,
                caption=cap,
                tags=[sid],
                duration_s=0.5,
                storage_mode=StorageMode.by_value,
                uri=f"secret://{sid}",
                license=LicenseRecord(
                    source="user", license_id="CC0-1.0", commercial_ok=True, rights_verified=True
                ),
            )
            for sid, cap in [
                ("door", "door creak"),
                ("rain", "rain bed"),
                ("thunder", "thunder rumble"),
            ]
        }
        tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(int(0.5 * SR)) / SR)).astype(
            "float32"
        )
        self.arrays = {sid: tone for sid in self.recs}
        self.arrays["nar"] = (
            0.1 * np.random.default_rng(0).standard_normal(2 * SR)
        ).astype("float32")

    def __getitem__(self, k):
        return self.recs[k]

    def __contains__(self, k):
        return k in self.arrays or k in self.recs

    def array(self, ref, *, sr=None, mono=True):
        from foley.audio import WORKING_SAMPLE_RATE, to_working

        return to_working(
            self.arrays[ref],
            SR,
            mono=mono,
            target_sr=WORKING_SAMPLE_RATE if sr is None else sr,
        )

    def _cands(self, ids, k):
        return [
            Candidate(
                sound=self.recs[i], clap_score=0.9 - 0.1 * n, rrf_score=0.8 - 0.1 * n
            )
            for n, i in enumerate(ids[:k])
        ]

    def search(self, query, *, k=10, **kw):
        return self._cands(list(self.recs), k)

    def similar(self, sound_id, *, k=10):
        return self._cands([i for i in self.recs if i != sound_id], k)

    def search_clip(self, clip, *, k=10):
        return self._cands(list(self.recs), k)


def _memo_session_factory():
    """A session factory that returns the SAME in-memory store per id (mimics disk persistence)."""
    sessions: dict = {}

    def factory(sid):
        if sid not in sessions:
            sessions[sid] = SessionStore(sid, candidates={}, picks={}, rejects={})
        return sessions[sid]

    return factory


@pytest.fixture
def wired():
    """Configure the MCP module with an injected fake library + in-memory session/store."""
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


# --- import purity + extras ------------------------------------------------


def test_import_foley_does_not_import_py2mcp():
    code = (
        "import sys, foley;"
        "bad={'py2mcp','fastmcp'} & set(sys.modules);"
        "assert not bad, bad"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_mcp_extra_declared_but_not_in_ci_install():
    tomllib = pytest.importorskip("tomllib")
    root = pathlib.Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert "py2mcp" in data["project"]["optional-dependencies"]["mcp"]
    assert "mcp" not in data["tool"]["wads"]["ci"]["install"]["extras"]
    assert data["project"]["scripts"]["foley-mcp"] == "foley.agent.mcp:_cli"


# --- projections -----------------------------------------------------------


def test_candidate_row_is_compact_and_leak_free():
    c = Candidate(
        sound=SoundRecord(
            id="door",
            caption="a creak",
            tags=["door"],
            duration_s=1.2,
            storage_mode=StorageMode.by_value,
            uri="secret/path",
            license=LicenseRecord(
                source="user", license_id="CC0-1.0", commercial_ok=True, rights_verified=True
            ),
        ),
        clap_score=0.8,
        rrf_score=0.5,
    )
    row = mcp._candidate_row(c)
    assert json.dumps(row)  # JSON-safe
    # leaky internals are absent (keys AND values)
    for k in ("storage_mode", "uri", "sound", "qc", "embedding_ref"):
        assert k not in row
    assert "secret/path" not in json.dumps(row)
    assert row["id"] == "door" and row["scores"]["clap"] == 0.8
    assert row["license"]["license_id"] == "CC0-1.0"


# --- session round-trip ----------------------------------------------------


def test_session_cache_and_rehydrate_round_trip():
    lib = FakeLibrary()
    sess = SessionStore("t", candidates={}, picks={}, rejects={})
    cands = lib.search("x", k=2)
    assert sess.cache_candidates(cands) == 2
    rebuilt = sess.rehydrate([c.sound.id for c in cands])
    assert [c.sound.id for c in rebuilt] == [c.sound.id for c in cands]
    assert (
        isinstance(rebuilt[0], Candidate)
        and rebuilt[0].sound.license.license_id == "CC0-1.0"
    )


# --- preview / similar_to / refine ----------------------------------------


def test_preview_writes_uri_and_degrades_gracefully(wired):
    r = mcp.foley_preview("door", seconds=1)
    assert (
        r["sound_id"] == "door" and r["preview_uri"] is not None
    )  # real audio -> a key
    # no byte store -> graceful degrade (preview_uri None), never raises
    from foley.agent.preview import preview

    cand = preview("door", library=wired, byte_store=None)
    assert cand.preview_uri is None


def test_similar_to_and_refine(wired):
    rows = mcp.foley_similar_to("door", k=5)
    assert rows and all(r["id"] != "door" for r in rows) and json.dumps(rows)
    res = mcp.foley_refine(query="storm", k=5)
    assert "queries" in res and "results" in res and json.dumps(res)


# --- tool JSON-safety ------------------------------------------------------


def test_pick_reject_status_capabilities_json_safe(wired):
    assert mcp.foley_pick("door", layer="sfx_fg")["n_picks"] == 1
    assert mcp.foley_reject("thunder", reason="too loud")["n_rejects"] == 1
    assert json.dumps(mcp.foley_list_picks())
    st = mcp.foley_status()
    assert json.dumps(st) and st["n_picks"] == 1 and st["n_rejects"] == 1
    assert json.dumps(mcp.foley_capabilities())


def test_plan_from_picks_then_weave(wired):
    mcp.foley_search("x", k=2)  # caches candidates in the session
    mcp.foley_pick("door")
    tl = mcp.foley_plan(transcript="the door opened")
    assert json.dumps(tl) and tl["items"] and tl["items"][0]["clip_ref"] == "door"
    # weave the timeline (narration is a library ref); returns JSON with audio by key
    result = mcp.foley_weave("nar", tl)
    assert json.dumps(result)
    assert (
        result["audio_ref"] is not None
    )  # ndarray written to the byte store, not returned
    assert result["captions_vtt"].startswith("WEBVTT")
    assert isinstance(result["credits"], list)  # tuple normalized to list


def test_timeline_edit_tools(wired):
    from foley.base import Anchor, Layer, Placement, SoundDesignTimeline, TimelineItem

    tl = SoundDesignTimeline(
        items=[
            TimelineItem(
                clip_ref="door",
                onset="on 'door'",
                gain=-6.0,
                layer=Layer.sfx_fg,
                id="c1",
                placement=Placement(anchor=Anchor.absolute, onset=0.5),
                event={"query": "door creak"},
            )
        ]
    ).to_dict()
    assert mcp.foley_swap_clip(tl, "c1", "rain")["items"][0]["clip_ref"] == "rain"
    assert json.dumps(mcp.foley_set_gain(tl, "c1", -3.0))
    assert json.dumps(mcp.foley_nudge(tl, "c1", 0.25))
    assert json.dumps(mcp.foley_toggle(tl, "c1", False))
    assert mcp.foley_set_master(tl, target_lufs=-14.0)["master"]["target_lufs"] == -14.0
    # peak-only edit keeps the LUFS default instead of silently discarding the ceiling
    only_peak = mcp.foley_set_master(tl, peak_dbfs=-2.0)["master"]
    assert only_peak["true_peak_db"] == -2.0 and only_peak["target_lufs"] == -16.0
    assert mcp.foley_timeline_captions(tl, fmt="vtt")["vtt"].startswith("WEBVTT")
    assert "-->" in mcp.foley_timeline_captions(tl, fmt="srt")["srt"]


# --- offline enforcement ---------------------------------------------------


def test_generate_blocked_for_external_backend_offline(wired):
    mcp._configure(runtime=foley.RuntimeConfig.offline_local())
    out = mcp.foley_generate("a whoosh", backend="elevenlabs")
    assert out["ok"] is False and "offline" in out["error"]


# --- server construction (no run / no network) -----------------------------


def test_build_mcp_server_registers_the_full_tool_surface(wired):
    pytest.importorskip("py2mcp")
    import asyncio

    server = mcp.build_mcp_server()
    names = {getattr(t, "name", t) for t in asyncio.run(server.list_tools())}
    expected = {fn.__name__ for fn in mcp.TOOLS}
    assert (
        expected <= names and "foley_weave" in names and "foley_capabilities" in names
    )
    assert {"foley_score", "foley_guide"} <= names  # the AI-first agent tools
    assert len(mcp._resolve_tools()) == 22


def test_resolve_tools_subset():
    subset = mcp._resolve_tools(include=["foley_find", "foley_weave"])
    assert [f.__name__ for f in subset] == ["foley_find", "foley_weave"]


# --- foley_find via a real MemoryIndex library -----------------------------


def _mem_library():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from conftest import FakeEmbedder

    from foley.index import MemoryIndex, SoundLibrary

    emb = FakeEmbedder()
    idx = MemoryIndex(dim=emb.dim)
    lib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=emb)
    for sid, cap in [
        ("door", "heavy wooden door creaking open"),
        ("rain", "steady rain ambience"),
        ("thunder", "distant thunder rumble"),
    ]:
        lib.add(
            SoundRecord(
                id=sid,
                caption=cap,
                tags=[sid],
                duration_s=2.0,
                uri=f"t://{sid}",
                license=LicenseRecord(
                    source="test",
                    license_id="CC0-1.0",
                    commercial_ok=True,
                    rights_verified=True,
                ),
            ),
            vector=emb.embed_text(cap)[0],
        )
    return lib


def test_foley_find_returns_json_candidate_rows():
    saved = dict(mcp._STATE)
    try:
        mcp._configure(
            library=_mem_library(),
            session_factory=lambda sid: SessionStore(
                sid, candidates={}, picks={}, rejects={}
            ),
        )
        rows = mcp.foley_find("The heavy oak door creaked as rain fell.", k=5)
        assert json.dumps(rows) and rows
        assert all("id" in r and "scores" in r and "license" in r for r in rows)
    finally:
        mcp._STATE.clear()
        mcp._STATE.update(saved)
