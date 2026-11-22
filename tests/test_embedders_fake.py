"""ClapEmbedder logic with a fake model/processor: no weights, no download."""

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from foley.index import embedders as E  # noqa: E402


class _Inputs(dict):
    def to(self, device):
        self.device = device
        return self


class FakeProcessor:
    def __init__(self, fail_audio_kw=False):
        self.fail_audio_kw = fail_audio_kw
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.fail_audio_kw and "audio" in kw:
            raise TypeError("unexpected keyword 'audio'")
        return _Inputs(x=1)


class FakeModel:
    def __init__(self, dim=4):
        self.config = type("C", (), {"projection_dim": dim})()

    def get_text_features(self, **kw):
        return torch.tensor([[3.0, 4.0, 0.0, 0.0]])

    def get_audio_features(self, **kw):
        return torch.tensor([[0.0, 0.0, 6.0, 8.0]])


def _emb(**kw):
    e = E.ClapEmbedder(device="cpu", **kw)
    e.__dict__["_model"] = FakeModel()
    e.__dict__["_processor"] = FakeProcessor()
    return e


def test_embed_text_is_normalised_2d_and_accepts_str_or_list():
    e = _emb()
    out = e.embed_text("door")
    assert out.shape == (1, 4) and out.dtype == np.float32
    assert np.allclose(np.linalg.norm(out, axis=-1), 1.0)
    assert np.allclose(out[0], [0.6, 0.8, 0, 0])
    assert e._processor.calls[0]["text"] == ["door"]
    e.embed_text(["a", "b"])
    assert e._processor.calls[1]["text"] == ["a", "b"]


def test_embed_audio_is_normalised_1d():
    e = _emb()
    out = e.embed_audio(np.zeros(4800, dtype="float32"), 48_000)
    assert out.shape == (4,)
    assert np.allclose(out, [0, 0, 0.6, 0.8])


def test_process_audio_falls_back_to_legacy_keyword():
    e = _emb()
    e.__dict__["_processor"] = FakeProcessor(fail_audio_kw=True)
    e._process_audio(np.zeros(10), 48_000)
    assert "audios" in e._processor.calls[-1]


def test_device_explicit_and_auto(monkeypatch):
    assert E.ClapEmbedder(device="cpu").device == "cpu"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert E.ClapEmbedder().device == "cpu"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert E.ClapEmbedder().device == "cuda"


def test_open_source_flag_and_threshold_override():
    assert E.ClapEmbedder("laion/x").open_source is True
    assert E.ClapEmbedder("other/x").open_source is False
    assert E.ClapEmbedder(prompt_match_threshold=0.42).prompt_match_threshold == 0.42


def test_threshold_falls_back_to_provisional_for_unknown_checkpoint():
    assert (
        E.ClapEmbedder("nobody/uncalibrated-clap").prompt_match_threshold
        == E.PROVISIONAL_PROMPT_MATCH_THRESHOLD
    )


def test_dim_resolved_from_config(monkeypatch):
    import transformers

    cfg = type("Cfg", (), {"projection_dim": 256})()
    monkeypatch.setattr(transformers.AutoConfig, "from_pretrained", lambda *a, **k: cfg)
    monkeypatch.setattr("foley.runtime.load_pretrained", lambda fn, mid, **k: fn(mid))
    assert E.ClapEmbedder("other/clap").dim == 256


def test_dim_falls_back_to_loaded_model_config(monkeypatch):
    import transformers

    def boom(*a, **k):
        raise OSError("no config")

    monkeypatch.setattr(transformers.AutoConfig, "from_pretrained", boom)
    monkeypatch.setattr("foley.runtime.load_pretrained", lambda fn, mid, **k: fn(mid))
    e = E.ClapEmbedder("other/clap", device="cpu")
    e.__dict__["_model"] = FakeModel(dim=7)
    assert e.dim == 7


def test_dim_reraises_egress_blocked(monkeypatch):
    import transformers
    from foley.runtime import EgressBlocked

    def blocked(*a, **k):
        raise EgressBlocked("offline")

    monkeypatch.setattr(transformers.AutoConfig, "from_pretrained", blocked)
    monkeypatch.setattr("foley.runtime.load_pretrained", lambda fn, mid, **k: fn(mid))
    with pytest.raises(EgressBlocked):
        E.ClapEmbedder("other/clap").dim


def test_model_and_processor_load_through_load_pretrained(monkeypatch):
    import transformers

    seen = []

    class M(FakeModel):
        def to(self, d):
            seen.append(("to", d))
            return self

        def eval(self):
            seen.append("eval")
            return self

    monkeypatch.setattr(transformers.ClapModel, "from_pretrained", lambda mid: M(dim=9))
    monkeypatch.setattr(transformers.ClapProcessor, "from_pretrained", lambda mid: "proc")
    monkeypatch.setattr("foley.runtime.load_pretrained", lambda fn, mid, **k: fn(mid))
    e = E.ClapEmbedder("other/clap", device="cpu")
    assert e._processor == "proc"
    assert e._model.config.projection_dim == 9
    assert e._dim == 9 and ("to", "cpu") in seen and "eval" in seen


def test_default_embedder_is_cached():
    E.default_embedder.cache_clear()
    assert E.default_embedder() is E.default_embedder()
    E.default_embedder.cache_clear()
