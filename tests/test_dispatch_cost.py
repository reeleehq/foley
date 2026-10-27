"""The one dispatch path, cost, the generations cache and loud errors (#53 #57 #59 #64).

Every test drives the public verbs (``foley.generate`` / ``find`` / ``add_from`` /
``estimate``) with injected adapters that count their calls, so "nothing was paid for"
is asserted directly.
"""

import io

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.agent.policy import Budget  # noqa: E402
from foley.base import Candidate, CandidateOrigin, SoundRecord  # noqa: E402
from foley.cost import BudgetExceeded, CostApprovalRequired  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.sources._dispatch import UnsupportedParameter  # noqa: E402
from foley.sources.base import (  # noqa: E402
    GeneratedClip,
    SourceConfigurationError,
    generated_license,
)
from foley.sources.registry import SOURCE_REGISTRY, register_source  # noqa: E402

SR = 16_000
DEMO = "The heavy oak door creaked as rain fell outside."


@pytest.fixture(autouse=True)
def _run_store():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _wav(freq=440.0, *, silent=False, dur=0.6):
    t = np.linspace(0.0, dur, int(SR * dur), endpoint=False, dtype=np.float32)
    y = np.zeros_like(t) if silent else 0.5 * np.sin(2 * np.pi * freq * t)
    buf = io.BytesIO()
    sf.write(buf, y.astype(np.float32), SR, format="WAV")
    return buf.getvalue()


class CountingAdapter:
    """A generate adapter that counts calls and returns a fresh tone each time."""

    def __init__(self, config, *, silent=False):
        self.config = config
        self.name = config["name"]
        self.calls = 0
        self.silent = silent

    def generate(self, prompt, **affordances):
        self.calls += 1
        lic = generated_license(
            source=self.name,
            license_id="Stability-Community",
            generator_model="fake-1",
            generation_prompt=prompt,
        )
        rec = SoundRecord(id=f"{self.name}:pending", license=lic, caption=prompt)
        cand = Candidate(sound=rec, origin=CandidateOrigin.generated)
        audio = _wav(300 + 40 * self.calls, silent=self.silent)
        return GeneratedClip(audio_bytes=audio, candidate=cand, notes=[])


def _config(name, pricing, **extra):
    return {
        "name": name,
        "kind": "generate",
        "supported_affordances": ["prompt", "duration_s", "seed"],
        "on_unsupported_param": "warn",
        "native_defaults": {"duration_min_s": 0.5, "duration_max_s": 30.0},
        "data_egress": "external",
        "pricing": pricing,
        **extra,
    }


@pytest.fixture
def paid_source():
    """Register a $0.40-per-call external generator; unregister afterwards."""
    made = []

    def make(name="paidgen", *, amount=0.40, unit="per_call", silent=False):
        cfg = _config(name, {"unit": unit, "amount_usd": amount} if unit else None)
        adapter = CountingAdapter(cfg, silent=silent)
        register_source(name, cfg, adapter)
        made.append(name)
        return adapter

    yield make
    for name in made:
        SOURCE_REGISTRY.pop(name, None)


def _el_adapter(transport=None, *, plan="elevenlabs-paid-plan", api_key="k"):
    from foley.sources.elevenlabs.adapter import ElevenLabsAdapter

    def must_not_call(*a, **k):
        raise AssertionError("the ElevenLabs API must not be called")

    return ElevenLabsAdapter(api_key=api_key, http=transport or must_not_call, plan=plan)


# ---------------------------------------------------------------------------
# #53 — one dispatch path; drops are raised or visible on the result
# ---------------------------------------------------------------------------


def test_a_meaning_carrying_parameter_raises_before_any_call(library):
    """The acceptance line: seed on ElevenLabs (non-deterministic) raises."""
    with pytest.raises(UnsupportedParameter, match="seed"):
        foley.generate("a door creaks", backend="elevenlabs", adapter=_el_adapter(),
                       library=library, seed=1)


def test_under_warn_every_drop_is_on_the_returned_candidate(library, paid_source):
    paid_source("droppy", amount=0.01)
    with pytest.warns(UserWarning, match="steps"):
        cand = foley.generate("a door creaks", backend="droppy", library=library,
                              steps=12, negative_prompt="hum", on_unsupported="warn",
                              duration_s=99)
    joined = " | ".join(cand.notes)
    assert "steps=12" in joined and "negative_prompt='hum'" in joined
    assert "clamped to 30 s" in joined
    assert cand.cost_estimate_usd == pytest.approx(0.01)


