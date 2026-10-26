"""Tests for the SELECT stage — ``foley.agent`` (#7): find(), the ladder, the gate, obs.

The entire ``decompose → refine → search → license_gate → verify → decide → generate →
place`` loop is exercised hermetically: the deterministic fakes (KeywordDecomposer,
ClapJudge, StringOverlapJudge, KeywordRefiner) are the resolved defaults, the library is
an in-memory :class:`SoundLibrary` over the :class:`~tests.conftest.FakeEmbedder` (numpy
only — no CLAP/torch), the LLM path is tested with an injected fake ``anthropic`` client,
and every ``find()`` writes its forced-on run-manifest to an injected ``dict`` store.
"""

import subprocess
import sys
import types
from dataclasses import fields

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.agent import (  # noqa: E402
    AnthropicDecomposer,
    Budget,
    ClapJudge,
    DecideAction,
    StringOverlapJudge,
    decide,
    gate_candidates,
    search_sounds,
    verify_match,
)
from foley.base import (  # noqa: E402
    Candidate,
    CandidateOrigin,
    IntendedUse,
    Layer,
    LicenseRecord,
    Salience,
    SoundDesignTimeline,
    SoundEvent,
    SoundRecord,
    TimelineItem,
    Verdict,
    VerifyLevel,
)
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def run_store():
    """Route every ``find()``'s forced-on run-manifest to an in-memory ``dict`` (not disk)."""
    store = {}
    foley.obs.configure(run_store=store)
    yield store
    foley.obs.reset()


def _rec(sid, caption, tags=(), *, verified=True, commercial=True, voice=False):
    lic = LicenseRecord(
        source="test",
        license_id="CC0-1.0",
        commercial_ok=commercial,
        rights_verified=verified,
        contains_recognizable_voice=voice,
    )
    return SoundRecord(
        id=sid, caption=caption, tags=list(tags), duration_s=2.0, uri=f"test://{sid}", license=lic
    )


def _lib(records):
    emb = _embedder()
    idx = MemoryIndex(dim=emb.dim)
    lib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=emb)
    for r in records:
        lib.add(r, vector=emb.embed_text(r.caption)[0])
    return lib


def _embedder():
    import os

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)  # cwd-independent (robust on the Windows CI leg)
    from conftest import FakeEmbedder

    return FakeEmbedder()


def _candidate(sid, caption, *, verified=True, voice=False, clap=0.9):
    c = Candidate(sound=_rec(sid, caption, [sid], verified=verified, voice=voice))
    c.clap_score = clap
    return c


DEMO = "The heavy oak door creaked as rain fell and thunder rolled."


@pytest.fixture
def library():
    return _lib(
        [
            _rec("door", "heavy wooden door creaking open", ["door", "wood"]),
            _rec("rain", "steady rain ambience on a window", ["rain", "weather"]),
            _rec("thunder", "distant thunder rumble in a storm", ["thunder", "storm"]),
        ]
    )


# ---------------------------------------------------------------------------
# purity + smoke
# ---------------------------------------------------------------------------


