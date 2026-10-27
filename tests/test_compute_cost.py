"""A source billed per compute second is priced from the run time fal reports (#186).

ThinkSound bills $0.001 per compute second: unknown before the call (so it needs
approval), and since falaw#125 known after it, from fal's ``Completed.metrics``
(``inference_time``), which falaw carries on its ``done`` event. Without it the actual
stays unknown, never guessed.
"""

import copy
import pickle
import sys
import types

import pytest

from foley import RemoteVideo
from foley.sources.fal.adapter import FalAdapter, FalAnswer, falaw_runner
from foley.sources.fal.config import SOURCE_CONFIGS

CONFIGS = {c["name"]: c for c in SOURCE_CONFIGS}


def _thinksound(answer):
    return FalAdapter(
        CONFIGS["fal_thinksound"],
        api_key="k",
        runner=lambda endpoint_id, arguments, *, api_key, audio_field="audio": answer,
        uploader=lambda path, *, api_key: "https://fal.media/up/1.mp4",
        demux=lambda media: media,  # the fake answers audio
    )


def test_thinksound_is_priced_from_the_reported_run_time():
    answer = FalAnswer(
        b"audio",
        {"video": {"url": "https://fal.media/v.mp4"}},
        {"inference_time": 42.5},
    )
    clip = _thinksound(answer).generate("", video="https://x/shot.mp4")
    assert clip.candidate.cost_actual_usd == pytest.approx(0.0425)
    assert any("observed run time" in n for n in clip.notes)


@pytest.mark.parametrize(
    "metrics",
    [
        None,
        {},
        {"inference_time": "42"},
        {"inference_time": -1.0},
        {"inference_time": float("nan")},
        {"inference_time": True},
    ],
)
def test_no_usable_run_time_leaves_the_cost_unknown(metrics):
    answer = FalAnswer(b"audio", {"video": {"url": "https://fal.media/v.mp4"}}, metrics)
    clip = _thinksound(answer).generate("", video="https://x/shot.mp4")
    assert clip.candidate.cost_actual_usd is None


def test_a_fal_answer_carries_its_metrics_to_the_cost():
    answer = FalAnswer(
        b"audio", {"video": {"url": "https://fal.media/v.mp4"}}, {"inference_time": 10}
    )
    assert _thinksound(answer).generate(
        "", video="https://x/s.mp4"
    ).candidate.cost_actual_usd == pytest.approx(0.01)


def test_a_runner_answering_two_values_still_works():
    clip = _thinksound(
        (b"audio", {"video": {"url": "https://fal.media/v.mp4"}})
    ).generate("", video="https://x/shot.mp4")
    assert clip.candidate.cost_actual_usd is None


def test_falaw_runner_keeps_the_done_events_metrics(tmp_path, monkeypatch):
    clip = tmp_path / "a.wav"
    clip.write_bytes(b"RIFF")

    def cached_call_fal(endpoint_id, arguments, *, refresh, on_event):
        on_event(types.SimpleNamespace(kind="progress", metrics={"inference_time": 1}))
        on_event(types.SimpleNamespace(kind="done", metrics={"inference_time": 7.25}))
        return {"audio": {"url": "https://fal.media/a.wav"}}

    import contextlib

    fake = types.SimpleNamespace(
        cached_call_fal=cached_call_fal,
        materialize_asset=lambda url, key_hint: str(clip),
        using_fal_credentials=lambda key: contextlib.nullcontext(),
        errors=types.SimpleNamespace(
            FalClientNotInstalled=type("A", (Exception,), {}),
            FalUnauthorized=type("B", (Exception,), {}),
            FalInsufficientFunds=type("C", (Exception,), {}),
            FalAccountLocked=type("D", (Exception,), {}),
            FalNonCanonicalArgument=type("E", (Exception,), {}),
        ),
    )
    monkeypatch.setitem(sys.modules, "falaw", fake)
    monkeypatch.setitem(sys.modules, "falaw.errors", fake.errors)
    answer = falaw_runner("fal-ai/x", {}, api_key="k")
    media, response = answer  # still the two-tuple every runner answers
    assert media == b"RIFF" and answer.metrics == {"inference_time": 7.25}


@pytest.mark.parametrize(
    "roundtrip",
    [copy.copy, copy.deepcopy, lambda a: pickle.loads(pickle.dumps(a))],
    ids=["copy", "deepcopy", "pickle"],
)
def test_a_fal_answer_survives_copy_and_pickle(roundtrip):
    answer = FalAnswer(b"audio", {"a": 1}, {"inference_time": 3.0})
    again = roundtrip(answer)
    assert tuple(again) == (b"audio", {"a": 1})
    assert again.metrics == {"inference_time": 3.0}