def test_an_ordinary_drop_is_noted_without_raising(library, paid_source):
    paid_source("droppy2", amount=0.01)
    with pytest.warns(UserWarning):
        cand = foley.generate("rain", backend="droppy2", library=library, steps=8)
    assert any("steps=8" in n for n in cand.notes)


def test_add_from_notes_unsupported_search_parameters(library):
    class StubSearch:
        config = {"name": "stubsearch", "supported_affordances": ["query", "k", "license"],
                  "data_egress": "external"}

        def search(self, query, **kw):
            assert "ucs_category" not in kw  # dropped before the source sees it
            return []

    report = foley.add_from("stubsearch", query="door", library=library,
                            adapter=StubSearch(), ucs_category="DOORWood")
    assert any("ucs_category" in n for n in report.notes)


# ---------------------------------------------------------------------------
# #57 — cost model: None = unknown, cumulative cap, stop before the first paid call
# ---------------------------------------------------------------------------


def test_estimate_is_none_when_unknown_never_zero(paid_source):
    paid_source("mystery", unit=None)
    assert foley.estimate("generate", backend="mystery") is None
    assert foley.estimate("generate", backend="stable_audio") == 0.0
    assert foley.estimate("generate", backend="elevenlabs", duration_s=3) == pytest.approx(0.006)


def test_unknown_cost_needs_approval(library, paid_source):
    adapter = paid_source("mystery2", unit=None)
    with pytest.raises(CostApprovalRequired):
        foley.generate("a door creaks", backend="mystery2", library=library)
    assert adapter.calls == 0
    cand = foley.generate("a door creaks", backend="mystery2", library=library,
                          budget=Budget(approve_unknown_cost=True))
    assert adapter.calls == 1 and cand.cost_estimate_usd is None


def test_a_call_over_the_default_one_dollar_cap_is_refused(library, paid_source):
    adapter = paid_source("pricey", amount=2.0)
    with pytest.raises(BudgetExceeded):
        foley.generate("a door creaks", backend="pricey", library=library)
    assert adapter.calls == 0


def test_find_stops_before_the_first_paid_call_over_budget(paid_source, fake_embedder):
    """The acceptance line: a find whose estimate exceeds the budget never pays."""
    idx = MemoryIndex(dim=fake_embedder.dim)
    empty = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)
    adapter = paid_source("pricey2", amount=0.30)  # 6 events x $0.30 = $1.80 > $1
    assert foley.estimate("find", backend="pricey2") == pytest.approx(1.80)
    with pytest.raises(BudgetExceeded, match="upper bound"):
        foley.find(DEMO, library=empty, backend="pricey2", budget=Budget(max_usd=1.0))
    assert adapter.calls == 0
    foley.find(DEMO, library=empty, backend="pricey2", budget=Budget(max_usd=2.0))
    assert adapter.calls >= 1  # within budget, it does generate


def test_the_cap_is_cumulative_across_calls_in_one_run(paid_source, library):
    from foley.cost import spend_scope

    adapter = paid_source("sixty", amount=0.60)
    with spend_scope(Budget(max_usd=1.0)) as budget:
        foley.generate("a door creaks", backend="sixty", library=library)
        with pytest.raises(BudgetExceeded):
            foley.generate("rain on a roof", backend="sixty", library=library)
    assert adapter.calls == 1 and budget.spent_usd == pytest.approx(0.60)


def test_a_stricter_inner_budget_still_applies(paid_source, library):
    from foley.cost import spend_scope

    adapter = paid_source("fifty", amount=0.50)
    with spend_scope(Budget(max_usd=10.0)):
        with pytest.raises(BudgetExceeded):
            foley.generate("a door", backend="fifty", library=library,
                           budget=Budget(max_usd=0.10))
    assert adapter.calls == 0


def test_paid_llm_calls_count_toward_the_cap(monkeypatch, library):
    """'$1 per run, LLM calls included': Anthropic calls are priced, so they are capped."""
    pytest.importorskip("anthropic")
    from foley.agent.llm import llm_call_estimate

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm_call_estimate("anthropic", max_tokens=500) > 0
    assert foley.estimate("find", llm="anthropic") > 1.0  # 6 events x 10 judge calls ...
    with pytest.raises(BudgetExceeded, match="upper bound"):
        foley.find(DEMO, library=library, llm="anthropic", budget=Budget(max_usd=1.0))


