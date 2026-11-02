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


#: Fake vocabulary: the Yes/yes and No/no single-token ids, and the multi-token "Nope".
_IDS = {"Yes": [7], "yes": [8], "No": [3], "no": [4], "Nope": [3, 9]}
_VOCAB = 16


def _fake_qwen(torch, seen, *, chunk_length=30, next_logits=None):
    """A (processor, model) pair with Qwen2-Audio's interface, for the real pipeline code."""

    class _Tok:
        def encode(self, word, add_special_tokens=True):
            return _IDS[word]

    class _Batch(dict):
        def to(self, device):
            seen["device"] = device
            return self

    class _Processor:
        tokenizer = _Tok()
        feature_extractor = type(
            "FE", (), {"sampling_rate": 16000, "chunk_length": chunk_length}
        )()

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
            logits = torch.zeros((1, 4, _VOCAB))
            for tok, value in (next_logits or {}).items():
                logits[0, -1, tok] = value
            return type("Out", (), {"logits": logits})()

    return _Processor(), _Model()


def test_audiolm_judge_real_pipeline_with_faked_model_load(tmp_path, monkeypatch):
    """The real Qwen2-Audio wiring, with from_pretrained faked (no weights downloaded).

    _load_qwen2_audio and qwen2_audio_pipeline run as they would on the 7B checkpoint:
    the conversation through the chat template, the clip resampled to the processor's
    rate, one forward pass, P(yes) = softmax mass on {Yes, yes} over {Yes, yes, No, no}.
    That the conversation and the ``audio=`` call fit transformers' real Qwen2-Audio
    processor is checked separately (test_aqa_conversation_fits_the_real_processor).
    """
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("soxr")
    seen = {}
    processor, model = _fake_qwen(torch, seen, next_logits={7: 2.0, 8: 1.0})

    def _proc_from_pretrained(model_id, **kw):
        seen["processor_kwargs"] = kw
        return processor

    def _model_from_pretrained(model_id, **kw):
        seen["model_id"], seen["load_kwargs"] = model_id, kw
        return model

    monkeypatch.setattr(transformers.AutoProcessor, "from_pretrained", _proc_from_pretrained)
    monkeypatch.setattr(
        transformers.Qwen2AudioForConditionalGeneration, "from_pretrained", _model_from_pretrained
    )
    import soundfile as sf

    c = _candidate_with_audio(tmp_path)
    sf.write(c.sound.uri, np.zeros(6144, dtype=np.float32), 48000)  # resampled to 2048 @ 16k
    load = {"dtype": "auto", "device_map": "auto", "revision": "abc123"}
    judge = AudioLMJudge(tau=0.5, load_kwargs=load)
    v = judge.judge(SoundEvent(query="a dog barking"), c)
    e = np.exp
    assert v.match is True
    assert v.confidence == pytest.approx((e(2) + e(1)) / (e(2) + e(1) + 2), abs=1e-6)
    assert judge.last_response["p_no"] == pytest.approx(1 - v.confidence, abs=1e-6)
    assert seen["model_id"] == "Qwen/Qwen2-Audio-7B-Instruct" and seen["eval"]
    assert seen["load_kwargs"] == load and seen["processor_kwargs"] == {"revision": "abc123"}
    assert seen["sr"] == 16000 and seen["audio_len"] == 2048 and seen["gen_prompt"] is True
    assert seen["conversation"] == V.aqa_conversation(
        "Does this audio contain a dog barking? Answer strictly yes or no."
    )
    pipeline = judge._pipeline
    judge.judge(SoundEvent(query="rain"), c)
    assert judge._pipeline is pipeline  # loaded once, reused
    assert AudioLMJudge().load_kwargs == {"dtype": "auto", "device_map": "auto"}


def test_qwen2_audio_pipeline_refuses_multi_token_answers_and_warns_on_long_clips():
    torch = pytest.importorskip("torch")
    pytest.importorskip("soxr")
    seen = {}
    with pytest.raises(ValueError, match="'Nope' is 2 tokens"):
        V.qwen2_audio_pipeline(*_fake_qwen(torch, seen), answers=(("Yes",), ("Nope",)))
    pipeline = V.qwen2_audio_pipeline(*_fake_qwen(torch, seen, chunk_length=0.1))
    with pytest.warns(UserWarning, match="hears only the first 0.1 s"):
        out = pipeline("q", np.zeros(2048, dtype=np.float32), 16000)  # 0.128 s
    assert out["p_yes"] == pytest.approx(0.5)  # all four answer logits equal


def test_aqa_conversation_fits_the_real_processor():
    """transformers' Qwen2-Audio processor takes ``audio=``, and its chat template turns
    foley's conversation into an <|AUDIO|> slot plus the question (no download)."""
    pytest.importorskip("transformers")
    import inspect

    from transformers import Qwen2AudioProcessor

    assert "audio" in inspect.signature(Qwen2AudioProcessor.__call__).parameters
    try:
        from transformers.utils.chat_template_utils import _compile_jinja_template
    except ImportError:  # pragma: no cover - older/newer transformers layout
        jinja2 = pytest.importorskip("jinja2")
        _compile_jinja_template = jinja2.Template
    template = Qwen2AudioProcessor.default_chat_template.fget(None)
    text = _compile_jinja_template(template).render(
        messages=V.aqa_conversation("Does this audio contain rain?"),
        add_generation_prompt=True,
    )
    assert "<|audio_bos|><|AUDIO|><|audio_eos|>" in text
    assert "Does this audio contain rain?" in text and text.endswith("<|im_start|>assistant\n")
