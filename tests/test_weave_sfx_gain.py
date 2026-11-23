"""The effects-bus level under the narration: ``sfx_gain_db`` (#292)."""

import importlib
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("mixing.loudness")

import foley  # noqa: E402
from foley.audio import WORKING_SAMPLE_RATE, to_working  # noqa: E402
from foley.base import Layer, SoundDesignTimeline, TimelineItem  # noqa: E402
from foley.weave.align import FakeAligner  # noqa: E402
from foley.weave.render import RenderCache, check_sfx_gain_db, render  # noqa: E402

render_module = importlib.import_module("foley.weave.render")  # the package shadows it
pytestmark = pytest.mark.filterwarnings("ignore:foley.weave.*not licensed:FutureWarning")

SR = 48000
TRANSCRIPT = "the door opened wide"


class _Lib:
    def __init__(self):
        rng = np.random.default_rng(1)
        voice = (0.1 * rng.standard_normal(2 * SR)).astype("float32")
        door = (0.5 * np.sin(2 * np.pi * 300 * np.arange(int(0.2 * SR)) / SR)).astype("float32")
        rain = (0.15 * rng.standard_normal(SR)).astype("float32")
        self.arrays = {"nar": (voice, SR), "door": (door, SR), "rain": (rain, SR)}

    def array(self, ref, *, sr=None, mono=True):
        s, o = self.arrays[ref]
        return to_working(s, o, mono=mono, target_sr=WORKING_SAMPLE_RATE if sr is None else sr)

    def __contains__(self, k):
        return k in self.arrays


def _tl(items=True):
    return SoundDesignTimeline(
        narration_ref="nar",
        items=(
            [
                TimelineItem(clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg),
                TimelineItem(
                    clip_ref="rain", onset=None, gain=-18.0, layer=Layer.ambience, loop=True
                ),
            ]
            if items
            else []
        ),
    )


def _render(timeline=None, **kw):
    timeline = _tl() if timeline is None else timeline
    return render(timeline, _Lib(), sr=SR, transcript=TRANSCRIPT, aligner=FakeAligner(), **kw)


@pytest.fixture
def unmastered(monkeypatch):
    """Skip mastering, so the pre-master mix (where the gain acts) can be measured."""
    real = render_module.master

    def passthrough(mix, sr, profile):
        _, report = real(mix, sr, profile)
        return mix, report

    monkeypatch.setattr(render_module, "master", passthrough)


def test_zero_db_is_the_mix_as_before_byte_for_byte():
    assert np.array_equal(_render().audio, _render(sfx_gain_db=0.0).audio)
    assert np.array_equal(_render().audio, _render(sfx_gain_db=0).audio)


def test_the_gain_scales_the_effects_bus_and_leaves_the_voice(unmastered):
    voice_only = _render(_tl(items=False)).audio
    full = _render().audio
    quieter = _render(sfx_gain_db=-12.0).audio
    effects, effects_quieter = full - voice_only, quieter - voice_only
    assert np.abs(effects).max() > 0.01  # the fixture has audible effects
    np.testing.assert_allclose(effects_quieter, effects * 10 ** (-12 / 20), atol=1e-6)


def test_minus_inf_mutes_the_effects():
    voice_only = _render(_tl(items=False)).audio
    muted = _render(sfx_gain_db=float("-inf")).audio
    np.testing.assert_allclose(muted, voice_only, atol=1e-6)


def test_the_gain_acts_after_ducking_and_mastering_still_holds_the_target():
    louder, quieter = _render(sfx_gain_db=6.0), _render(sfx_gain_db=-6.0)
    assert not np.array_equal(louder.audio, quieter.audio)
    for r in (louder, quieter):
        report = r.master_report.to_dict()
        assert report["target_lufs"] == r.timeline.master.target_lufs
        assert np.isfinite(r.audio).all()


def test_the_cache_holds_pre_gain_buses():
    """A level change re-renders from the cached buses and still matches a cold render."""
    cache = RenderCache()
    _render(cache=cache)
    n = len(cache)
    warm = _render(cache=cache, sfx_gain_db=-9.0)
    assert len(cache) == n  # nothing re-rendered: the gain is applied after the cache
    assert np.array_equal(warm.audio, _render(sfx_gain_db=-9.0).audio)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "loud", None])
def test_unusable_levels_are_refused(bad):
    with pytest.raises(ValueError, match="sfx_gain_db"):
        check_sfx_gain_db(bad)
    with pytest.raises(ValueError, match="sfx_gain_db"):
        _render(sfx_gain_db=bad)


def test_numeric_strings_and_ints_are_levels():
    assert check_sfx_gain_db("-3") == -3.0
    assert check_sfx_gain_db(-6) == -6.0
    assert check_sfx_gain_db(float("-inf")) == -math.inf


def _weave(**kw):
    rng = np.random.default_rng(2)
    voice = (0.1 * rng.standard_normal(2 * SR)).astype("float32")
    tl = SoundDesignTimeline(
        items=[TimelineItem(clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg)]
    )
    lib = _Lib()
    return foley.weave(voice, tl, library=lib, transcript=TRANSCRIPT, aligner=FakeAligner(), **kw)


def test_weave_forwards_the_level_and_records_it_only_when_set():
    with foley.obs.run("session") as run:
        default = _weave()
        assert "sfx_gain_db" not in run.manifest.plan_ref
    with foley.obs.run("session") as run:
        quieter = _weave(sfx_gain_db=-12.0)
        assert run.manifest.plan_ref["sfx_gain_db"] == -12.0
    with foley.obs.run("session") as run:
        _weave(sfx_gain_db=float("-inf"))
        assert run.manifest.plan_ref["sfx_gain_db"] == "-inf"  # JSON has no -Infinity
    assert not np.array_equal(default.audio, quieter.audio)


def test_weave_refuses_a_bad_level_before_rendering(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("rendered")

    monkeypatch.setattr("foley.weave.render", boom)
    with pytest.raises(ValueError, match="sfx_gain_db"):
        _weave(sfx_gain_db=float("nan"))


def test_score_refuses_a_bad_level_before_any_spend(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("searched")

    monkeypatch.setattr("foley.find", boom)
    with pytest.raises(ValueError, match="sfx_gain_db"):
        foley.score("The door creaked.", audio=np.zeros(SR, dtype="float32"), sfx_gain_db=float("nan"))