def test_a_chosen_paid_llm_gets_a_default_cap_that_fits_a_default_run(monkeypatch, library):
    """#88: find(llm='anthropic') with the defaults is not refused before its first call."""
    from foley.agent import llm
    from foley.cost import default_max_usd as _default_max_usd
    from foley.cost import DEFAULT_MAX_USD

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("FOLEY_LLM", raising=False)
    assert _default_max_usd(None) == _default_max_usd("fake") == DEFAULT_MAX_USD
    assert _default_max_usd("anthropic") == 3.0
    monkeypatch.setattr(llm, "_require_anthropic", lambda: None)  # no SDK needed here
    assert foley.estimate("find", llm="anthropic") < _default_max_usd("anthropic")
    # The default cap still holds a run whose bound is over it (k=20: about $4.6).
    with pytest.raises(BudgetExceeded, match=r"\$3\.00 cap"):
        foley.find(DEMO, library=library, llm="anthropic", k=20)
    monkeypatch.setenv("FOLEY_LLM", "anthropic")
    assert _default_max_usd(None) == 3.0  # the operator's choice counts too
    # score() has one cap for the whole run, sized the same way (refused at $3, not $1).
    with pytest.raises(BudgetExceeded, match=r"\$3\.00 cap"):
        foley.score([DEMO], library=library, llm="anthropic", max_events=10)
    # So has the MCP server, for its lifetime, when its operator chose Claude.
    from foley.agent import mcp

    mcp._STATE["budget"], mcp._STATE["max_usd"] = None, None
    assert mcp._server_budget().max_usd == 3.0
    mcp._STATE["budget"] = None


def test_a_paid_rung_is_charged_its_actual_usage(monkeypatch):
    from types import SimpleNamespace

    from foley.agent.verify import AnthropicJudge
    from foley.base import SoundEvent
    from foley.cost import spend_scope

    class _Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                text = SimpleNamespace(type="text", text='{"match": true, "confidence": 0.9, "reason": "ok"}')
                return SimpleNamespace(content=[text], model="claude-opus-4-8", stop_reason="end_turn",
                                       usage=SimpleNamespace(input_tokens=1000, output_tokens=100))

    cand = Candidate(sound=SoundRecord(id="x", caption="door"))
    with spend_scope(Budget(max_usd=1.0)) as budget:
        AnthropicJudge(client=_Client()).judge(SoundEvent(query="door"), cand)
    assert budget.spent_usd == pytest.approx((1000 * 5 + 100 * 25) / 1e6)


def test_a_failed_call_that_may_have_billed_is_still_charged(paid_source, library):
    from foley.cost import spend_scope

    adapter = paid_source("timeout", amount=0.40)

    def boom(prompt, **kw):
        raise TimeoutError("read timeout after the request was accepted")

    adapter.generate = boom
    with spend_scope(Budget(max_usd=1.0)) as budget:
        for _ in range(2):
            with pytest.raises(foley.GenerationError):
                foley.generate("a door", backend="timeout", library=library)
        with pytest.raises(BudgetExceeded):
            foley.generate("a door", backend="timeout", library=library)
    assert budget.spent_usd == pytest.approx(0.80)


def test_a_stream_does_not_lend_its_budget_to_the_caller(paid_source, library, fake_embedder):
    from foley.cost import active_budget

    stream = foley.find(DEMO, library=library, stream=True, budget=Budget(max_usd=5.0))
    next(stream, None)
    assert active_budget() is None  # between items, the stream's budget is not in force


def test_an_mcp_server_has_one_cap_whatever_session_ids_the_agent_sends(paid_source, library):
    from foley.agent import mcp

    adapter = paid_source("mcpgen", amount=0.40)
    mcp._configure(library=library)
    mcp._STATE["budget"] = None
    results = [
        mcp.foley_generate(f"door {i}", backend="mcpgen", session=f"invented-{i}")
        for i in range(4)
    ]
    assert [r["ok"] for r in results] == [True, True, False, False]
    assert adapter.calls == 2 and "cap" in results[2]["error"]
    assert mcp.foley_status(session="anything")["spent_usd"] == pytest.approx(0.80)
    mcp._STATE["budget"] = None


# ---------------------------------------------------------------------------
# #59 — paid bytes are never lost and never paid for twice
# ---------------------------------------------------------------------------


def test_an_identical_paid_request_is_a_cache_hit(library, paid_source):
    adapter = paid_source("cached", amount=0.05)
    first = foley.generate("a door creaks", backend="cached", library=library, duration_s=2)
    second = foley.generate("a door creaks", backend="cached", library=library, duration_s=2)
    assert adapter.calls == 1
    assert second.sound.id == first.sound.id
    assert second.cost_actual_usd == 0.0
    assert any("generations cache" in n for n in second.notes)
    foley.generate("a door creaks", backend="cached", library=library, duration_s=2,
                   reuse_cached=False)
    assert adapter.calls == 2


