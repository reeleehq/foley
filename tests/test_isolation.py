"""Spend and egress honesty at the public interface (#58, #54).

#58: a key being present never turns a default call into a paid one, and the suite makes
no network call with every provider key set. #54: ``with foley.offline():`` (or
``$FOLEY_OFFLINE``) blocks every external path through the Python API — sources, the
generate and pull façades, and the LLM rungs — not only the MCP tool.
"""

import os
import socket
import sys

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.agent.llm import resolve_llm  # noqa: E402
from foley.base import LicenseRecord, SoundRecord  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.requirements import provider_key_env_vars  # noqa: E402
from foley.runtime import EgressBlocked  # noqa: E402

DEMO = "The heavy oak door creaked as rain fell and thunder rolled."


@pytest.fixture(autouse=True)
def _run_store():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


@pytest.fixture
def every_key_set(monkeypatch):
    """Set every provider credential foley knows about (after the suite's scrub)."""
    for name in provider_key_env_vars():
        monkeypatch.setenv(name, f"test-{name.lower()}")
    return provider_key_env_vars()


def _library():
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    from conftest import FakeEmbedder

    emb = FakeEmbedder()
    idx = MemoryIndex(dim=emb.dim)
    lib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=emb)
    for sid, caption in [
        ("door", "heavy wooden door creaking open"),
        ("rain", "steady rain ambience on a window"),
        ("thunder", "distant thunder rumble in a storm"),
    ]:
        lic = LicenseRecord(
            source="test", license_id="CC0-1.0", commercial_ok=True, rights_verified=True
        )
        rec = SoundRecord(
            id=sid, caption=caption, tags=[sid], duration_s=2.0, uri=f"test://{sid}", license=lic
        )
        lib.add(rec, vector=emb.embed_text(caption)[0])
    return lib


# ---------------------------------------------------------------------------
# #58 — no implicit paid calls
# ---------------------------------------------------------------------------


def test_provider_keys_cover_every_paid_source():
    keys = provider_key_env_vars()
    assert {"ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FREESOUND_API_KEY"} <= set(keys)


def test_key_presence_never_selects_a_paid_llm(every_key_set):
    assert resolve_llm() == "fake"


def test_find_and_score_make_no_network_call_with_every_key_set(every_key_set):
    """The acceptance line: defaults stay hermetic even with every key in the environment."""
    lib = _library()
    hits = foley.find(DEMO, library=lib, verify="listen")
    assert hits, "the fake rungs still resolve sounds"
    result = foley.score(DEMO, library=lib)
    assert result.timeline.items


@pytest.mark.network_trip_expected
def test_socket_guard_blocks_outbound_connections():
    with pytest.raises(RuntimeError, match="FOLEY_LIVE_API_TESTS"):
        socket.create_connection(("192.0.2.1", 443), timeout=0.01)


def test_llm_opt_in_is_explicit_and_loud(monkeypatch):
    with pytest.raises(ValueError, match="must be one of"):
        resolve_llm("claude")
    pytest.importorskip("anthropic")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        resolve_llm("anthropic")  # no key → names the env var
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert resolve_llm("anthropic") == "anthropic"
    monkeypatch.setenv("FOLEY_LLM", "anthropic")
    assert resolve_llm() == "anthropic"  # the env opt-in


def test_local_llm_needs_an_endpoint(monkeypatch):
    with pytest.raises(RuntimeError, match="FOLEY_LLM_BASE_URL"):
        resolve_llm("local")
    monkeypatch.setenv("FOLEY_LLM_BASE_URL", "http://localhost:11434/v1")
    assert resolve_llm() == "local"  # a loopback endpoint is the free default


def test_a_remote_openai_compatible_endpoint_is_never_implicit(monkeypatch):
    """A cloud endpoint may bill: it needs llm='local' even online."""
    monkeypatch.setenv("FOLEY_LLM_BASE_URL", "https://api.openai.com/v1")
    assert resolve_llm() == "fake"
    assert resolve_llm("local") == "local"


