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
    mix = np.stack([_transient_program(sr)] * 2, axis=1) * np.float32(1.5)  # over
    out = lookahead_true_peak_limit(mix, sr, -1.0)
    bed = _bed_mask(sr, len(mix))
    bed_gain_db = 20 * np.log10(np.abs(out[bed]).max() / np.abs(mix[bed]).max())
    assert abs(bed_gain_db) < 0.05  # only the hits were turned down
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


def test_lookahead_limiter_does_not_spread_a_nan():
    from foley.weave.master import lookahead_true_peak_limit

    sr = 48000
    mix = _sine_stereo(200, 1.0, sr, 0.99) * np.float32(1.5)
    mix[100, 0] = np.nan
    assert lookahead_true_peak_limit(mix, sr, -1.0) is mix


def test_near_nyquist_residual_is_limited_then_trimmed():
    # On full-band content mixing's polyphase meter reads under foley's FFT one: the
    # lookahead stage must hold mixing's ceiling, and the trim the (bounded) rest.
    from mixing.loudness import limit_peaks, true_peak_db

    from foley.qc import true_peak_dbtp
    from foley.weave.master import lookahead_true_peak_limit

    sr = 48000
    noise = np.random.default_rng(1).normal(0, 0.3, (sr * 2, 1)).clip(-1, 1)
    ceiling = 10 ** (-1.0 / 20)
    stage = limit_peaks(noise, ceiling=ceiling, true_peak=True, fs=sr)
    assert true_peak_db(stage, sr) <= -1.0 + 0.01
    out = lookahead_true_peak_limit(noise, sr, -1.0)
    assert true_peak_dbtp(out, sr) <= -1.0 + 1e-6
    trim_db = 20 * np.log10(np.abs(out).max() / np.abs(stage).max())
    assert -1.5 < trim_db <= 0.0


def test_an_unknown_meter_name_raises_everywhere():
    from foley.level import reference_gain_db
    from foley.qc import measure_lufs

    sr = 48000
    x = _sine_stereo(200, 1.0, sr, 0.1)
    for call in (
        lambda: measure_lufs(x, sr, meter="numpi"),
        lambda: reference_gain_db(x, sr, meter="numpi"),
        lambda: master(x, sr, MASTER_PROFILES["podcast"], meter="numpi"),
    ):
        with pytest.raises(ValueError, match="unknown meter"):
            call()
