"""A source billed per compute second is priced from the run time fal reports (#186).

ThinkSound bills $0.001 per compute second: unknown before the call (so it needs
approval), and since falaw#125 known after it, from fal's ``Completed.metrics``
(``inference_time``), which falaw carries on its ``done`` event. Without it the actual
stays unknown, never guessed.
"""

import sys
import types

import pytest

from foley.sources.fal.adapter import FalAdapter, falaw_runner
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
    answer = (b"audio", {"video": {"url": "https://fal.media/v.mp4"}}, {"inference_time": 42.5})
    clip = _thinksound(answer).generate("", video="https://x/shot.mp4")
    assert clip.candidate.cost_actual_usd == pytest.approx(0.0425)
    assert any("observed run time" in n for n in clip.notes)


@pytest.mark.parametrize(
    "metrics", [None, {}, {"inference_time": "42"}, {"inference_time": -1.0},
                {"inference_time": float("nan")}, {"inference_time": True}],
)
def test_no_usable_run_time_leaves_the_cost_unknown(metrics):
    answer = (b"audio", {"video": {"url": "https://fal.media/v.mp4"}}, metrics)
    clip = _thinksound(answer).generate("", video="https://x/shot.mp4")
    assert clip.candidate.cost_actual_usd is None


def test_a_fal_answer_carries_its_metrics_to_the_cost():
    from foley.sources.fal.adapter import FalAnswer

    answer = FalAnswer(b"audio", {"video": {"url": "https://fal.media/v.mp4"}}, {"inference_time": 10})
    assert _thinksound(answer).generate("", video="https://x/s.mp4").candidate.cost_actual_usd == pytest.approx(0.01)


def test_a_runner_answering_two_values_still_works():
    clip = _thinksound((b"audio", {"video": {"url": "https://fal.media/v.mp4"}})).generate(
        "", video="https://x/shot.mp4")
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