def test_a_quarantined_generation_keeps_its_bytes(library, paid_source,
                                                  _in_memory_generations_cache):
    paid_source("silent", amount=0.05, silent=True)
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("a door creaks", backend="silent", library=library)
    assert exc.value.status == "quarantined"
    cache = _in_memory_generations_cache
    (entry,) = cache.requests.values()
    assert cache.audio[entry["content_key"]]  # the paid bytes are retrievable
    assert any(key in str(exc.value) or key in " ".join(r_n for r in exc.value.report.results
                                                         for r_n in r.notes)
               for key in cache.requests)


def test_a_refused_generation_names_its_kept_bytes_on_every_surface(
    library, paid_source, _in_memory_generations_cache
):
    """#107: the error, the result and the MCP tool all carry the cache key."""
    from foley.agent import mcp

    paid_source("silent3", amount=0.05, silent=True)
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("a door creaks", backend="silent3", library=library)
    (entry,) = _in_memory_generations_cache.requests.values()
    assert exc.value.cache_key == entry["content_key"]
    assert exc.value.report.results[0].cache_key == exc.value.cache_key
    assert foley.generations.get(exc.value.cache_key) == _in_memory_generations_cache.audio[
        entry["content_key"]
    ]
    mcp._configure(library=library)
    mcp._STATE["budget"] = None
    try:
        out = mcp.foley_generate("a door creaks", backend="silent3")
    finally:
        mcp._STATE["budget"] = None
    assert out["ok"] is False and out["status"] == "quarantined"
    assert foley.generations.get(out["cache_key"])


# ---------------------------------------------------------------------------
# #64 — the root cause reaches the caller
# ---------------------------------------------------------------------------


def test_a_missing_key_names_the_env_var_and_its_sign_up_url(library, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    adapter = _el_adapter(api_key=None)
    with pytest.raises(SourceConfigurationError) as exc:
        foley.generate("a door creaks", backend="elevenlabs", adapter=adapter, library=library)
    assert "ELEVENLABS_API_KEY" in str(exc.value)
    assert "https://elevenlabs.io/app/settings/api-keys" in str(exc.value)


def test_add_from_raises_on_a_missing_key(library, monkeypatch):
    from foley.sources.freesound.adapter import FreesoundAdapter

    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    adapter = FreesoundAdapter(http=lambda *a, **k: pytest.fail("no HTTP without a key"))
    with pytest.raises(SourceConfigurationError) as exc:
        foley.add_from("freesound", query="door", library=library, adapter=adapter)
    assert "FREESOUND_API_KEY" in str(exc.value) and "http" in str(exc.value)


def test_a_per_request_key_reaches_the_source(monkeypatch):
    """Keys resolve through ocracy's facade kit: explicit, then a bound key, then env."""
    from ocracy.kit import using_credentials

    from foley.sources.elevenlabs.adapter import ElevenLabsAdapter
    from foley.sources.freesound.adapter import FreesoundAdapter

    monkeypatch.setenv("FREESOUND_API_KEY", "server-key")
    fs = FreesoundAdapter(http=lambda *a, **k: pytest.fail("no HTTP"))
    assert fs.api_key == "server-key"
    with using_credentials(freesound="user-key", elevenlabs="user-el-key"):
        assert fs.api_key == "user-key"
        assert FreesoundAdapter(api_key="explicit").api_key == "explicit"
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        assert ElevenLabsAdapter().api_key == "user-el-key"


def test_a_backend_failure_is_chained_into_generation_error(library, paid_source):
    adapter = paid_source("flaky", amount=0.01)

    def boom(prompt, **kw):
        raise RuntimeError("upstream 503: try later")

    adapter.generate = boom
    with pytest.raises(foley.GenerationError, match="upstream 503") as exc:
        foley.generate("a door creaks", backend="flaky", library=library)
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_a_quarantined_request_is_not_replayed(library, paid_source):
    adapter = paid_source("silent2", amount=0.05, silent=True)
    for _ in range(2):
        with pytest.raises(foley.GenerationError):
            foley.generate("a door creaks", backend="silent2", library=library)
    assert adapter.calls == 2  # the bad result is kept, not served again


def test_a_corrupt_cache_entry_is_a_miss(library, paid_source, _in_memory_generations_cache):
    adapter = paid_source("corrupt", amount=0.05)
    foley.generate("a door creaks", backend="corrupt", library=library)
    for key in _in_memory_generations_cache.requests:
        _in_memory_generations_cache.requests[key] = {"content_key": None, "license": {}}
    cand = foley.generate("a door creaks", backend="corrupt", library=library)
    assert adapter.calls == 2 and cand.sound.id


def test_a_failed_cache_write_keeps_the_paid_sound(library, paid_source, monkeypatch):
    from foley.sources import _dispatch
    from foley.stores import GenerationsCache

    class Full(dict):
        def __setitem__(self, k, v):
            raise OSError("disk full")

    monkeypatch.setattr(_dispatch, "_default_cache", lambda: GenerationsCache(Full(), {}))
    paid_source("fullgen", amount=0.05)
    cand = foley.generate("a door creaks", backend="fullgen", library=library)
    assert cand.sound.id in library.meta
    assert any("could not keep" in n for n in cand.notes)


def test_a_cache_hit_keeps_the_adapters_notes(library, paid_source):
    adapter = paid_source("noted", amount=0.05)
    original = adapter.generate

    def with_note(prompt, **kw):
        clip = original(prompt, **kw)
        clip.notes.append("output_format substituted: flac -> mp3")
        return clip

    adapter.generate = with_note
    foley.generate("a door", backend="noted", library=library)
    second = foley.generate("a door", backend="noted", library=library)
    assert any("substituted" in n for n in second.notes)


def test_an_identical_request_spelled_differently_is_one_cache_entry(library, paid_source):
    adapter = paid_source("spelled", amount=0.05)
    foley.generate("a door", backend="spelled", library=library, duration_s=2)
    foley.generate("a door", backend="spelled", library=library, duration_s=2.0)
    assert adapter.calls == 1


def test_a_missing_extra_is_a_configuration_error(library, paid_source):
    adapter = paid_source("noextra", amount=0.05)

    def needs_torch(prompt, **kw):
        raise ModuleNotFoundError("No module named 'torch'", name="torch")

    adapter.generate = needs_torch
    with pytest.raises(SourceConfigurationError, match="pip install"):
        foley.generate("a door", backend="noextra", library=library)


def test_estimate_prices_the_call_as_it_would_be_made():
    assert foley.estimate("generate", backend="elevenlabs", duration_s=60) == pytest.approx(0.06)



# ---------------------------------------------------------------------------
# second review: bounds from the real prompt, retries, concurrency
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, tin, tout):
        self.input_tokens, self.output_tokens = tin, tout


