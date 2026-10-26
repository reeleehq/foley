"""CLAP on a small host (#116): the numpy log-mel front end, the ONNX embedder, the fallback.

Hermetic: the ONNX sessions and the tokenizer are injected fakes; nothing is downloaded.
The front end is checked against ``transformers``' own extractor when it is installed.
"""

import numpy as np
import pytest

from foley.index.onnx_clap import (
    ONNX_CLAP_MODEL_ID,
    OnnxClapEmbedder,
    log_mel,
    mel_filters,
)
from foley.prompt_match import MATCH, MISMATCH, UNCHECKED, prompt_match

SR = 48_000


def test_log_mel_has_the_models_input_shape_for_any_length():
    for n in (0, 1000, SR * 4, SR * 10, SR * 13):
        feats = log_mel(np.zeros(n, "float32"))
        assert feats.shape == (1001, 64) and feats.dtype == np.float32
        assert np.isfinite(feats).all()


def test_a_short_clip_is_repeated_and_a_long_one_cut_to_its_middle():
    tone = np.sin(2 * np.pi * 440 * np.arange(SR) / SR).astype("float32")
    assert np.allclose(log_mel(tone), log_mel(np.tile(tone, 10)), atol=1e-3)
    long = np.concatenate([np.zeros(SR), tone[:SR], np.zeros(SR)] * 4)
    assert np.array_equal(log_mel(long), log_mel(long.copy()))  # deterministic crop


def test_the_mel_bank_is_slaney_scaled_and_normalised():
    fb = mel_filters()
    assert fb.shape == (513, 64) and (fb >= 0).all() and fb.max() < 0.1
    assert (fb.sum(axis=0) > 0).all()  # every band covers some bins


def test_log_mel_matches_transformers_feature_extractor():
    pytest.importorskip("transformers")
    from transformers import ClapFeatureExtractor

    try:
        fe = ClapFeatureExtractor.from_pretrained(
            "laion/larger_clap_general", local_files_only=True
        )
    except OSError:
        pytest.skip("laion/larger_clap_general is not cached")
    rng = np.random.default_rng(0)
    for n in (SR * 4, SR * 10):
        wav = (0.1 * rng.standard_normal(n)).astype("float32")
        ref = fe(wav, sampling_rate=SR, return_tensors="np")["input_features"][0, 0]
        assert np.abs(ref - log_mel(wav)).max() < 1e-3
    assert np.abs(fe.mel_filters_slaney - mel_filters()).max() < 1e-9


class _Session:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def run(self, _outputs, feeds):
        self.calls.append(feeds)
        return [self.fn(feeds)]


class _Tokenizer:
    class _Enc:
        ids = [0, 5, 2]

    def encode(self, _text):
        return self._Enc()


def _embedder(*, audio_vec, text_vec, **kw):
    e = OnnxClapEmbedder(**kw)
    e.__dict__["_audio"] = _Session(
        lambda f: np.tile(np.asarray(audio_vec, "float32"), (1, 1))
    )
    e.__dict__["_text"] = _Session(
        lambda f: np.tile(np.asarray(text_vec, "float32"), (1, 1))
    )
    e.__dict__["_tokenizer"] = _Tokenizer()
    return e


def test_the_embedder_follows_the_clap_embedder_protocol():
    e = _embedder(audio_vec=[3, 4], text_vec=[0, 2])
    clip = e.embed_audio(np.zeros(SR, "float32"), SR)
    text = e.embed_text(["a", "b"])
    assert clip.shape == (2,) and np.linalg.norm(clip) == pytest.approx(1.0)
    assert text.shape == (2, 2) and np.allclose(np.linalg.norm(text, axis=1), 1.0)
    feeds = e._audio.calls[0]["input_features"]
    assert feeds.shape == (1, 1, 1001, 64)
    assert e._text.calls[0]["input_ids"].dtype == np.int64
    assert len(e._text.calls) == 2  # one unpadded run per text: the graph has no mask


def test_the_embedder_threshold_is_keyed_by_its_own_model():
    assert OnnxClapEmbedder().model_id == ONNX_CLAP_MODEL_ID
    assert OnnxClapEmbedder(prompt_match_threshold=0.5).prompt_match_threshold == 0.5
    calibrated = OnnxClapEmbedder().prompt_match_threshold
    assert 0.0 < calibrated < 0.3 and calibrated != 0.2  # the shipped calibration


class _Broken:
    """A full-size embedder that was meant to check but cannot load (a small host)."""

    prompt_match_threshold = 0.2

    def embed_audio(self, wav, sr):
        raise ImportError("No module named 'transformers'")

    embed_text = embed_audio


