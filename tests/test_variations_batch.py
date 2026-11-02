"""``foley.variations`` through a backend's native batch knob: n takes in one call (#210).

Hermetic: fal goes through a replay runner that answers a batch (``all_audio=True``)
with canned samples, and Stable Audio Open through a fake pipeline; nothing reaches
the network or loads a model.
"""

import io

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.cost import BudgetExceeded, actual_call_cost, estimate_call  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.sources.base import batch_limit, derived_seed, seed_limit  # noqa: E402
from foley.sources.fal import SOURCE_CONFIGS  # noqa: E402
from foley.sources.fal.adapter import FalAdapter  # noqa: E402
from foley.sources.stable_audio import SOURCE_CONFIG as SA_CONFIG  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402

from ._fakes import fake_generator  # noqa: E402

SR = 16_000
CONFIGS = {c["name"]: c for c in SOURCE_CONFIGS}
MIRELO_PER_S = CONFIGS["fal_mirelo"]["pricing"]["amount_usd"]


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _wav(freq, *, silent=False):
    t = np.linspace(0.0, 0.6, int(SR * 0.6), endpoint=False, dtype=np.float32)
    tone = np.zeros_like(t) if silent else 0.5 * np.sin(2 * np.pi * freq * t)
    buf = io.BytesIO()
    sf.write(buf, tone.astype(np.float32), SR, format="WAV")
    return buf.getvalue()


class BatchRunner:
    """A fake fal transport answering ``num_samples`` distinct takes.

    It reports per-sample seeds of its own making (``seeds=False``: none), never
    derived from the seed sent, so a test checks that foley records what the backend
    reports and sends what foley decided (``calls``), not what the fake assumes.
    ``reported`` holds each call's reported seeds. ``answered`` caps the samples it
    returns; ``silent`` lists the take indexes it answers with silence.
    """

    def __init__(self, *, seeds=True, answered=None, silent=()):
        self.calls, self.seeds, self.answered, self.silent = [], seeds, answered, silent
        self.reported = []

    def __call__(self, endpoint_id, arguments, *, api_key, audio_field="audio", all_audio=False):
        self.calls.append(dict(arguments, all_audio=all_audio))
        n = arguments.get("num_samples", 1)
        k = min(n, self.answered or n)
        audios = [
            _wav(200 + 50 * len(self.calls) + 13 * i, silent=i in self.silent)
            for i in range(k)
        ]
        response = {"audio": [{"url": f"u{i}"} for i in range(k)], "model": "sfx2.0"}
        if self.seeds:
            response["seeds"] = [90_000 + 1_000 * len(self.calls) + 7 * i for i in range(k)]
            self.reported.append(response["seeds"])
        return (audios if all_audio else audios[0]), response


def _mirelo(runner, name="fal_mirelo"):
    return FalAdapter(CONFIGS[name], api_key="fal-test-key", runner=runner)


def _variations(adapter, n, library, **kw):
    return foley.variations(
        "a sabre swing", n, backend=adapter.name, adapter=adapter, library=library,
        duration_s=1, **kw,
    )


# ---------------------------------------------------------------------------
# config + pricing
# ---------------------------------------------------------------------------


def test_the_batch_backends_declare_their_knob_and_seed_range():
    assert batch_limit(CONFIGS["fal_mirelo"]) == 4
    assert batch_limit(CONFIGS["fal_mirelo_v2a"]) == 4
    assert batch_limit(SA_CONFIG) == 4
    # Stable Audio 3 (fal or local) and Sonilo have no batch knob: one call per take.
    for name in ("fal_stable_audio_3", "fal_sonilo", "fal_elevenlabs"):
        assert batch_limit(CONFIGS[name]) == 1
    assert seed_limit(CONFIGS["fal_mirelo"]) == 2**63
    assert seed_limit(CONFIGS["fal_stable_audio_3"]) == 2**31  # the default


def test_a_per_sample_price_scales_with_the_samples_and_a_per_call_one_does_not():
    mirelo, sa3 = CONFIGS["fal_mirelo"], CONFIGS["fal_stable_audio_3"]
    one = estimate_call(mirelo, duration_s=2)
    assert estimate_call(mirelo, samples=3, duration_s=2) == pytest.approx(3 * one)
    assert actual_call_cost(mirelo, duration_s=2, samples=3) == pytest.approx(3 * one)
    assert estimate_call(sa3, samples=3) == estimate_call(sa3)
    assert CONFIGS["fal_sonilo"]["pricing"]["per_sample"] is True


# ---------------------------------------------------------------------------
# Mirelo through fal: num_samples
# ---------------------------------------------------------------------------