def _fake_anthropic(*, fail_with=None, calls=None):
    from types import SimpleNamespace

    class _Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                if calls is not None:
                    calls.append(kw)
                if fail_with and len(calls or []) <= len(fail_with):
                    raise fail_with[len(calls) - 1]
                text = SimpleNamespace(type="text", text='{"events": []}')
                return SimpleNamespace(content=[text], model="claude-opus-4-8",
                                       stop_reason="end_turn", usage=_Usage(100, 50))

    return _Client()


def test_a_long_passage_is_bounded_by_its_real_length(monkeypatch):
    """A 400k-character passage cannot slip under the cap on a fixed input guess."""
    from foley.agent.decompose import AnthropicDecomposer
    from foley.cost import spend_scope

    calls = []
    with spend_scope(Budget(max_usd=1.0)) as budget:
        budget.charge(0.90)
        with pytest.raises(BudgetExceeded):
            AnthropicDecomposer(client=_fake_anthropic(calls=calls)).decompose("x" * 400_000)
    assert calls == [] and budget.spent_usd == pytest.approx(0.90)


def test_a_metered_call_is_charged_its_actual_usage_and_never_resent_after_a_timeout():
    from foley.agent.llm import metered_create
    from foley.cost import spend_scope

    with spend_scope(Budget(max_usd=1.0)) as budget:
        metered_create(_fake_anthropic(calls=[]), model="claude-opus-4-8", max_tokens=500,
                       messages=[{"role": "user", "content": "hi"}])
        assert budget.spent_usd == pytest.approx((100 * 5 + 50 * 25) / 1e6)
        calls = []
        with pytest.raises(TimeoutError):
            metered_create(_fake_anthropic(fail_with=[TimeoutError("read")], calls=calls),
                           model="claude-opus-4-8", max_tokens=500, messages=[])
        assert len(calls) == 1  # not re-sent
        assert budget.spent_usd > (100 * 5 + 50 * 25) / 1e6  # the reservation stays


def test_a_rejected_metered_call_is_retried_without_double_charging():
    anthropic = pytest.importorskip("anthropic")
    import httpx2 as httpx  # noqa: F401 - the SDK's HTTP library (1.x)

    from foley.agent.llm import metered_create
    from foley.cost import spend_scope

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rejected = anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req),
                                        body=None)
    calls = []
    with spend_scope(Budget(max_usd=1.0)) as budget:
        metered_create(_fake_anthropic(fail_with=[rejected], calls=calls), sleep=lambda s: None,
                       model="claude-opus-4-8", max_tokens=500, messages=[])
    assert len(calls) == 2
    assert budget.spent_usd == pytest.approx((100 * 5 + 50 * 25) / 1e6)