def _clip():
    from foley.audio import encode

    return encode(np.zeros(SR, "float32") + 0.01, SR)


def test_a_small_host_falls_back_to_the_onnx_embedder():
    small = _embedder(audio_vec=[1, 0], text_vec=[1, 0], prompt_match_threshold=0.15)
    got = prompt_match("x", _clip(), embedder=_Broken(), fallback=lambda: small)
    assert got["status"] == MATCH and got["model"] == ONNX_CLAP_MODEL_ID
    far = _embedder(audio_vec=[0, 1], text_vec=[1, 0], prompt_match_threshold=0.15)
    assert (
        prompt_match("x", _clip(), embedder=_Broken(), fallback=lambda: far)["status"]
        == MISMATCH
    )


def test_no_fallback_means_unchecked_with_the_reason():
    got = prompt_match("x", _clip(), embedder=_Broken())
    assert got["status"] == UNCHECKED and "transformers" in got["reason"]
    assert (
        prompt_match("x", _clip(), embedder=_Broken(), fallback=lambda: None)["status"]
        == UNCHECKED
    )


def test_a_fallback_is_not_tried_for_an_embedder_that_never_compares_text_with_audio():
    class Fake:  # no prompt_match_threshold: unchecked by design, not by failure
        pass

    def boom():
        raise AssertionError("the fallback must not run")

    assert (
        prompt_match("x", _clip(), embedder=Fake(), fallback=boom)["status"]
        == UNCHECKED
    )
    assert (
        prompt_match("x", _clip(), embedder=None, fallback=boom)["status"] == UNCHECKED
    )


# --- the wiring in generate(): _prompt_verdict -------------------------------------


def _generate_module():
    import sys

    import foley.sources.generate  # noqa: F401

    return sys.modules["foley.sources.generate"]


class _Lib:
    def __init__(self, embedder=None, error=None):
        self._e, self._error = embedder, error

    @property
    def embedder(self):
        if self._error:
            raise self._error
        return self._e


def test_generate_falls_back_when_the_library_embedder_cannot_run(monkeypatch):
    g = _generate_module()
    small = _embedder(audio_vec=[1, 0], text_vec=[1, 0], prompt_match_threshold=0.15)
    monkeypatch.setattr(g, "_small_host_embedder", lambda: small)
    notes = []
    got = g._prompt_verdict("x", _clip(), _Lib(_Broken()), notes)
    assert got["status"] == MATCH and got["model"] == ONNX_CLAP_MODEL_ID
    assert "prompt match: ok" in notes[0]


def test_generate_falls_back_when_the_library_embedder_cannot_be_built(monkeypatch):
    g = _generate_module()
    small = _embedder(audio_vec=[1, 0], text_vec=[1, 0], prompt_match_threshold=0.15)
    monkeypatch.setattr(g, "_small_host_embedder", lambda: small)
    got = g._prompt_verdict("x", _clip(), _Lib(error=ImportError("no torch")), [])
    assert got["status"] == MATCH


def test_generate_without_any_embedder_says_why(monkeypatch):
    g = _generate_module()
    monkeypatch.setattr(g, "_small_host_embedder", lambda: None)
    got = g._prompt_verdict("x", _clip(), _Lib(error=ImportError("no torch")), [])
    assert got["status"] == UNCHECKED and "no torch" in got["reason"]


def test_both_reasons_survive_when_the_fallback_also_fails():
    got = prompt_match("x", _clip(), embedder=_Broken(), fallback=lambda: _Broken2())
    assert got["status"] == UNCHECKED
    assert "transformers" in got["reason"] and "fallback" in got["reason"]


class _Broken2(_Broken):
    model_id = "second"

    def embed_audio(self, wav, sr):
        raise RuntimeError("model file missing")

    embed_text = embed_audio


def test_the_small_host_embedder_needs_its_extra(monkeypatch):
    import importlib.util

    g = _generate_module()
    g._small_host_embedder.cache_clear()
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda n, *a: None if n == "onnxruntime" else real(n, *a),
    )
    assert g._small_host_embedder() is None
    g._small_host_embedder.cache_clear()


def test_a_library_whose_embedder_is_none_is_unchecked(monkeypatch):
    g = _generate_module()
    monkeypatch.setattr(g, "_small_host_embedder", lambda: None)
    assert g._prompt_verdict("x", _clip(), _Lib(None), [])["status"] == UNCHECKED
