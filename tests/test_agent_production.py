"""Post-v1 agent production — authenticated HTTP MCP transport + local-LLM SELECT rungs.

The bearer gate, fail-closed auth, and the local-LLM adapters (with an injected fake client)
run in CI; the real HTTP app build (py2mcp/fastmcp) and any live endpoint are guarded.
"""

import asyncio
import json
import sys

import pytest

np = pytest.importorskip("numpy")

from foley.agent import mcp  # noqa: E402


# --- HTTP transport: fail-closed auth + bearer gate -------------------------


def test_make_http_app_is_fail_closed_without_tokens():
    with pytest.raises(ValueError):
        mcp.make_http_app(auth=None)
    with pytest.raises(ValueError):
        mcp.make_http_app(auth={"bearer_tokens": []})


@pytest.mark.parametrize("bad", ["", "   ", "short", None])
def test_a_blank_or_short_token_is_refused_not_dropped(bad):
    """A header-less request reads as the empty token: accepting "" would open the server."""
    with pytest.raises(ValueError, match="blank or shorter"):
        mcp.make_http_app(auth={"bearer_tokens": ["a" * 32, bad]})


def test_a_passphrase_in_the_env_is_not_split_into_weak_tokens(monkeypatch):
    monkeypatch.setenv("FOLEY_MCP_TOKEN", "correct horse battery staple")
    monkeypatch.setattr(mcp, "build_mcp_server", lambda **kw: pytest.fail("built"))
    with pytest.raises(SystemExit):  # argparse error: refused before anything is built
        mcp._cli(["--http"])


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_bearer_asgi_gate():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    mw = mcp._BearerAuthASGI(inner, {"secret"})
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {}

    # anonymous HTTP → 401, inner never called
    _run(mw({"type": "http", "headers": []}, receive, send))
    assert sent[0]["status"] == 401 and seen == []
    # wrong token → 401
    sent.clear()
    _run(mw({"type": "http", "headers": [(b"authorization", b"Bearer nope")]}, receive, send))
    assert sent[0]["status"] == 401 and seen == []
    # correct token → passes through to the app
    _run(mw({"type": "http", "headers": [(b"authorization", b"Bearer secret")]}, receive, send))
    assert seen == ["http"]
    # non-HTTP scopes (lifespan) pass through untouched
    _run(mw({"type": "lifespan"}, receive, send))
    assert seen == ["http", "lifespan"]


def test_make_http_app_builds_a_gated_asgi_app():
    pytest.importorskip("py2mcp")
    pytest.importorskip("fastmcp")
    app = mcp.make_http_app(auth={"bearer_tokens": ["t1" * 8, "t2" * 8]})
    assert isinstance(app, mcp._BearerAuthASGI)
    assert callable(app)  # ASGI app


def test_cli_http_serves_with_its_session_tokens_and_offline_posture(monkeypatch):
    """``foley-mcp --http`` reaches uvicorn (it raised TypeError on ``session``), takes
    whitespace-separated tokens from the env, and holds ``--offline`` for its lifetime."""
    import types

    import foley

    built, served = {}, {}

    class _FakeServer:
        def http_app(self, **kw):
            built["http_app"] = kw
            return "inner-app"

    def fake_build(**kw):
        built.update(kw)
        return _FakeServer()

    def fake_run(app, **kw):
        served.update(app=app, obs_on=foley.obs.is_enabled(), **kw)

    monkeypatch.setattr(mcp, "build_mcp_server", fake_build)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_run))
    old, new, cli = "o" * 16, "n" * 16, "c" * 16
    monkeypatch.setenv("FOLEY_MCP_TOKEN", f" {old}  {new} ")
    was_on = foley.obs.is_enabled()
    foley.obs.enable()
    try:
        argv = ["--http", "--offline", "--session", "s1", "--token", cli, "--port", "9"]
        assert mcp._cli(argv) == 0
        assert foley.obs.is_enabled() is True  # posture restored after the server stops
    finally:
        (foley.obs.enable if was_on else foley.obs.disable)()
    assert built["session"] == "s1" and built["runtime"].offline
    assert served["obs_on"] is False  # telemetry off while serving
    assert (served["host"], served["port"]) == ("127.0.0.1", 9)
    assert served["app"]._tokens == {cli, old, new}