def test_a_paid_post_is_not_resent_after_a_transport_error():
    from foley.sources.resilience import SourceUnavailable, make_resilient_transport_from_config

    sent = []

    def flaky(method, url, **kw):
        sent.append(method)
        raise TimeoutError("read timeout")

    paid = make_resilient_transport_from_config(
        {"rate": None, "pricing": {"unit": "per_second", "amount_usd": 0.002}},
        base=flaky, sleep=lambda s: None)
    with pytest.raises(TimeoutError):
        paid("POST", "https://api.example/x")
    assert sent == ["POST"]
    free = make_resilient_transport_from_config(
        {"rate": None, "pricing": {"unit": "free"}}, base=flaky, sleep=lambda s: None)
    with pytest.raises(SourceUnavailable):
        free("POST", "https://api.example/x")
    assert len(sent) > 2  # a free source keeps its retries


def test_concurrent_calls_cannot_all_pass_before_any_is_counted(paid_source, library):
    import threading

    from foley.cost import spend_scope

    gate = threading.Barrier(4)
    adapter = paid_source("concurrent", amount=0.40)
    original = adapter.generate

    def slow(prompt, **kw):
        return original(prompt, **kw)

    adapter.generate = slow
    budget = Budget(max_usd=1.0)
    errors = []

    def worker(i):
        gate.wait()
        try:
            with spend_scope(budget):
                foley.generate(f"door {i}", backend="concurrent", library=library)
        except BudgetExceeded as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert adapter.calls == 2 and len(errors) == 2
    assert budget.spent_usd == pytest.approx(0.80)


def test_a_rights_refusal_or_ingest_error_replays_the_paid_bytes(library, paid_source,
                                                                 _in_memory_generations_cache):
    adapter = paid_source("replay", amount=0.05)
    foley.generate("a door", backend="replay", library=library)
    for key, entry in list(_in_memory_generations_cache.requests.items()):
        _in_memory_generations_cache.requests[key] = {**entry, "status": "error"}
    foley.generate("a door", backend="replay", library=library)
    assert adapter.calls == 1  # an unrelated ingest error does not re-pay


def test_loopback_means_this_machine_only():
    from foley.agent.llm import is_loopback_host

    assert is_loopback_host("127.0.0.1") and is_loopback_host("localhost")
    assert not is_loopback_host("127.example.com")


def test_estimate_score_sums_one_find_per_segment(paid_source):
    paid_source("seg", amount=0.01)
    one = foley.estimate("find", backend="seg", context="a door")
    assert foley.estimate("score", backend="seg", segments=["a door", "rain"]) == pytest.approx(2 * one)


def test_an_over_budget_mcp_find_is_a_json_refusal(library, monkeypatch):
    from foley.agent import mcp

    def over_budget(*a, **k):
        raise BudgetExceeded("this find run (upper bound) would cost ~$3.00, over its $1.00 cap")

    monkeypatch.setattr(foley, "find", over_budget)
    mcp._configure(library=library)
    rows = mcp.foley_find(DEMO)
    assert rows == [{"ok": False, "status": "refused", "error": rows[0]["error"]}]
    assert "cap" in rows[0]["error"]


# ---------------------------------------------------------------------------
# third review
# ---------------------------------------------------------------------------


def test_a_refused_reservation_leaves_no_half_reservation(monkeypatch):
    from foley.cost import authorize, spend_scope

    outer, inner = Budget(max_usd=10.0), Budget(max_usd=1.0)
    with spend_scope(outer), spend_scope(inner):
        real_reserve = inner.reserve

        def raced(est, *, what):  # another thread filled the inner budget meanwhile
            inner.charge(0.9)
            real_reserve(est, what=what)

        monkeypatch.setattr(inner, "reserve", raced)
        with pytest.raises(BudgetExceeded):
            authorize(0.5, what="a call")
    assert outer.spent_usd == 0.0


def test_bad_cached_bytes_are_replayed_at_most_once(library, paid_source,
                                                    _in_memory_generations_cache, monkeypatch):
    adapter = paid_source("badbytes", amount=0.05)
    original = adapter.generate

    def html_body(prompt, **kw):
        clip = original(prompt, **kw)
        clip.audio_bytes = b"<html>error</html>"
        return clip

    adapter.generate = html_body
    for _ in range(3):
        with pytest.raises(foley.GenerationError):
            foley.generate("a door", backend="badbytes", library=library)
    assert adapter.calls == 2  # paid, replayed once, then generated anew