def test_fit_eval_stays_deterministic_with_a_local_endpoint(monkeypatch):
    from foley.agent.verify import StringOverlapJudge, _default_fit_judge

    monkeypatch.setenv("FOLEY_LLM_BASE_URL", "http://localhost:11434/v1")
    assert isinstance(_default_fit_judge("judge"), StringOverlapJudge)


def test_an_unused_key_warns_once(monkeypatch):
    import foley.agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "_warned_unused_key", False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.warns(UserWarning, match="no longer opts in"):
        resolve_llm()
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        resolve_llm()  # second time: silent


def test_capability_report_names_the_resolved_llm(every_key_set):
    assert foley.requirements.capability_report()["llm"] == "fake"


# ---------------------------------------------------------------------------
# #54 — offline holds on every Python path
# ---------------------------------------------------------------------------


def test_offline_blocks_external_generation(every_key_set):
    with foley.offline():
        with pytest.raises(EgressBlocked, match="elevenlabs"):
            foley.generate("a door creaks", backend="elevenlabs", library=_library())


def test_offline_blocks_an_injected_external_adapter(every_key_set):
    from foley.sources.elevenlabs.adapter import ElevenLabsAdapter

    def must_not_be_called(*a, **k):  # pragma: no cover - the gate fires first
        raise AssertionError("transport called under offline()")

    adapter = ElevenLabsAdapter(http=must_not_be_called)
    with foley.offline():
        with pytest.raises(EgressBlocked):
            foley.generate("a door creaks", backend="elevenlabs", adapter=adapter)


def test_offline_blocks_external_retrieval(every_key_set):
    with foley.offline():
        with pytest.raises(EgressBlocked, match="freesound"):
            foley.add_from("freesound", query="door", library=_library())


def test_offline_blocks_the_paid_llm(every_key_set, monkeypatch):
    pytest.importorskip("anthropic")
    with foley.offline():
        with pytest.raises(EgressBlocked, match="anthropic"):
            foley.find(DEMO, library=_library(), llm="anthropic")
        monkeypatch.setenv("FOLEY_LLM_BASE_URL", "http://llm.example.com/v1")
        assert resolve_llm() == "fake"  # a remote endpoint is never the implicit default
        with pytest.raises(EgressBlocked, match="local"):
            resolve_llm("local")  # and asked for explicitly, it is external
        monkeypatch.setenv("FOLEY_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
        assert resolve_llm() == "local"  # a loopback endpoint stays allowed


def test_offline_env_var_applies_without_a_scope(monkeypatch, every_key_set):
    monkeypatch.setenv("FOLEY_OFFLINE", "1")
    monkeypatch.setenv("FOLEY_OBS", "1")
    assert foley.runtime.is_offline()
    assert not foley.obs.is_enabled()  # telemetry off too, not only egress
    with pytest.raises(EgressBlocked):
        foley.generate("a door creaks", backend="elevenlabs", library=_library())


def test_an_injected_paid_rung_is_refused_offline(every_key_set):
    """The check runs when the rung is called, not only when a default is resolved."""
    from foley.agent.verify import AnthropicJudge

    class _Boom:
        class messages:  # noqa: N801 - mimics the SDK attribute
            @staticmethod
            def create(**kw):  # pragma: no cover - the gate fires first
                raise AssertionError("model called under offline()")

    judge = AnthropicJudge(client=_Boom())
    with foley.offline():
        with pytest.raises(EgressBlocked, match="anthropic"):
            foley.find(DEMO, library=_library(), judge=judge, verify="judge")


def test_find_degrades_offline_with_an_external_generator(every_key_set):
    """An external fallback backend under offline() is skipped, not a crash."""
    with foley.offline():
        hits = foley.find(DEMO, library=_library(), backend="elevenlabs")
    assert isinstance(hits, list)


def test_local_sources_still_run_offline():
    from foley.sources.registry import require_source_egress

    with foley.offline():
        require_source_egress("stable_audio")  # local: no raise