# --- local-LLM SELECT rungs (OpenAI-compatible; injected fake client) -------


class _FakeClient:
    """A fake OpenAI client whose chat.completions.create returns canned JSON content."""

    def __init__(self, content):
        create = lambda **kw: type(  # noqa: E731
            "R",
            (),
            {
                "choices": [type("C", (), {"message": type("M", (), {"content": content})()})()],
                "model": "fake-local",
            },
        )()
        self.chat = type("Chat", (), {"completions": type("Cmp", (), {"create": staticmethod(create)})()})()


def test_local_llm_decomposer_parses_events(monkeypatch):
    monkeypatch.setenv("FOLEY_APPROVE_UNKNOWN_COST", "1")  # a real rung: cost unknown (#57)
    from foley.agent.local_llm import LocalLLMDecomposer

    client = _FakeClient(
        json.dumps(
            {
                "events": [
                    {"query": "rain", "layer": "ambience", "diegetic": True, "salience": "high", "audioset": ["Rain"]},
                    {"query": "door", "layer": "sfx_fg", "diegetic": True, "salience": "medium", "audioset": ["Door"]},
                ]
            }
        )
    )
    events = LocalLLMDecomposer(client=client).decompose("it rained and a door shut", max_events=5)
    assert [e.query for e in events] == ["rain", "door"]


def test_local_llm_judge_and_refiner(monkeypatch):
    monkeypatch.setenv("FOLEY_APPROVE_UNKNOWN_COST", "1")  # a real rung: cost unknown (#57)
    from foley.agent.local_llm import LocalLLMJudge, LocalLLMRefiner
    from foley.base import Candidate, LicenseRecord, SoundEvent, SoundRecord, VerifyLevel

    rec = SoundRecord(id="x", caption="steady rain", tags=["rain"], license=LicenseRecord(source="t", license_id="CC0-1.0"))
    event = SoundEvent(query="rain on a window", audioset=["Rain"])
    verdict = LocalLLMJudge(client=_FakeClient(json.dumps({"match": True, "confidence": 0.88, "reason": "rain"}))).judge(
        event, Candidate(sound=rec), level=VerifyLevel.judge
    )
    assert verdict.match is True and abs(verdict.confidence - 0.88) < 1e-9
    assert verdict.level == VerifyLevel.judge

    refiner = LocalLLMRefiner(client=_FakeClient(json.dumps({"paraphrases": ["rain", "heavy rain", "downpour"]})))
    out = refiner.refine("rain", n=3)
    assert out[0] == "rain" and "downpour" in out and len(out) <= 3


def test_default_resolvers_prefer_local_llm_when_configured(monkeypatch):
    monkeypatch.setenv("FOLEY_LLM_BASE_URL", "http://localhost:11434/v1")
    from foley.agent.decompose import _default_decomposer
    from foley.agent.local_llm import LocalLLMDecomposer, LocalLLMJudge, LocalLLMRefiner
    from foley.agent.refine import _default_refiner
    from foley.agent.verify import _default_judge
    from foley.base import VerifyLevel

    assert isinstance(_default_decomposer(), LocalLLMDecomposer)
    assert isinstance(_default_judge(VerifyLevel.judge), LocalLLMJudge)
    assert isinstance(_default_refiner(), LocalLLMRefiner)


def test_default_resolvers_not_local_without_config(monkeypatch):
    monkeypatch.delenv("FOLEY_LLM_BASE_URL", raising=False)
    from foley.agent.decompose import _default_decomposer
    from foley.agent.local_llm import LocalLLMDecomposer

    assert not isinstance(_default_decomposer(), LocalLLMDecomposer)


def test_local_llm_module_is_openai_free_at_import():
    # importing the module must NOT pull `openai` (lazy inside the call path only)
    code = "import sys, foley.agent.local_llm; assert 'openai' not in sys.modules"
    import subprocess

    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