def test_paid_sources_do_not_retry_gateway_errors():
    from foley.sources.resilience import make_resilient_transport_from_config

    sent = []

    class R:
        status_code = 504
        headers = {}

    def gateway(method, url, **kw):
        sent.append(method)
        return R()

    paid = make_resilient_transport_from_config(
        {"rate": None, "pricing": {"unit": "per_call", "amount_usd": 1}},
        base=gateway, sleep=lambda s: None)
    paid("POST", "https://api.example/x")
    assert sent == ["POST"]


def test_an_injected_sdk_client_is_used_without_its_retries():
    from foley.agent.llm import metered_create

    seen = {}

    class Client:
        def with_options(self, **kw):
            seen.update(kw)
            return _fake_anthropic(calls=[])

    metered_create(Client(), model="claude-opus-4-8", max_tokens=10, messages=[])
    assert seen == {"max_retries": 0}


def test_llm_prices_come_from_falaw_and_unlisted_models_are_unknown():
    """One price table for the fleet: listed models are priced, unlisted ones are None."""
    from types import SimpleNamespace

    from foley.agent.llm import _usage_cost, llm_call_estimate

    usage = SimpleNamespace(input_tokens=1000, output_tokens=1000)
    listed = _usage_cost("claude-opus-4-7", SimpleNamespace(usage=usage))
    assert listed is not None and listed > 0  # the private table lacked this model
    assert _usage_cost("no-such-model", SimpleNamespace(usage=usage)) is None
    assert _usage_cost("claude-opus-4-7", SimpleNamespace(usage=None)) is None
    assert llm_call_estimate("anthropic", model="no-such-model", max_tokens=5) is None

@pytest.mark.parametrize("bad", [5.0, -0.1, True, "0.5"])
def test_a_bad_prompt_influence_is_refused_before_any_budget_is_reserved(
    paid_source, library, bad
):
    from foley.cost import spend_scope

    adapter = paid_source("sixty", amount=0.60)
    with spend_scope(Budget(max_usd=1.0)) as budget:
        with pytest.raises(ValueError, match="prompt_influence"):
            foley.generate("a door creaks", backend="sixty", library=library,
                           prompt_influence=bad)
    assert adapter.calls == 0 and budget.spent_usd == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_duration_is_refused_before_any_budget_is_reserved(
    paid_source, library, bad
):
    from foley.cost import spend_scope

    adapter = paid_source("sixty", amount=0.60)
    with spend_scope(Budget(max_usd=1.0)) as budget:
        with pytest.raises(ValueError, match="duration"):
            foley.generate("a door creaks", backend="sixty", library=library,
                           duration_s=bad)
    assert adapter.calls == 0 and budget.spent_usd == 0


def test_a_nan_estimate_is_unknown_cost_and_never_poisons_the_budget():
    budget = Budget(max_usd=0.0)
    with pytest.raises(CostApprovalRequired):
        budget.reserve(float("nan"), what="x")
    approved = Budget(max_usd=0.0, approve_unknown_cost=True)
    approved.reserve(float("nan"), what="x")
    assert approved.spent_usd == 0
    with pytest.raises(BudgetExceeded):
        approved.check(0.01, what="y")


# ---------------------------------------------------------------------------
# #75 — the generation vocabulary: duration_s, model, reproducibility
# ---------------------------------------------------------------------------


def test_the_old_duration_spelling_raises_naming_the_new_one(library):
    with pytest.raises(TypeError, match="duration= was renamed duration_s="):
        foley.generate("a door creaks", backend="elevenlabs", adapter=_el_adapter(),
                       library=library, duration=2)


def test_model_on_a_backend_that_cannot_pin_one_raises(library, paid_source):
    paid_source("unpinned", amount=0.01)
    with pytest.raises(UnsupportedParameter, match="model"):
        foley.generate("a door creaks", backend="unpinned", library=library,
                       model="some-model-v9")


def test_a_pinned_model_is_keyed_as_the_model():
    from foley.sources._dispatch import request_digest
    from foley.sources.elevenlabs.config import SOURCE_CONFIG as EL

    def key(**aff):
        return request_digest("elevenlabs", "rain", EL, aff, salt="paid")

    default = EL["native_defaults"]["model_id"]
    assert key(model=default) == key()  # pinning the default is the same request
    assert key(model="eleven_text_to_sound_v3") != key()


