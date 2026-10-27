"""WEAVE mastering — LUFS target + true-peak ceiling on synth signals."""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("mixing.loudness")

from foley.base import MASTER_PROFILES  # noqa: E402
from foley.weave.master import MasterReport, master  # noqa: E402


def _sine_stereo(freq, secs, sr, amp):
    t = np.arange(int(secs * sr)) / sr
    x = (amp * np.sin(2 * np.pi * freq * t)).astype("float32")
    return np.stack([x, x], axis=1)


def test_master_hits_podcast_target_within_tol():
    sr = 48000
    mix = _sine_stereo(200, 3.0, sr, 0.05)  # quiet input
    mastered, report = master(mix, sr, MASTER_PROFILES["podcast"])
    assert isinstance(report, MasterReport)
    assert abs(report.output_lufs - (-16.0)) < 0.5
    assert report.true_peak_dbtp <= -1.0 + 1e-6
    assert mastered.shape == mix.shape


def test_master_streaming_target():
    sr = 48000
    _, report = master(
        _sine_stereo(200, 3.0, sr, 0.05), sr, MASTER_PROFILES["streaming"]
    )
    assert abs(report.output_lufs - (-14.0)) < 0.5


def test_master_true_peak_ceiling_holds_on_loud_input():
    sr = 48000
    mix = _sine_stereo(200, 3.0, sr, 0.9)  # loud, near full-scale
    mastered, _ = master(mix, sr, MASTER_PROFILES["podcast"])
    from foley.qc import true_peak_dbtp

    assert true_peak_dbtp(mastered, sr) <= -1.0 + 0.25  # within tol of the ceiling


def test_master_report_is_json_serialisable():
    sr = 48000
    _, report = master(_sine_stereo(200, 1.0, sr, 0.1), sr, MASTER_PROFILES["podcast"])
    d = report.to_dict()
    assert d["target_lufs"] == -16.0 and d["engine"] == "inprocess"
    assert set(d) >= {"input_lufs", "output_lufs", "true_peak_dbtp", "limited"}


def test_master_injected_limiter_and_meter_are_used():
    sr = 48000
    mix = _sine_stereo(200, 3.0, sr, 0.05)
    calls = {"limiter": 0, "meter": 0}

    def limiter(m, rate, ceiling_db):
        calls["limiter"] += 1
        return m * 0.5  # a different array: the report must measure it, not trust it

    def meter(x, rate):
        calls["meter"] += 1
        return -20.0

    mastered, report = master(
        mix, sr, MASTER_PROFILES["podcast"], limiter=limiter, meter=meter
    )
    assert calls["limiter"] == 1 and calls["meter"] >= 2
    assert report.limited is True
    assert report.true_peak_dbtp == pytest.approx(
        float(__import__("foley.qc", fromlist=["x"]).true_peak_dbtp(mastered, sr))
    )
    assert report.input_lufs == -20.0 and report.output_lufs == -20.0


