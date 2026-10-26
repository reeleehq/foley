"""AI-first surface — foley.score(), the agent kit installer, and the foley_score/guide tools."""

import json
import os
import sys
import tempfile

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.agent import mcp  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_agent import _lib, _rec  # noqa: E402
from test_mcp import FakeLibrary, _memo_session_factory  # noqa: E402


@pytest.fixture(autouse=True)
def _obs_to_memory():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


def _demo_lib():
    return _lib(
        [
            _rec("door", "heavy wooden door creaking open", ["door", "wood"]),
            _rec("rain", "steady rain ambience on a window", ["rain", "weather"]),
            _rec("thunder", "distant thunder rumble in a storm", ["thunder", "storm"]),
        ]
    )


# --- foley.score() ----------------------------------------------------------


def test_score_plan_only_returns_timeline_and_rationale():
    res = foley.score(
        ["The heavy oak door creaked.", "Rain fell and thunder rolled."], library=_demo_lib()
    )
    assert res.weave is None  # no audio → plan only
    assert res.n_sounds == len(res.events) == len(res.timeline.items)
    assert res.n_sounds >= 1
    assert "sound" in res.rationale.lower()
    # every scored event carries a real placed sound + a segment index
    for e in res.events:
        assert e.sound_id and isinstance(e.segment, int)
        assert json.dumps(e.to_dict())  # JSON-friendly


def test_score_accepts_a_single_string():
    res = foley.score("The heavy oak door creaked.", library=_demo_lib())
    assert res.n_sounds >= 1 and all(e.segment == 0 for e in res.events)


def test_score_weaves_when_audio_is_given():
    lib = FakeLibrary()  # serves clip + narration audio
    res = foley.score("A door creak and distant thunder.", audio="nar", library=lib)
    assert res.weave is not None
    assert res.weave.audio.shape[1] == 2  # mastered stereo mix
    assert res.weave.captions_vtt.startswith("WEBVTT")
    # the returned timeline is the hydrated (woven) one
    assert res.timeline is res.weave.timeline


def test_score_weave_can_be_forced_off_with_audio():
    lib = FakeLibrary()
    res = foley.score("A door creak.", audio="nar", library=lib, weave=False)
    assert res.weave is None


# --- the agent kit installer ------------------------------------------------


def test_install_agent_kit_copies_skill_command_subagent_and_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        dest = os.path.join(d, ".claude")
        installed = foley.install_agent_kit(dest=dest)
        assert len(installed) == 3
        assert os.path.isfile(os.path.join(dest, "skills/foley-sound-design/SKILL.md"))
        assert os.path.isfile(os.path.join(dest, "commands/foley-score.md"))
        assert os.path.isfile(os.path.join(dest, "agents/sound-designer.md"))
        # idempotent: a second run installs nothing (no overwrite)
        assert foley.install_agent_kit(dest=dest) == []
        # overwrite re-installs
        assert foley.install_agent_kit(dest=dest, overwrite=True)


def test_shipped_skill_is_spec_clean():
    from foley.agent_kit import _data_dir

    text = (_data_dir() / "skills" / "foley-sound-design" / "SKILL.md").read_text()
    assert text.startswith("---")  # YAML frontmatter
    fm = text.split("---", 2)[1]
    assert "name: foley-sound-design" in fm
    assert "description:" in fm
    # the body teaches the load-bearing discipline
    body = text.split("---", 2)[2].lower()
    for token in ("restraint", "license", "foley.score", "weave"):
        assert token in body, token


# --- MCP agent tools --------------------------------------------------------


@pytest.fixture
def mcp_wired():
    saved = dict(mcp._STATE)
    mcp._configure(
        library=FakeLibrary(),
        session_factory=_memo_session_factory(),
        byte_store={},
        runtime=foley.RuntimeConfig.default(),
    )
    yield
    mcp._STATE.clear()
    mcp._STATE.update(saved)


def test_foley_score_and_guide_tools_are_json_safe(mcp_wired):
    out = mcp.foley_score("A door creaks and rain falls.")
    assert json.dumps(out)
    assert set(out) == {"timeline", "events", "n_sounds", "rationale"}
    assert out["timeline"]["items"] or out["n_sounds"] == 0
    guide = mcp.foley_guide()
    assert json.dumps(guide) and "restraint" in guide["guide"].lower()
    # both are registered in the stable tool surface
    names = {t.__name__ for t in mcp.TOOLS}
    assert {"foley_score", "foley_guide"} <= names


def test_ai_first_surface_is_exported():
    for name in ("score", "ScoreResult", "install_agent_kit", "make_http_app"):
        assert hasattr(foley, name) and name in foley.__all__