def test_generation_reproducible_follows_the_recorded_seed():
    from foley.base import LicenseRecord

    assert LicenseRecord(license_id="cc0", source="t").generation_reproducible is None
    seeded = LicenseRecord(license_id="x", source="t", is_ai_generated=True, generation_seed=7)
    assert seeded.generation_reproducible is True
    unseeded = LicenseRecord(license_id="x", source="t", is_ai_generated=True)
    assert unseeded.generation_reproducible is False


@pytest.mark.parametrize(
    "backend, affordances, key",
    [
        ("elevenlabs", {"duration_s": 2.0, "output_format": "wav"},
         "f05ae9730d9a41cdc1f57cb6418b433f468913642318e1636acb246d83e1fba9"),
        ("fal_stable_audio_3", {"duration_s": 3, "seed": 7},
         "50a9da8fb72bef0c96cb5356c80c3a8d1cc6851f5bbcf077532588c47f56adad"),
        ("stable_audio_3", {"duration_s": 1.5, "steps": 8},
         "ddf4e0127a89f04fee65310c2a955213f5d841e571b580b311633d21c8564bb9"),
    ],
)
def test_the_duration_rename_keeps_every_cache_key(backend, affordances, key):
    """Keys computed before the rename (with ``duration=``): the paid cache still hits."""
    from foley.sources._dispatch import request_digest
    from foley.sources.registry import get_source

    config = get_source(backend)["config"]
    assert request_digest(backend, "a door creaks", config, affordances, salt=None) == key


def test_the_old_duration_spelling_raises_on_every_entry_point():
    from foley.sources.elevenlabs.adapter import ElevenLabsAdapter

    with pytest.raises(TypeError, match="renamed duration_s"):
        foley.estimate("generate", backend="elevenlabs", duration=3)
    with pytest.raises(TypeError, match="renamed duration_s"):
        foley.generations.find("rain", duration=1)
    adapter = ElevenLabsAdapter(api_key="k", http=lambda *a, **k: None,
                                plan="elevenlabs-paid-plan")
    with pytest.raises(TypeError, match="renamed duration_s"):
        adapter.generate("rain", duration=2)  # called directly, below the dispatch


def test_the_order_skips_a_backend_that_cannot_pin_the_model(library, paid_source):
    unpinned = paid_source("unpinned", amount=0.01)
    cfg = {**_config("pinnable", {"unit": "per_call", "amount_usd": 0.01}),
           "supported_affordances": ["prompt", "duration_s", "seed", "model"]}
    pinnable = CountingAdapter(cfg)
    register_source("pinnable", cfg, pinnable)
    try:
        cand = foley.generate("a door creaks", backend=("unpinned", "pinnable"),
                              library=library, model="m-2")
    finally:
        SOURCE_REGISTRY.pop("pinnable", None)
    assert unpinned.calls == 0 and pinnable.calls == 1
    assert cand is not None


def _never_called(*args, **kwargs):
    raise AssertionError("the backend must not be called")


def _direct_adapters():
    from foley.sources.elevenlabs.adapter import ElevenLabsAdapter
    from foley.sources.fal.adapter import FalAdapter
    from foley.sources.fal.config import SOURCE_CONFIGS as FAL_CONFIGS
    from foley.sources.stable_audio.adapter import StableAudioAdapter
    from foley.sources.stable_audio_3.adapter import StableAudio3Adapter

    return {
        "elevenlabs": ElevenLabsAdapter(api_key="k", http=_never_called,
                                        plan="elevenlabs-paid-plan"),
        "fal": FalAdapter(FAL_CONFIGS[0], api_key="k", runner=_never_called),
        "stable_audio": StableAudioAdapter(pipeline=_never_called),
        "stable_audio_3": StableAudio3Adapter(runner=_never_called),
    }


@pytest.mark.parametrize("name", ["elevenlabs", "fal", "stable_audio", "stable_audio_3"])
def test_every_adapter_called_directly_rejects_the_old_duration(name):
    with pytest.raises(TypeError, match="renamed duration_s"):
        _direct_adapters()[name].generate("rain", duration=2)


def test_pinning_the_native_default_model_keys_as_unpinned():
    """Where generator_version differs from model_id, the default pin is still unpinned."""
    from foley.sources._dispatch import request_digest

    cfg = {**_config("versioned", {"unit": "per_call", "amount_usd": 0.01}),
           "supported_affordances": ["prompt", "model"],
           "native_defaults": {"model_id": "m-1", "generator_version": "vendor/m-1/v3"}}

    def key(**aff):
        return request_digest("versioned", "rain", cfg, aff, salt=None)

    assert key(model="m-1") == key()
    assert key(model="m-2") != key()