def test_n_takes_come_from_one_call_each_with_its_own_seed_and_share(library):
    runner = BatchRunner()
    takes = _variations(_mirelo(runner), 3, library)
    assert len(runner.calls) == 1
    (call,) = runner.calls
    assert call["num_samples"] == 3 and call["all_audio"] is True
    assert len({c.sound.id for c in takes}) == 3
    # each take records the seed the backend reports for it, and its sample index
    assert [c.sound.license.generation_seed for c in takes] == runner.reported[0]
    params = [c.sound.license.generation_params for c in takes]
    assert [p["sample_index"] for p in params] == [0, 1, 2]
    assert {p["num_samples"] for p in params} == {3}
    # each take is billed one sample, and its estimate is what it was charged
    assert [c.cost_actual_usd for c in takes] == [pytest.approx(MIRELO_PER_S)] * 3
    assert [c.cost_estimate_usd for c in takes] == [c.cost_actual_usd for c in takes]


def test_a_budget_for_no_take_refuses_before_any_call(library):
    runner = BatchRunner()
    with pytest.raises(BudgetExceeded) as info:
        _variations(
            _mirelo(runner), 3, library, budget=foley.Budget(max_usd=0.5 * MIRELO_PER_S)
        )
    assert runner.calls == [] and info.value.variations == []


def test_a_budget_for_part_of_a_batch_gets_those_takes(library):
    """The batch is cut to what the budget affords, reserved before the call: the
    budget then refuses the take it cannot afford, as one call per take did."""
    runner = BatchRunner()
    budget = foley.Budget(max_usd=2.5 * MIRELO_PER_S)
    with pytest.raises(BudgetExceeded) as info:
        _variations(_mirelo(runner), 3, library, budget=budget)
    assert [c["num_samples"] for c in runner.calls] == [2]
    assert len(info.value.variations) == 2
    assert budget.spent_usd == pytest.approx(2 * MIRELO_PER_S)


def test_the_batch_settles_at_its_actual_cost(library):
    budget = foley.Budget(max_usd=1.0)
    _variations(_mirelo(BatchRunner()), 3, library, budget=budget)
    assert budget.spent_usd == pytest.approx(3 * MIRELO_PER_S)


def test_each_take_has_its_own_cache_entry_and_a_rerun_replays_them_all(
    library, _in_memory_generations_cache
):
    runner = BatchRunner()
    takes = _variations(_mirelo(runner), 3, library)
    entries = _in_memory_generations_cache.requests.values()
    assert sorted(e.get("variation", 0) for e in entries) == [0, 1, 2]
    again = _variations(_mirelo(runner), 3, library)
    assert len(runner.calls) == 1  # nothing paid twice
    assert [c.sound.id for c in again] == [c.sound.id for c in takes]
    assert all(c.cost_actual_usd == 0.0 for c in again)


def test_take_zero_is_the_plain_request(library):
    runner = BatchRunner()
    takes = _variations(_mirelo(runner), 2, library)
    one = foley.generate(
        "a sabre swing", backend="fal_mirelo", adapter=_mirelo(runner),
        library=library, duration_s=1,
    )
    assert one.sound.id == takes[0].sound.id and len(runner.calls) == 1


def test_only_the_takes_the_cache_lacks_are_made(library):
    runner = BatchRunner()
    foley.generate(
        "a sabre swing", backend="fal_mirelo", adapter=_mirelo(runner),
        library=library, duration_s=1,
    )
    _variations(_mirelo(runner), 3, library)
    assert [c["num_samples"] for c in runner.calls] == [1, 2]


def test_more_takes_than_the_knob_allows_take_several_calls(library):
    runner = BatchRunner()
    takes = _variations(_mirelo(runner), 6, library)
    assert len(takes) == 6 and len({c.sound.id for c in takes}) == 6
    assert [c["num_samples"] for c in runner.calls] == [4, 2]


def test_a_seeded_batch_sends_each_calls_first_take_seed(library):
    runner = BatchRunner()
    _variations(_mirelo(runner), 6, library, seed=2**31 - 1)
    # the second call starts at take 4's seed, in Mirelo's 64-bit range (no wrap at 2**31)
    assert [c["seed"] for c in runner.calls] == [2**31 - 1, 2**31 + 3]
    assert derived_seed(2**31 - 1, 4, limit=2**63) == 2**31 + 3


def test_a_seeded_take_is_the_request_for_its_seed(library):
    """Take i of seed s is generate(seed=s + i): one key, batch or not (#210)."""
    runner = BatchRunner()
    takes = _variations(_mirelo(runner), 2, library, seed=5)
    one = foley.generate(
        "a sabre swing", backend="fal_mirelo", adapter=_mirelo(runner),
        library=library, duration_s=1, seed=6,
    )
    assert len(runner.calls) == 1 and one.sound.id == takes[1].sound.id


def test_a_reported_seed_other_than_the_keyed_one_is_noted(library):
    takes = _variations(_mirelo(BatchRunner()), 2, library, seed=5)
    assert any("reports seed" in n for n in takes[1].notes)