def _transient_program(sr, secs=6.0, seed=0):
    """A quiet bed with a few loud, band-limited hits: what a lookahead limiter is for."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs * sr)) / sr
    x = 0.05 * np.sin(2 * np.pi * 440 * t)
    n = 2400
    hit = sum(np.sin(2 * np.pi * f * t[:n] + rng.uniform(0, 6)) for f in (90, 230, 610))
    hit = 0.9 * hit / np.abs(hit).max() * np.exp(-np.arange(n) / 300)
    for k in range(1, int(secs) - 1):
        x[k * sr : k * sr + n] += hit
    return x.clip(-1, 1).astype("float32")


def _bed_mask(sr, n_frames, secs=6.0, margin_s=0.2):
    """Frames farther than ``margin_s`` from every hit (the limiter's window is 50 ms)."""
    keep = np.ones(n_frames, dtype=bool)
    for k in range(1, int(secs) - 1):
        keep[max(0, int((k - margin_s) * sr)) : int((k + 0.05 + margin_s) * sr)] = False
    return keep


def _static(mix, sr, ceiling_db):
    from foley.audio import limit_true_peak

    return limit_true_peak(mix, sr, ceiling_dbtp=ceiling_db)[0]


def test_lookahead_limiter_leaves_the_bed_alone():
    from foley.qc import true_peak_dbtp
    from foley.weave.master import lookahead_true_peak_limit

    sr = 48000
    mix = np.stack([_transient_program(sr)] * 2, axis=1) * np.float32(3.0)
    assert true_peak_dbtp(mix, sr) > 4.0  # well over the ceiling
    out = lookahead_true_peak_limit(mix, sr, -1.0)
    assert out is not mix
    bed = _bed_mask(sr, len(mix))
    bed_gain_db = 20 * np.log10(np.abs(out[bed]).max() / np.abs(mix[bed]).max())
    hit_gain_db = 20 * np.log10(np.abs(out[~bed]).max() / np.abs(mix[~bed]).max())
    assert abs(bed_gain_db) < 0.05  # the bed is untouched...
    assert hit_gain_db < -4.0  # ...while the hits came down
    assert true_peak_dbtp(out, sr) <= -1.0 + 1e-6
    assert out.dtype == mix.dtype and out.shape == mix.shape
    mono = mix[:, 0].copy()
    out1 = lookahead_true_peak_limit(mono, sr, -1.0)
    assert out1.shape == mono.shape and out1.dtype == mono.dtype
    assert true_peak_dbtp(out1, sr) <= -1.0 + 1e-6


def test_master_reaches_the_target_on_a_transient_program():
    sr = 48000
    mix = np.stack([_transient_program(sr)] * 2, axis=1)
    profile = MASTER_PROFILES["podcast"]
    _, static = master(mix, sr, profile, limiter=_static)
    limited, report = master(mix, sr, profile)
    assert report.limited is True
    assert report.true_peak_dbtp <= profile.true_peak_db + 1e-6  # the report's meter
    assert report.output_lufs > static.output_lufs + 3.0
    assert abs(report.output_lufs - profile.target_lufs) < 1.0
    assert limited.dtype == mix.dtype and limited.shape == mix.shape


def test_max_limiting_db_zero_is_the_static_master():
    from dataclasses import replace

    sr = 48000
    mix = np.stack([_transient_program(sr)] * 2, axis=1)
    profile = replace(MASTER_PROFILES["podcast"], max_limiting_db=0.0)
    _, static = master(mix, sr, profile, limiter=_static)
    _, report = master(mix, sr, profile)
    assert report.output_lufs == pytest.approx(static.output_lufs, abs=0.1)


def test_lookahead_limiter_returns_an_unclipped_mix_as_is():
    from foley.weave.master import lookahead_true_peak_limit

    sr = 48000
    quiet = _sine_stereo(200, 1.0, sr, 0.1)
    assert lookahead_true_peak_limit(quiet, sr, -1.0) is quiet
    mono = quiet[:, 0]
    assert lookahead_true_peak_limit(mono, sr, -1.0) is mono


def test_lookahead_limiter_keeps_a_nan_local_and_still_limits():
    from foley.qc import true_peak_dbtp
    from foley.weave.master import lookahead_true_peak_limit

    sr = 48000
    mix = _sine_stereo(200, 1.0, sr, 0.99) * np.float32(4.0)  # about +12 dBTP
    mix[100, 0] = np.nan
    out = lookahead_true_peak_limit(mix, sr, -1.0)
    assert np.isnan(out[100, 0]) and np.isfinite(np.delete(out[:, 0], 100)).all()
    assert np.isfinite(out[:, 1]).all()
    assert true_peak_dbtp(np.nan_to_num(out), sr) <= -1.0 + 1e-6


def test_an_injected_limiter_gets_no_headroom():
    sr = 48000
    mix = np.stack([_transient_program(sr)] * 2, axis=1)
    out, _ = master(mix, sr, MASTER_PROFILES["podcast"], limiter=lambda m, r, c: m)
    assert 20 * np.log10(np.abs(out).max()) <= -1.0 + 1e-4  # held at the sample peak


@pytest.mark.parametrize("sr", [48000, 44100, 22050])
def test_full_band_noise_is_held_at_the_ceiling_with_a_rounding_level_trim(sr):
    # The limiter and the master's meter use one meter at one factor (#190), so what
    # the master trims after the limiter is float rounding, not a meter mismatch.
    from foley.base import MasterProfile
    from foley.qc import true_peak_dbtp
    from foley.weave.master import lookahead_true_peak_limit, master

    noise = np.random.default_rng(1).normal(0, 0.3, (sr * 2, 2)).clip(-1, 1)
    stage = lookahead_true_peak_limit(noise.astype(np.float32), sr, -1.0)
    assert true_peak_dbtp(stage, sr) <= -1.0 + 0.05
    out, rep = master(noise.astype(np.float32), sr, MasterProfile(target_lufs=-10.0))
    assert rep.true_peak_dbtp <= -1.0 and true_peak_dbtp(out, sr) <= -1.0


def test_a_nan_does_not_lift_the_ceiling():
    from foley.weave.master import _held_at_ceiling

    sr = 48000
    loud = np.random.default_rng(2).normal(0, 0.5, (sr, 2)).clip(-1, 1).astype(np.float32)
    loud[100, 0] = np.nan
    out, tp = _held_at_ceiling(loud, sr, -1.0)
    finite = np.where(np.isfinite(out), out, 0)
    from foley.qc import true_peak_dbtp

    assert tp == -1.0 and true_peak_dbtp(finite, sr) <= -1.0 and np.isnan(out[100, 0])


def test_a_limiter_returning_ints_is_refused():
    from foley.base import MasterProfile
    from foley.weave.master import master

    mix = np.random.default_rng(3).normal(0, 0.1, (48000, 2)).astype(np.float32)
    with pytest.raises(TypeError, match="float samples"):
        master(mix, 48000, MasterProfile(),
               limiter=lambda m, sr, c: (m * 32767).astype(np.int16))


def test_an_unknown_meter_name_raises_everywhere():
    from foley.level import reference_gain_db
    from foley.qc import measure_lufs

    sr = 48000
    x = _sine_stereo(200, 1.0, sr, 0.1)
    for call in (
        lambda: measure_lufs(x, sr, meter="numpi"),
        lambda: master(x[: sr // 10], sr, MASTER_PROFILES["podcast"], meter="numpi"),
        lambda: reference_gain_db(x, sr, meter="numpi"),
        lambda: master(x, sr, MASTER_PROFILES["podcast"], meter="numpi"),
    ):
        with pytest.raises(ValueError, match="unknown meter"):
            call()
