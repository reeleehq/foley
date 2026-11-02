"""The procedural source kind and its first source, pyfxr (#76).

Real synthesis, offline: pyfxr is in the ``test`` extra (a small Cython wheel), so these
run in CI with no network and no model. The load-bearing assertions: a procedural clip
goes through the whole ``foley.generate`` façade under ``procedural-free`` and is not
AI output (no watermark attempted, no disclosure, ``algorithmicMedia`` credential); a
seed reproduces a non-noise preset byte for byte; a prompt picks the preset; a call
with no preset to play is refused before any work, so the generation order skips it.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")
pyfxr = pytest.importorskip("pyfxr")

import foley  # noqa: E402
from foley.base import GENERATION_AFFORDANCES, IntendedUse  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.licensing import LICENSE_FLAGS, LICENSE_META, keep  # noqa: E402
from foley.provenance import disclosure  # noqa: E402
from foley.sources._dispatch import UnsupportedParameter  # noqa: E402
from foley.sources.base import GENERATING_KINDS, generated_license  # noqa: E402
from foley.sources.capabilities import capabilities_of, list_backends  # noqa: E402
from foley.sources.pyfxr import SOURCE_CONFIG  # noqa: E402
from foley.sources.pyfxr.adapter import PyfxrAdapter  # noqa: E402
from foley.sources.pyfxr.config import SFX_PARAMS  # noqa: E402

from ._fakes import FakePipeline, fake_generator  # noqa: E402
from .test_generate_order import _swap_sources  # noqa: E402


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


class SpyWatermarker:
    """Records every embed; a procedural clip must never reach it."""

    method, version = "spy", "0"

    def __init__(self):
        self.calls = 0

    def embed(self, audio_bytes, **kw):
        self.calls += 1
        raise AssertionError("a procedural clip was sent to the watermarker")


class SpyAdapter(PyfxrAdapter):
    """The real adapter, counting its calls."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def generate(self, prompt, **kw):
        self.calls += 1
        return super().generate(prompt, **kw)


# ---------------------------------------------------------------------------
# the kind, the licence row, the affordance
# ---------------------------------------------------------------------------


def test_procedural_is_a_generating_kind_with_its_own_licence_row():
    assert GENERATING_KINDS == ("generate", "procedural")
    assert SOURCE_CONFIG["kind"] == "procedural"
    flags = LICENSE_FLAGS["procedural-free"]
    assert flags.commercial_ok and flags.redistribute_standalone_ok
    assert flags.ai_training_ok and not flags.requires_attribution
    assert "procedural-free" in LICENSE_META


def test_the_config_presets_are_the_canonical_ones_and_its_params_pyfxrs():
    assert set(SOURCE_CONFIG["presets"]) == set(GENERATION_AFFORDANCES["preset"].choices)
    assert set(SOURCE_CONFIG["preset_keywords"]) == set(SOURCE_CONFIG["presets"])
    assert all(callable(getattr(pyfxr, f)) for f in SOURCE_CONFIG["presets"].values())
    native = {k for k, v in vars(pyfxr.SFX).items() if isinstance(v, pyfxr.FloatParam)}
    assert set(SFX_PARAMS) == native | {"wave_type"}


def test_not_ai_generated_license_keeps_provenance_without_disclosure():
    lic = generated_license(
        source="pyfxr",
        license_id="procedural-free",
        generator_model="pyfxr",
        generation_prompt="zap",
        generation_seed=3,
        ai_generated=False,
    )
    assert lic.is_ai_generated is False and lic.disclosure_recommended is False
    assert lic.generation_seed == 3 and lic.generation_reproducible is True
    cred = disclosure.build_content_credential(lic, asset_id="x")
    actions = cred["manifest"]["assertions"][0]["data"]["actions"]
    assert actions[0]["digitalSourceType"] == disclosure.IPTC_ALGORITHMIC_MEDIA
    labels = [a["label"] for a in cred["manifest"]["assertions"]]
    assert "foley.generation" in labels  # the reproducibility record is kept
    assert disclosure.art50_checklist(lic)["publish_ready"] is True


def test_capabilities_and_price():
    view = capabilities_of(SOURCE_CONFIG)
    assert view["kind"] == "procedural"
    assert view["offline_capable"] is True and view["deterministic"] is True
    assert view["watermarked"] is False and view["modes"] == ["t2a"]
    assert list_backends(kind="procedural") == ["pyfxr"]
    assert "pyfxr" in list_backends(supports="offline_capable")
    assert foley.estimate("generate", backend="pyfxr") == 0.0
    from foley.sources.generate import DEFAULT_GENERATE_ORDER

    assert "pyfxr" not in DEFAULT_GENERATE_ORDER


# ---------------------------------------------------------------------------
# through the façade
# ---------------------------------------------------------------------------


def test_facade_stores_a_procedural_clip_unwatermarked(library):
    wm = SpyWatermarker()
    clip = foley.generate(
        "a laser zap", backend="pyfxr", seed=1, library=library, watermarker=wm
    )
    lic = clip.sound.license
    assert lic.license_id == "procedural-free"
    assert lic.is_ai_generated is False and lic.disclosure_recommended is False
    assert lic.watermark is None and wm.calls == 0
    assert lic.generation_params["preset"] == "laser"
    assert keep(lic, IntendedUse(commercial=True, redistribute_standalone=True))
    assert len(library) == 1
    assert "AI-generated" not in foley.provenance.credits.attribution_line(clip.sound)


