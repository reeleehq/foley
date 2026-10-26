"""Tests for the Tier-2 audio-LM fit-judge — ``foley.agent.AudioLMJudge`` (#10b).

The whole byte-decode → AQAScore-prompt → P(yes) → :class:`Verdict` path is exercised
with an INJECTED fake pipeline (no torch/transformers), and the ``_default_fit_judge``
resolver is checked to keep AudioLMJudge injection-only in this slice (its real
Qwen2-Audio pipeline is a deferred follow-up). The real round-trip is importorskip-guarded.
"""

import pytest

np = pytest.importorskip("numpy")

from foley.agent import AnthropicJudge, AudioLMJudge, StringOverlapJudge  # noqa: E402
from foley.agent import verify as V  # noqa: E402
from foley.base import (  # noqa: E402
    Candidate,
    LicenseRecord,
    SoundEvent,
    SoundRecord,
    VerifyLevel,
)


def _candidate_with_audio(tmp_path, caption="a dog barking"):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "clip.wav"
    sf.write(str(path), np.zeros(2048, dtype=np.float32), 16000)
    rec = SoundRecord(
        id="c",
        uri=str(path),
        caption=caption,
        license=LicenseRecord(source="test", license_id="CC0-1.0", rights_verified=True),
    )
    c = Candidate(sound=rec)
    c.license_ok = True
    return c


def test_audiolm_judge_fake_pipeline(tmp_path):
    """The AQAScore path: prompt built from the event, P(yes) → Verdict, no torch."""
    c = _candidate_with_audio(tmp_path)
    captured = {}

    def fake_pipeline(prompt, wav, sr):
        captured["prompt"] = prompt
        captured["sr"] = sr
        return {"p_yes": 0.87}

    judge = AudioLMJudge(pipeline=fake_pipeline, tau=0.5)
    v = judge.judge(SoundEvent(query="a dog barking"), c, level=VerifyLevel.listen)
    assert v.match is True and v.confidence == pytest.approx(0.87) and v.level is VerifyLevel.listen
    assert "a dog barking" in captured["prompt"]
    assert judge.last_response == {"p_yes": 0.87}  # stashed for the GenAI span


def test_audiolm_judge_below_tau_rejects(tmp_path):
    """P(yes) below tau → no match."""
    c = _candidate_with_audio(tmp_path)
    judge = AudioLMJudge(pipeline=lambda p, w, s: {"p_yes": 0.2}, tau=0.5)
    assert judge.judge(SoundEvent(query="x"), c, level=VerifyLevel.listen).match is False


def test_audiolm_judge_parses_text_output(tmp_path):
    """A raw yes/no text pipeline output is parsed to a hard 0/1 fallback."""
    c = _candidate_with_audio(tmp_path)
    yes = AudioLMJudge(pipeline=lambda p, w, s: "Yes, clearly.", tau=0.5)
    no = AudioLMJudge(pipeline=lambda p, w, s: "No.", tau=0.5)
    assert yes.judge(SoundEvent(query="q"), c).match is True
    assert no.judge(SoundEvent(query="q"), c).match is False


def test_default_fit_judge_resolution(monkeypatch):
    """The resolver never auto-selects AudioLMJudge (injection-only); the LLM only on opt-in (#58)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")  # a key alone opts in to nothing
    for level in ("clap", "listen", "judge"):
        j = V._default_fit_judge(level)
        assert isinstance(j, StringOverlapJudge) and not isinstance(j, AudioLMJudge)
    pytest.importorskip("anthropic")
    assert isinstance(V._default_fit_judge("judge", llm="anthropic"), AnthropicJudge)


def test_audiolm_available_is_bool():
    """The capability probe returns a plain bool (transformers + torch present)."""
    assert isinstance(V._audiolm_available(), bool)


def test_audiolm_judge_real_roundtrip():
    """The real Qwen2-Audio path is deferred behind foley[fit] — importorskip-guarded."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    judge = AudioLMJudge()
    with pytest.raises(NotImplementedError):
        judge._build_pipeline()  # the real wrapper is a documented #10b follow-up
