"""#12 onboarding — generalized check_requirements (binary/env/importable) + capability report."""

import foley
from foley import requirements as req
from foley.weave import requirements as weave_req


def test_probe_dispatch(monkeypatch):
    # env probe reads os.environ; importable probe reads find_spec; binary reads which
    monkeypatch.setenv("FREESOUND_API_KEY", "secret")
    status = req.check_requirements(names=("FREESOUND_API_KEY",))
    assert status["FREESOUND_API_KEY"] is True
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    assert req.check_requirements(names=("FREESOUND_API_KEY",))["FREESOUND_API_KEY"] is False


def test_importable_probe(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec

    def fake_spec(name):
        return object() if name == "py2mcp" else real(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_spec)
    assert req.check_requirements(names=("py2mcp",))["py2mcp"] is True


def test_keys_derived_from_source_configs():
    reqs = req.build_requirements()
    # the env-var names + sign-up URLs come from each SOURCE_CONFIG['auth'] (SSOT)
    assert "FREESOUND_API_KEY" in reqs and reqs["FREESOUND_API_KEY"].probe == "env"
    assert "ELEVENLABS_API_KEY" in reqs
    assert "ANTHROPIC_API_KEY" in reqs
    assert reqs["FREESOUND_API_KEY"].url  # sign-up URL carried through
    # the WEAVE system binaries are merged in unchanged (binary probe)
    assert "ffmpeg" in reqs and reqs["ffmpeg"].probe == "binary"


def test_verify_and_setup_reports_never_installs():
    report = req.verify_and_setup(names=("ffmpeg", "py2mcp"))
    assert set(report["ffmpeg"]) == {"available", "purpose", "install", "url", "probe"}
    assert report["ffmpeg"]["probe"] == "binary"
    assert report["py2mcp"]["probe"] == "importable"


def test_capability_report_shape():
    rep = foley.capability_report()
    assert set(rep) == {"keys", "extras", "system", "offline", "sources", "backends", "llm", "degraded_tools"}
    assert "FREESOUND_API_KEY" in rep["keys"]  # env-probed
    assert "py2mcp" in rep["extras"]  # importable-probed
    assert "ffmpeg" in rep["system"]  # binary-probed
    assert isinstance(rep["degraded_tools"], list)


def test_capability_report_offline_posture():
    rep = foley.capability_report(runtime=foley.RuntimeConfig.offline_local())
    assert rep["offline"] is True
    assert "freesound" not in rep["sources"]  # external sources dropped offline


def test_weave_requirements_back_compat():
    # the weave-scoped check_requirements is unchanged (binary probe default)
    status = weave_req.check_requirements()
    assert set(status) == {"ffmpeg", "rubberband"}
    assert all(isinstance(v, bool) for v in status.values())
    # the Requirement dataclass gained a defaulted probe (back-compat)
    assert weave_req.REQUIREMENTS["ffmpeg"].probe == "binary"