class _Cache:
    def __init__(self):
        self.audio, self.requests = {}, {}


def test_the_actual_cost_settles_the_budget_and_a_replay_charges_nothing():
    from foley.agent.policy import Budget
    from foley.cost import spend_scope
    from foley.sources._dispatch import plan_generation, run_generation

    answer = FalAnswer(
        b"audio",
        {"video": {"url": "https://fal.media/v.mp4"}},
        {"inference_time": 42.5},
    )
    adapter = _thinksound(answer)
    cache = _Cache()
    video = RemoteVideo(url="https://x/shot.mp4", sha256="0" * 64)
    with spend_scope(Budget(approve_unknown_cost=True)) as budget:
        plan = plan_generation(
            "fal_thinksound", "", adapter=adapter, cache=cache, video=video
        )
        assert plan.estimate_usd is None and budget._unknown_calls == 1
        clip = run_generation(plan, adapter, cache=cache)
        assert clip.candidate.cost_actual_usd == pytest.approx(0.0425)
        assert budget.spent_usd == pytest.approx(0.0425)
        assert budget._unknown_calls == 0
        (entry,) = cache.requests.values()
        assert entry["actual_usd"] == pytest.approx(0.0425)

        replay = plan_generation(
            "fal_thinksound", "", adapter=adapter, cache=cache, video=video
        )
        assert replay.cached is not None
        again = run_generation(replay, adapter, cache=cache)
        assert again.candidate.cost_actual_usd == 0.0
        assert budget.spent_usd == pytest.approx(0.0425) and budget._unknown_calls == 0
        cost_notes = [n for n in again.notes if "run time" in n]
        assert cost_notes and all(
            n.startswith("when first generated: ") for n in cost_notes
        )


def test_without_a_run_time_the_call_stays_an_unknown_one():
    from foley.agent.policy import Budget
    from foley.cost import spend_scope
    from foley.sources._dispatch import plan_generation, run_generation

    adapter = _thinksound(
        FalAnswer(b"audio", {"video": {"url": "https://fal.media/v.mp4"}})
    )
    video = RemoteVideo(url="https://x/shot.mp4", sha256="0" * 64)
    with spend_scope(Budget(approve_unknown_cost=True)) as budget:
        plan = plan_generation(
            "fal_thinksound", "", adapter=adapter, cache=_Cache(), video=video
        )
        run_generation(plan, adapter, cache=_Cache())
        assert budget.spent_usd == 0.0 and budget._unknown_calls == 1


def test_a_billed_answer_whose_demux_failed_still_settles_its_cost():
    from foley.agent.policy import Budget
    from foley.cost import spend_scope
    from foley.sources._dispatch import plan_generation, run_generation
    from foley.sources.base import UndemuxedAnswer

    def demux(media):
        raise ValueError("no audio track")

    adapter = FalAdapter(
        CONFIGS["fal_thinksound"],
        api_key="k",
        runner=lambda endpoint_id, arguments, *, api_key, audio_field="audio": (
            FalAnswer(
                b"video",
                {"video": {"url": "https://fal.media/v.mp4"}},
                {"inference_time": 10},
            )
        ),
        uploader=lambda path, *, api_key: "https://fal.media/up/1.mp4",
        demux=demux,
    )
    video = RemoteVideo(url="https://x/shot.mp4", sha256="0" * 64)
    with spend_scope(Budget(approve_unknown_cost=True)) as budget:
        plan = plan_generation(
            "fal_thinksound", "", adapter=adapter, cache=_Cache(), video=video
        )
        with pytest.raises(UndemuxedAnswer):
            run_generation(plan, adapter, cache=_Cache())
        assert budget.spent_usd == pytest.approx(0.01) and budget._unknown_calls == 0


def test_a_video_billed_source_is_never_settled_below_its_exact_quote():
    """HunyuanVideo-Foley bills 10 s blocks of the video: the audio it returns is not the bill."""
    from foley.sources._dispatch import GenerationPlan, _billed

    hunyuan = CONFIGS["fal_hunyuan_foley"]
    assert hunyuan["pricing"].get("seconds_from") == "video"
    plan = GenerationPlan(backend="fal_hunyuan_foley", prompt="", config=hunyuan,
                          affordances={}, estimate_usd=0.2)
    assert _billed(plan, 0.1) == 0.2 and _billed(plan, 0.3) == 0.3
    assert _billed(plan, None) is None
    per_call = GenerationPlan(backend="x", prompt="", config={"pricing": {"unit": "per_second"}},
                              affordances={}, estimate_usd=0.2)
    assert _billed(per_call, 0.1) == 0.1  # elsewhere the actual replaces the estimate
