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


def test_audiolm_judge_without_fit_extra_says_how_to_get_it(monkeypatch):
    """No pipeline and no foley[fit]: an ImportError naming the extra, not a crash in torch."""
    monkeypatch.setattr(V, "_audiolm_available", lambda: False)
    with pytest.raises(ImportError, match=r"foley\[fit\]"):
        AudioLMJudge()._build_pipeline()


def test_audiolm_judge_real_pipeline_with_faked_model_load(tmp_path, monkeypatch):
    """The real Qwen2-Audio wiring (transformers' current API), with from_pretrained faked.

    No weights are downloaded: AutoProcessor / Qwen2AudioForConditionalGeneration's
    from_pretrained return fakes, so _load_qwen2_audio and qwen2_audio_pipeline run as
    they would on the 7B checkpoint: chat template with an audio part, the processor's
    ``audio=`` at its own rate, one forward pass, softmax over the Yes/No logits.
    """
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("soxr")
    YES, NO, VOCAB = 7, 3, 16
    seen = {}

    class _Tok:
        def encode(self, word, add_special_tokens=True):
            return {"Yes": [YES, 99], "No": [NO]}[word]

    class _Batch(dict):
        def to(self, device):
            seen["device"] = device
            return self

    class _Processor:
        tokenizer = _Tok()
        feature_extractor = type("FE", (), {"sampling_rate": 16000})()

        def apply_chat_template(self, conversation, *, add_generation_prompt, tokenize):
            seen["conversation"], seen["gen_prompt"] = conversation, add_generation_prompt
            return "<chat>"

        def __call__(self, *, text, audio, sampling_rate, return_tensors):
            seen["audio_len"], seen["sr"] = len(audio[0]), sampling_rate
            return _Batch(input_ids=torch.zeros((1, 4), dtype=torch.long))

    class _Model:
        device = "cpu"

        def eval(self):
            seen["eval"] = True
            return self

        def __call__(self, **inputs):
            logits = torch.zeros((1, 4, VOCAB))
            logits[0, -1, YES] = 2.0
            return type("Out", (), {"logits": logits})()

    def _model_from_pretrained(model_id, **kw):
        seen["model_id"], seen["load_kwargs"] = model_id, kw
        return _Model()

    monkeypatch.setattr(transformers.AutoProcessor, "from_pretrained", lambda m: _Processor())
    monkeypatch.setattr(
        transformers.Qwen2AudioForConditionalGeneration, "from_pretrained", _model_from_pretrained
    )
    import soundfile as sf

    c = _candidate_with_audio(tmp_path)
    sf.write(c.sound.uri, np.zeros(6144, dtype=np.float32), 48000)  # resampled to 2048 @ 16k
    judge = AudioLMJudge(tau=0.5)
    v = judge.judge(SoundEvent(query="a dog barking"), c)
    assert v.match is True and v.confidence == pytest.approx(1 / (1 + np.exp(-2.0)), abs=1e-6)
    assert judge.last_response["p_no"] == pytest.approx(1 - v.confidence, abs=1e-6)
    assert seen["model_id"] == "Qwen/Qwen2-Audio-7B-Instruct"
    assert seen["load_kwargs"] == {"dtype": "auto", "device_map": "auto"} and seen["eval"]
    assert seen["sr"] == 16000 and seen["audio_len"] == 2048 and seen["gen_prompt"] is True
    parts = seen["conversation"][0]["content"]
    assert parts[0]["type"] == "audio" and "a dog barking" in parts[1]["text"]
    pipeline = judge._pipeline
    judge.judge(SoundEvent(query="rain"), c)
    assert judge._pipeline is pipeline  # loaded once, reused