def test_a_standalone_seeded_variation_sends_the_derived_seed(library):
    runner = BatchRunner()
    one = foley.generate(
        "a sabre swing", backend="fal_mirelo", adapter=_mirelo(runner),
        library=library, duration_s=1, seed=5, variation=1,
    )
    assert runner.calls[-1]["seed"] == 6
    takes = _variations(_mirelo(runner), 2, library, seed=5)
    assert [c["seed"] for c in runner.calls] == [6, 5]  # take 0 made, take 1 replayed
    assert takes[1].sound.id == one.sound.id


def test_a_hole_in_the_cache_splits_the_batch_into_runs(library):
    runner = BatchRunner()
    foley.generate(
        "a sabre swing", backend="fal_mirelo", adapter=_mirelo(runner),
        library=library, duration_s=1, seed=5, variation=2,
    )
    takes = _variations(_mirelo(runner), 4, library, seed=5)
    calls = [(c["seed"], c["num_samples"]) for c in runner.calls]
    assert calls == [(7, 1), (5, 2), (8, 1)]  # take 2 was cached: runs [0, 1] and [3]
    assert len({c.sound.id for c in takes}) == 4


def test_a_backend_answering_with_a_video_is_never_batched():
    from foley.sources.generate import _batch_takes

    cfg = {**CONFIGS["fal_mmaudio_v2a"]}
    cfg["native_defaults"] = {**cfg["native_defaults"], "batch": {"native_name": "n", "max": 4}}
    assert _batch_takes("x", FalAdapter(cfg, api_key="k"), 3) == 1
    assert _batch_takes("x", _mirelo(BatchRunner()), 3) == 3


def test_a_compute_second_price_is_the_whole_calls_run_time():
    gpu = {"pricing": {"unit": "per_compute_second", "amount_usd": 0.001, "per_sample": True}}
    assert actual_call_cost(gpu, compute_s=10.0, samples=3) == pytest.approx(0.01)


def test_a_take_qc_refuses_fails_like_a_single_take_and_keeps_the_others(library):
    runner = BatchRunner(silent=(1,))
    with pytest.raises(foley.GenerationError) as info:
        _variations(_mirelo(runner), 3, library)
    assert info.value.status == "quarantined"
    made = info.value.variations
    assert len(made) == 2 and all(c.sound.id in library for c in made)


def test_fewer_samples_than_asked_is_an_error_for_the_missing_takes(library):
    runner = BatchRunner(answered=2)
    with pytest.raises(foley.GenerationError) as info:
        _variations(_mirelo(runner), 3, library)
    assert info.value.status == "error" and "fewer takes" in str(info.value)
    assert len(info.value.variations) == 2


def test_a_backend_reporting_no_per_sample_seed_says_so(library):
    takes = _mirelo(BatchRunner(seeds=False)).generate_takes(
        "a sabre swing", 2, duration_s=1.0
    )
    assert [t.candidate.sound.license.generation_seed for t in takes] == [None, None]
    assert all(any("no per-sample seed" in n for n in t.notes) for t in takes)


def test_the_batch_knob_is_not_a_provider_param():
    with pytest.raises(ValueError):
        _mirelo(BatchRunner()).generate("x", provider_params={"num_samples": 3})


# ---------------------------------------------------------------------------
# Stable Audio Open (diffusers): num_waveforms_per_prompt
# ---------------------------------------------------------------------------


class BatchPipeline:
    """A fake ``StableAudioPipeline`` rendering ``num_waveforms_per_prompt`` waveforms."""

    def __init__(self):
        self.vae = type("Vae", (), {"sampling_rate": SR})()
        self.device, self.dtype, self.calls = "cpu", "float32", []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        n = kwargs.get("num_waveforms_per_prompt", 1)
        t = np.linspace(0.0, 0.6, int(SR * 0.6), endpoint=False, dtype=np.float32)
        audios = [np.stack([0.4 * np.sin(2 * np.pi * (300 + 40 * i) * t)] * 2) for i in range(n)]
        return type("Out", (), {"audios": audios})()


def test_stable_audio_renders_the_takes_in_one_call_one_generator_each(library):
    pipe = BatchPipeline()
    adapter = StableAudioAdapter(SA_CONFIG, pipeline=pipe, make_generator=fake_generator)
    takes = foley.variations(
        "a door creak", 3, backend="stable_audio", adapter=adapter, library=library,
        seed=7, duration_s=1,
    )
    (call,) = pipe.calls
    assert call["num_waveforms_per_prompt"] == 3
    assert [g.seed for g in call["generator"]] == [7, 8, 9]
    assert [c.sound.license.generation_seed for c in takes] == [7, 8, 9]
    assert [c.sound.license.generation_params["sample_index"] for c in takes] == [0, 1, 2]
    assert len({c.sound.id for c in takes}) == 3


def test_stable_audio_one_take_keeps_one_generator():
    pipe = BatchPipeline()
    adapter = StableAudioAdapter(SA_CONFIG, pipeline=pipe, make_generator=fake_generator)
    adapter.generate("a door creak", seed=7)
    assert pipe.calls[0]["generator"].seed == 7
    assert pipe.calls[0]["num_waveforms_per_prompt"] == 1
