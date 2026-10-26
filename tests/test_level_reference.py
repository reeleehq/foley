"""WEAVE levels clips by measured loudness before the layer gain (#111).

A hot clip and a quiet one of the same sound must land together in the mix; a click too
short for a loudness reading is levelled by its peak; silence is left alone.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyloudnorm")

from foley.audio import WORKING_SAMPLE_RATE, to_working  # noqa: E402
from foley.base import Layer, SoundDesignTimeline, TimelineItem  # noqa: E402
from foley.level import reference_gain_db  # noqa: E402
from foley.qc import measure_lufs  # noqa: E402
from foley.weave.align import FakeAligner  # noqa: E402
from foley.weave.render import FullRender, RenderCache, render  # noqa: E402

SR = 48_000


def _tone(seconds, amp, freq=300.0):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype("float32")


def test_gain_brings_any_level_to_the_reference():
    for amp in (0.01, 0.1, 0.5):
        clip = _tone(1.0, amp)
        gain = reference_gain_db(clip, SR)
        got = measure_lufs(clip * 10 ** (gain / 20), SR)
        assert got == pytest.approx(-16.0, abs=0.3)


def test_gain_never_lets_the_peak_pass_the_ceiling():
    click = np.zeros(SR, dtype="float32")
    click[100] = 0.9  # high crest: the loudness target would clip it
    peak_db = 20 * np.log10(0.9) + reference_gain_db(click, SR)
    assert peak_db <= -1.0 + 1e-6


def test_a_clip_too_short_for_loudness_is_levelled_by_its_peak():
    click = _tone(0.1, 0.02)  # 100 ms: under one BS.1770 block
    assert measure_lufs(click, SR) is None
    gain = reference_gain_db(click, SR)
    assert 20 * np.log10(0.02) + gain == pytest.approx(-6.0, abs=0.01)


def test_silence_and_garbage_are_left_alone():
    assert reference_gain_db(np.zeros(SR, "float32"), SR) == 0.0
    assert reference_gain_db(np.full(SR, np.nan, "float32"), SR) == 0.0
    assert reference_gain_db(np.zeros(0, "float32"), SR) == 0.0
    assert reference_gain_db(_tone(1.0, 1e-6), SR) == 0.0  # under -80 dBFS


def test_the_boost_is_capped():
    assert reference_gain_db(_tone(1.0, 3e-3), SR) <= 36.0


def test_a_long_near_silent_clip_is_not_amplified():
    assert reference_gain_db(_tone(1.0, 2e-4), SR) == 0.0  # below the loudness gate


def test_a_loud_transient_is_levelled_up_to_the_ceiling_the_caller_sets():
    clip = np.zeros(SR, dtype="float32")
    clip[100] = 0.9
    clip += _tone(1.0, 0.002)
    held = reference_gain_db(clip, SR)  # default ceiling: -1 dBFS
    freed = reference_gain_db(
        clip, SR, peak_ceiling_dbfs=-1.0 + 9.0
    )  # sfx_fg's layer gain
    assert freed > held + 8.0  # the -1 dBFS ceiling no longer holds back the transient


class _Lib:
    def __init__(self, door_amp):
        voice = (0.1 * np.random.default_rng(1).standard_normal(2 * SR)).astype(
            "float32"
        )
        self.arrays = {"nar": (voice, SR), "door": (_tone(0.5, door_amp), SR)}

    def array(self, ref, *, sr=None, mono=True):
        s, o = self.arrays[ref]
        return to_working(
            s, o, mono=mono, target_sr=WORKING_SAMPLE_RATE if sr is None else sr
        )


def _bus_lufs(door_amp, strategy):
    tl = SoundDesignTimeline(
        narration_ref="nar",
        items=[
            TimelineItem(
                clip_ref="door", onset="on 'door'", gain=0.0, layer=Layer.sfx_fg
            )
        ],
    )
    r = render(
        tl, _Lib(door_amp), sr=SR, transcript="the door opened", aligner=FakeAligner(),
        apply_strategy=strategy,
    )  # fmt: skip
    return measure_lufs(r.buses[Layer.sfx_fg], SR)


def test_a_hot_and_a_quiet_clip_land_together_in_the_mix():
    hot, quiet = _bus_lufs(0.8, FullRender()), _bus_lufs(0.01, FullRender())
    assert abs(hot - quiet) < 1.5
    asstored = abs(
        _bus_lufs(0.8, FullRender(level_clips=False))
        - _bus_lufs(0.01, FullRender(level_clips=False))
    )
    assert asstored > 30  # the spread levelling removes


def test_the_render_cache_tells_the_two_strategies_apart():
    cache = RenderCache()
    kw = dict(sr=SR, transcript="the door opened", aligner=FakeAligner(), cache=cache)
    tl = SoundDesignTimeline(
        narration_ref="nar",
        items=[
            TimelineItem(
                clip_ref="door", onset="on 'door'", gain=0.0, layer=Layer.sfx_fg
            )
        ],
    )
    lib = _Lib(0.8)
    on = render(tl, lib, apply_strategy=FullRender(), **kw).buses[Layer.sfx_fg]
    off = render(tl, lib, apply_strategy=FullRender(level_clips=False), **kw).buses[
        Layer.sfx_fg
    ]
    assert not np.array_equal(on, off)