def test_import_purity():
    """`import foley` + `import foley.agent` + `import foley.weave` are dol-only (no LLM/ML/DSP dep)."""
    code = (
        "import sys, foley, foley.agent, foley.weave;"
        "heavy={'anthropic','torch','transformers','lancedb','opentelemetry',"
        "'whisperx','opentimelineio','audioseal','c2pa','scipy','pyroomacoustics','numpy'};"
        "bad=heavy & set(sys.modules);"
        "assert not bad, bad"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_find_smoke_default_fakes(library):
    """`foley.find` works out of the box; every result is license-clean + verified."""
    cands = foley.find(DEMO, library=library)
    assert cands, "expected at least one candidate"
    assert {c.sound.id for c in cands} == {"door", "rain", "thunder"}
    for c in cands:
        assert c.license_ok is True
        assert c.verdict is not None and c.verdict.match is True


# ---------------------------------------------------------------------------
# the license gate (fail-closed, before verify)
# ---------------------------------------------------------------------------


def test_license_gate_before_verify():
    """An unverified-rights candidate never reaches the judge and is absent from output."""
    lib = _lib(
        [
            _rec("good_dog", "a dog barking loudly", ["dog"], verified=True),
            _rec("bad_dog", "a dog barking loudly", ["dog"], verified=False),
        ]
    )

    class SpyJudge:
        def __init__(self):
            self.seen = []
            self._inner = StringOverlapJudge()

        def judge(self, event, candidate, *, level=VerifyLevel.listen):
            self.seen.append(candidate.sound.id)
            return self._inner.judge(event, candidate, level=level)

    spy = SpyJudge()
    cands = foley.find("A dog barked.", library=lib, judge=spy, budget=Budget(allow_generate=False))
    out_ids = {c.sound.id for c in cands}
    assert "bad_dog" not in out_ids
    assert "good_dog" in out_ids
    assert "bad_dog" not in spy.seen  # gate-rejected → never verified


def test_gate_ordering_invariant(monkeypatch):
    """Every keep_sound call precedes any verify_match call (the report-07 ordering)."""
    order = []
    real_keep = foley.licensing.keep_sound

    def spy_keep(rec, use):
        order.append("keep")
        return real_keep(rec, use)

    def spy_verify(event, candidate, **kw):
        order.append("verify")
        return Verdict(match=True, confidence=1.0, level=VerifyLevel.listen)

    monkeypatch.setattr("foley.agent.policy.keep_sound", spy_keep)
    monkeypatch.setattr("foley.agent.tools.verify_match", spy_verify)
    lib = _lib([_rec("d1", "a dog barking", ["dog"]), _rec("d2", "a dog barking", ["dog"])])
    foley.find("A dog barked.", library=lib, budget=Budget(allow_generate=False))
    assert "keep" in order and "verify" in order
    assert order.index("verify") > max(i for i, x in enumerate(order) if x == "keep")


def test_gate_failclosed_on_error(monkeypatch):
    """If keep_sound raises, the candidate is dropped (fail-closed) and license_ok is not True."""

    def boom(rec, use):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr("foley.agent.policy.keep_sound", boom)
    c = _candidate("x", "a dog barking")
    kept = gate_candidates([c], IntendedUse())
    assert kept == []
    assert c.license_ok is False


def test_conservative_intended_use_default():
    """intended_use=None → a conservative IntendedUse; a voice-flagged sound is rejected."""
    lib = _lib([_rec("v", "a dog barking", ["dog"], voice=True)])
    cands = foley.find("A dog barked.", library=lib, budget=Budget(allow_generate=False))
    assert cands == []  # the only candidate is gate-rejected (recognizable voice)


# ---------------------------------------------------------------------------
# decide() — the single, pure branch
# ---------------------------------------------------------------------------


def _verified(sid, conf):
    c = _candidate(sid, sid)
    c.license_ok = True
    c.verdict = Verdict(match=True, confidence=conf, level=VerifyLevel.listen)
    return c


def test_decide_single_branch():
    """decide()'s truth table across USE / REFINE / GENERATE / DROP and non-diegetic bias."""
    ev = SoundEvent(query="a dog barking")
    non = SoundEvent(query="tension drone", diegetic=False)
    hi, lo = _verified("a", 0.9), _verified("b", 0.3)

    assert decide(ev, [hi], [hi], tau_retrieve=0.5, budget=Budget(), loop=0).action is DecideAction.USE
    assert decide(ev, [lo], [lo], tau_retrieve=0.5, budget=Budget(max_refine_loops=1), loop=0).action is DecideAction.REFINE
    assert decide(ev, [], [], tau_retrieve=0.5, budget=Budget(max_refine_loops=0), loop=0).action is DecideAction.GENERATE
    assert decide(ev, [], [], tau_retrieve=0.5, budget=Budget(max_refine_loops=0, allow_generate=False), loop=0).action is DecideAction.DROP
    # non-diegetic biases GENERATE even with a confident retrieval match
    assert decide(non, [hi], [hi], tau_retrieve=0.5, budget=Budget(), loop=0).action is DecideAction.GENERATE


def test_decide_is_pure(monkeypatch):
    """decide() never calls keep_sound/search/generate, and asserts its precondition."""
    for target in ("foley.agent.policy.keep_sound",):
        monkeypatch.setattr(target, lambda *a, **k: pytest.fail("decide called keep_sound"))
    ev = SoundEvent(query="x")
    hi = _verified("a", 0.9)
    decide(ev, [hi], [hi], tau_retrieve=0.5, budget=Budget(), loop=0)  # no side-effect calls
    ungated = _candidate("u", "u")  # license_ok None, no verdict
    with pytest.raises(AssertionError):
        decide(ev, [ungated], [], tau_retrieve=0.5, budget=Budget(), loop=0)


def test_refine_loop_bounded():
    """Refine is called at most Budget.max_refine_loops times, then falls through (no infinite loop)."""

    class NoJudge:
        def judge(self, event, candidate, *, level=VerifyLevel.listen):
            return Verdict(match=False, confidence=0.0, level=VerifyLevel(level))

    class SpyRefiner:
        def __init__(self):
            self.calls = 0

        def refine(self, query, *, n=3, hint=None):
            self.calls += 1
            return [query, f"{query} refined {self.calls}"]

    refiner = SpyRefiner()
    budget = Budget(max_refine_loops=2, allow_generate=False)
    lib = _lib([_rec("d", "a dog barking", ["dog"])])
    cands = foley.find(
        "A dog barked.", library=lib, judge=NoJudge(), refiner=refiner, budget=budget
    )
    assert cands == []  # nothing ever verifies → DROP
    assert refiner.calls == 2  # exactly max_refine_loops re-retrieval passes
    assert budget._refines == 2


# ---------------------------------------------------------------------------
# the generation fallback (re-gated + re-verified; refusals fail-closed)
# ---------------------------------------------------------------------------


def _no_retrieval_lib():
    return _lib([_rec("irrelevant", "completely unrelated sound", ["nope"])])


def test_generate_fallback_reverified_and_gated(monkeypatch):
    """A generated clip is RE-GATED and RE-VERIFIED before being yielded."""
    seen = {"keep": 0, "verify": 0}
    real_keep, real_verify = foley.licensing.keep_sound, foley.agent.tools.verify_match

    def spy_keep(rec, use):
        seen["keep"] += 1
        return real_keep(rec, use)

    def spy_verify(event, candidate, **kw):
        seen["verify"] += 1
        return real_verify(event, candidate, **kw)

    def fake_generate(prompt, *, library=None, **kw):
        return Candidate(
            sound=_rec("gen", prompt, [prompt], verified=True), origin=CandidateOrigin.generated
        )

    monkeypatch.setattr("foley.agent.policy.keep_sound", spy_keep)
    monkeypatch.setattr("foley.agent.tools.verify_match", spy_verify)
    monkeypatch.setattr(foley, "generate", fake_generate)

    cands = foley.find(
        "A dog barked.",
        library=_no_retrieval_lib(),
        budget=Budget(max_refine_loops=0, max_generations=1),
        judge=StringOverlapJudge(),
    )
    gen = [c for c in cands if c.origin is CandidateOrigin.generated]
    assert gen and gen[0].sound.id == "gen"
    assert gen[0].license_ok is True and gen[0].verdict is not None and gen[0].verdict.match
    assert seen["keep"] >= 1 and seen["verify"] >= 1  # re-gated + re-verified


def test_generate_refusal_failclosed(monkeypatch):
    """A generation refusal is caught fail-closed — find() skips the event and continues."""

    def refuse(prompt, *, library=None, **kw):
        raise foley.TrademarkRefusal("nope", hits=["some-audio-logo"], report=None)

    monkeypatch.setattr(foley, "generate", refuse)
    cands = foley.find(
        "A dog barked.",
        library=_no_retrieval_lib(),
        budget=Budget(max_refine_loops=0, max_generations=1),
    )
    assert cands == []  # refusal → dropped, no crash


def test_generate_skipped_dup_still_gated(monkeypatch):
    """A byte-twin (skipped_dup) generated Candidate is still gated + verified, not assumed vetted."""

    def dup(prompt, *, library=None, **kw):
        # a bare Candidate as generate() returns on skipped_dup (event/verdict/license unset)
        return Candidate(
            sound=_rec("dup", prompt, [prompt], verified=True), origin=CandidateOrigin.generated
        )

    monkeypatch.setattr(foley, "generate", dup)
    cands = foley.find(
        "A dog barked.",
        library=_no_retrieval_lib(),
        budget=Budget(max_refine_loops=0, max_generations=1),
        judge=StringOverlapJudge(),
    )
    assert cands and cands[0].sound.id == "dup"
    assert cands[0].license_ok is True and cands[0].verdict is not None


# ---------------------------------------------------------------------------
# the verify ladder
# ---------------------------------------------------------------------------


def test_verify_ladder_levels():
    """clap never calls the injected judge; higher rungs escalate; level == the producing rung."""
    ev = SoundEvent(query="a dog barking")
    c = _candidate("d", "a dog barking", clap=0.8)
    c.license_ok = True

    class SpyJudge:
        def __init__(self):
            self.calls = 0

        def judge(self, event, candidate, *, level=VerifyLevel.listen):
            self.calls += 1
            return Verdict(match=True, confidence=0.9, level=VerifyLevel(level))

    spy = SpyJudge()
    v_clap = verify_match(ev, c, level="clap", judge=spy, tau_clap=0.35)
    assert v_clap.level is VerifyLevel.clap and spy.calls == 0

    v_listen = verify_match(ev, c, level="listen", judge=spy, tau_clap=0.35)
    assert v_listen.level is VerifyLevel.listen and spy.calls == 1

    ungated = _candidate("u", "u")  # license_ok is None
    with pytest.raises(AssertionError):
        verify_match(ev, ungated, level="listen", judge=spy)


# ---------------------------------------------------------------------------
# obs — one manifest, the steps trail, redaction, null-run parity
# ---------------------------------------------------------------------------


def test_obs_one_manifest_and_steps(library, run_store):
    """One find() → exactly one RunManifest(op='find') with an ordered decompose→…→place steps trail."""
    foley.find(DEMO, library=library)
    assert len(run_store) == 1
    manifest = next(iter(run_store.values()))
    assert manifest["op"] == "find"
    # nested search aggregated into THIS manifest (no separate search manifest)
    assert "search" in {s["name"] for s in manifest["spans"]}
    steps = manifest["steps"]
    kinds = {s["kind"] for s in steps}
    assert {"decompose", "search", "license_gate", "verify", "decide", "place"} <= kinds
    seqs = [s["seq"] for s in steps]
    assert seqs == sorted(seqs)  # monotonic
    gate = next(s for s in steps if s["kind"] == "license_gate")
    assert {"n_in", "n_kept", "rejected_ids"} <= set(gate["detail"])
    verify = next(s for s in steps if s["kind"] == "verify")
    assert {"level", "match", "confidence"} <= set(verify["detail"])


def test_obs_redaction(library, run_store):
    """Narration is redacted (context_text key, not a raw leak) throughout the manifest."""
    import json

    foley.find(DEMO, library=library)
    manifest = next(iter(run_store.values()))
    blob = json.dumps(manifest)
    assert manifest["inputs"]["context_text"] != DEMO
    assert "heavy oak door creaked" not in blob
    # the search step's query detail is redacted to a hash dict (not raw text)
    search = next(s for s in manifest["steps"] if s["kind"] == "search")
    assert isinstance(search["detail"]["query"], dict)
    assert "heavy wooden door creaking open" not in blob
    # the place step's symbolic onset (a verbatim narration word) is redacted, not leaked
    place = next(s for s in manifest["steps"] if s["kind"] == "place")
    assert isinstance(place["detail"]["onset"], dict)
    assert "on 'door'" not in blob


def test_nullrun_parity():
    """With obs off, current_run() is the null run whose add_step/set_plan_ref are safe no-ops."""
    foley.obs.disable()
    run = foley.obs.current_run()
    assert type(run).__name__ == "_NullRun"
    run.add_step(object())  # no-op, must not raise
    run.set_plan_ref({"x": 1})  # no-op, must not raise
    tl = foley.plan([])  # outside any run scope → run_manifest_ref is None-safe
    assert tl.run_manifest_ref is None


# ---------------------------------------------------------------------------
# plan() — the sparse SELECT→WEAVE bridge
# ---------------------------------------------------------------------------


def test_plan_is_sparse(library):
    """plan() emits UNRESOLVED items — SELECT's flat fields set, every WEAVE field at default.

    Post-#8 the model is the grown superset, so "sparse" is a property of plan()'s
    *output* (it does not resolve anchors / fill processing — that is WEAVE's job),
    not of the dataclass shape. Round-trippable either way.
    """
    with foley.obs.run("session") as run:
        cands = foley.find(DEMO, library=library)
        tl = foley.plan(cands, transcript="the door opened")
        assert tl.run_manifest_ref == run.manifest.run_id
    rain = next(it for it in tl.items if it.clip_ref == "rain")
    assert rain.layer is Layer.ambience and rain.loop is True and isinstance(rain.onset, str)
    # SPARSE = every WEAVE-resolved field stays at its default (anchor resolution and
    # per-item processing are the render's job, not plan()'s).
    for it in tl.items:
        assert it.placement is None and it.processing is None
        assert it.id is None and it.event is None and it.enabled is True
    assert tl.word_timeline == [] and tl.narration_ref is None
    rt = SoundDesignTimeline.from_dict(tl.to_dict())
    assert isinstance(rt.items[0], TimelineItem) and rt.run_manifest_ref == tl.run_manifest_ref


def test_stream_equals_list(library):
    """list(find(stream=True)) == find(stream=False); stream=True yields a generator."""
    streamed = foley.find(DEMO, library=library, stream=True)
    assert isinstance(streamed, types.GeneratorType)
    from_stream = [c.sound.id for c in streamed]
    from_list = [c.sound.id for c in foley.find(DEMO, library=library, stream=False)]
    assert from_stream == from_list and from_stream


# ---------------------------------------------------------------------------
# eval non-regression + the LLM seam + hermetic-CI guard
# ---------------------------------------------------------------------------


def test_eval_nonregression_parity(library):
    """search_sounds([q]) == library.search(q): the agent layer never touches retrieval ranking."""
    q = "distant thunder rumble"
    via_agent = [c.sound.id for c in search_sounds(q, k=10, library=library)]
    direct = [c.sound.id for c in library.search(q, k=10)]
    assert via_agent == direct


def test_rrf_merge_multi_query(library):
    """A multi-query search RRF-fuses the per-query lists (matches the reference RRF) and sets rrf_score."""
    from foley.index import RRF_K

    q1, q2 = "distant thunder rumble", "heavy wooden door"
    lists = [[c.sound.id for c in library.search(q, k=10)] for q in (q1, q2)]
    scores = {}
    for lst in lists:
        for rank, sid in enumerate(lst):
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (RRF_K + rank + 1)
    expected = sorted(scores, key=lambda s: scores[s], reverse=True)

    merged = search_sounds([q1, q2], k=10, library=library)
    assert [c.sound.id for c in merged] == expected  # equals the hand-computed fusion
    assert all(c.rrf_score is not None for c in merged)
    assert len({c.sound.id for c in merged}) == len(merged)  # deduped


def test_generate_under_clap_verify(monkeypatch):
    """A generated clip is re-verified at the listen rung even under verify='clap' (not silently dropped)."""

    def fake_gen(prompt, *, library=None, **kw):
        return Candidate(
            sound=_rec("gen", prompt, [prompt], verified=True), origin=CandidateOrigin.generated
        )

    monkeypatch.setattr(foley, "generate", fake_gen)

    class OneEvent:  # a non-diegetic cue → decide() routes to GENERATE unconditionally
        def decompose(self, context, *, max_events=6, seconds=None):
            return [SoundEvent(query="tension drone", diegetic=False)]

    cands = foley.find(
        "suspense builds",
        library=_no_retrieval_lib(),
        verify="clap",
        decomposer=OneEvent(),
        budget=Budget(max_refine_loops=0, max_generations=1),
    )
    assert cands and cands[0].sound.id == "gen"
    assert cands[0].verdict is not None and cands[0].verdict.level is VerifyLevel.listen


class _FakeAnthropic:
    """A stand-in anthropic client: records create() kwargs, returns a canned json_schema Message."""

    def __init__(self, payload):
        self._payload = payload
        self.create_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        block = types.SimpleNamespace(type="text", text=self._payload)
        usage = types.SimpleNamespace(input_tokens=123, output_tokens=45)
        return types.SimpleNamespace(
            content=[block], model="claude-opus-4-8", usage=usage, stop_reason="end_turn"
        )


def test_anthropic_decomposer_offline(monkeypatch):
    """AnthropicDecomposer round-trips a canned payload and records the GenAI span — no network."""
    monkeypatch.setenv("FOLEY_APPROVE_UNKNOWN_COST", "1")  # a real rung: cost unknown (#57)
    import json

    from foley.obs.trace import GENAI

    payload = json.dumps(
        {"events": [{"query": "a dog barking", "layer": "sfx_fg", "diegetic": True, "salience": "high"}]}
    )
    dec = AnthropicDecomposer(client=_FakeAnthropic(payload))
    events = dec.decompose("A dog barked", max_events=6)
    assert len(events) == 1
    assert events[0].query == "a dog barking" and events[0].layer is Layer.sfx_fg
    assert events[0].salience is Salience.high
    # correct model + adaptive thinking (never budget_tokens), structured output
    kw = dec._client.create_kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert "budget_tokens" not in kw and kw["thinking"] == {"type": "adaptive"}
    assert "output_config" in kw

    # GenAI attributes land on the span (usage/model/finish_reason)
    from foley.agent.decompose import decompose_context

    with foley.obs.run("t") as run:
        with run.span("llm") as sp:
            decompose_context("A dog barked", decomposer=AnthropicDecomposer(client=_FakeAnthropic(payload)), _span=sp)
    span = next(s for s in run.manifest.spans if s.name == "llm")
    assert span.attributes.get(GENAI["input_tokens"]) == 123
    assert span.attributes.get(GENAI["response_model"]) == "claude-opus-4-8"
    assert span.attributes.get(GENAI["finish_reasons"]) == ["end_turn"]  # semconv: string[]


def test_anthropic_judge_offline(monkeypatch):
    """AnthropicJudge round-trips a canned verdict and uses the right model — no network."""
    monkeypatch.setenv("FOLEY_APPROVE_UNKNOWN_COST", "1")  # a real rung: cost unknown (#57)
    import json

    from foley.agent.verify import AnthropicJudge

    payload = json.dumps({"match": True, "confidence": 0.88, "reason": "a real door creak"})
    j = AnthropicJudge(client=_FakeAnthropic(payload))
    c = _candidate("d", "a dog barking")
    c.license_ok = True
    v = j.judge(SoundEvent(query="a dog barking"), c, level=VerifyLevel.judge)
    assert v.match is True and v.confidence == 0.88 and v.level is VerifyLevel.judge
    kw = j._client.create_kwargs
    assert kw["model"] == "claude-opus-4-8" and "budget_tokens" not in kw
    assert kw["thinking"] == {"type": "adaptive"} and "output_config" in kw


def test_anthropic_refiner_offline(monkeypatch):
    """AnthropicRefiner round-trips a canned paraphrase list, query-first + deduped."""
    monkeypatch.setenv("FOLEY_APPROVE_UNKNOWN_COST", "1")  # a real rung: cost unknown (#57)
    import json

    from foley.agent.refine import AnthropicRefiner

    payload = json.dumps({"paraphrases": ["a dog barking", "dog woofing", "canine bark"]})
    r = AnthropicRefiner(client=_FakeAnthropic(payload))
    out = r.refine("a dog barking", n=3)
    assert out[0] == "a dog barking" and len(out) == len(set(out)) <= 3
    kw = r._client.create_kwargs
    assert kw["model"] == "claude-opus-4-8" and "budget_tokens" not in kw


def test_ci_stays_hermetic():
    """The `agent` extra is deliberately NOT in the CI install set (guards hermetic CI)."""
    import pathlib

    tomllib = pytest.importorskip("tomllib")  # stdlib on 3.11+; the CI 3.12 leg runs this guard

    root = pathlib.Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text())
    extras = data["tool"]["wads"]["ci"]["install"]["extras"]
    assert extras == ["test"] and "agent" not in extras
    assert "anthropic" in data["project"]["optional-dependencies"]["agent"]