def test_an_explicit_watermark_request_is_noted_not_applied(library):
    clip = foley.generate(
        "", backend="pyfxr", preset="jump", seed=2, library=library,
        watermark=True, watermarker=SpyWatermarker(),
    )
    assert any("not watermarked: procedural" in n for n in clip.notes)


def test_same_seed_same_bytes_and_a_different_seed_different_params():
    a = PyfxrAdapter().generate("", preset="laser", seed=11)
    b = PyfxrAdapter().generate("", preset="laser", seed=11)
    c = PyfxrAdapter().generate("", preset="laser", seed=12)
    assert a.audio_bytes == b.audio_bytes
    params = lambda clip: clip.candidate.sound.license.generation_params  # noqa: E731
    assert params(a) == params(b) and params(a) != params(c)
    assert set(SFX_PARAMS) <= set(params(a))  # the full resolved set, defaults too


def test_the_global_random_is_never_reseeded():
    import random

    state = random.getstate()
    PyfxrAdapter().generate("", preset="pickup", seed=5)
    assert random.getstate() == state


def test_noise_waveform_clips_carry_a_reproducibility_note():
    clip = PyfxrAdapter().generate("", preset="explosion", seed=1)
    assert clip.candidate.sound.license.generation_params["wave_type"] == 3
    assert any("not bit-reproducible" in n for n in clip.notes)


@pytest.mark.parametrize(
    "prompt, preset",
    [
        ("a coin pickup", "pickup"),
        ("blaster fire", "laser"),
        ("a big BOOM", "explosion"),
        ("a level up chime", "powerup"),
        ("ouch", "hurt"),
        ("boing", "jump"),
        ("a menu blip", "select"),
        ("two zaps, then an explosion", "laser"),  # the first named wins
    ],
)
def test_the_prompt_picks_the_preset(prompt, preset):
    clip = PyfxrAdapter().generate(prompt, seed=1)
    assert clip.candidate.sound.license.generation_params["preset"] == preset
    assert any("matched from the prompt" in n for n in clip.notes)


def test_no_preset_and_no_match_is_refused_before_any_work(library):
    spy = SpyAdapter()
    with pytest.raises(UnsupportedParameter, match="preset="):
        foley.generate("gentle rain", backend="pyfxr", library=library, adapter=spy)
    assert spy.calls == 0 and len(library) == 0


def test_the_order_skips_a_procedural_source_with_nothing_to_play(monkeypatch, library):
    from foley.sources.stable_audio.adapter import StableAudioAdapter

    spy = SpyAdapter()
    sa = StableAudioAdapter(pipeline=FakePipeline(), make_generator=fake_generator)
    _swap_sources(monkeypatch, {"pyfxr": spy, "stable_audio": sa})
    clip = foley.generate(
        "gentle rain", backend=("pyfxr", "stable_audio"), library=library
    )
    assert spy.calls == 0
    assert clip.sound.license.source == "stable_audio"
    assert any("pyfxr" in n for n in clip.notes)


def test_an_unknown_preset_is_refused(library):
    with pytest.raises(ValueError, match="preset"):
        foley.generate("zap", backend="pyfxr", preset="coin", library=library)


def test_provider_params_override_the_draw_and_are_recorded(library):
    clip = foley.generate(
        "", backend="pyfxr", preset="laser", seed=3, library=library,
        provider_params={"base_freq": 0.9, "wave_type": "sine"},
    )
    params = clip.sound.license.generation_params
    assert params["base_freq"] == 0.9 and params["wave_type"] == 2
    assert params["provider_params"] == {"base_freq": 0.9, "wave_type": "sine"}


def test_an_unknown_provider_param_is_refused_at_plan_time(library):
    spy = SpyAdapter()
    with pytest.raises(ValueError, match="not native params"):
        foley.generate(
            "zap", backend="pyfxr", adapter=spy, library=library,
            provider_params={"base_frequency": 0.2},
        )
    assert spy.calls == 0


def test_an_unsupported_affordance_is_noted(library):
    with pytest.warns(UserWarning, match="duration_s"):
        clip = foley.generate(
            "zap", backend="pyfxr", seed=1, duration_s=2.0, library=library
        )
    assert any("duration_s" in n for n in clip.notes)
    direct = PyfxrAdapter().generate("zap", seed=1, steps=8)
    assert any("'steps'" in n for n in direct.notes)


def test_a_short_blip_is_padded_to_the_qc_minimum():
    from foley.audio import load
    from foley.qc import DEFAULT_QC_THRESHOLDS

    clip = PyfxrAdapter().generate("", preset="select", seed=1)  # a ~50 ms blip
    samples, sr = load(clip.audio_bytes)
    assert len(samples) / sr >= DEFAULT_QC_THRESHOLDS.duration_min_s
    assert clip.candidate.sound.license.generation_params["padded_to_s"]
