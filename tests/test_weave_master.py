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
    """A quiet bed with a few loud, noisy hits: what a lookahead limiter is for."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs * sr)) / sr
    x = 0.05 * np.sin(2 * np.pi * 440 * t) + 0.02 * rng.normal(size=len(t))
    hit = 0.9 * np.exp(-np.arange(2400) / 300)
    for k in range(1, int(secs) - 1):
        x[k * sr : k * sr + 2400] += hit * rng.normal(size=2400)
    return np.clip(x, -1, 1).astype("float32")


def test_lookahead_limiter_turns_down_only_the_peaks():
    from foley.qc import true_peak_dbtp
    from foley.weave.master import _true_peak_trim, lookahead_true_peak_limit

    sr = 48000
    mix = np.stack([_transient_program(sr)] * 2, axis=1)
    _, static = master(mix, sr, MASTER_PROFILES["podcast"], limiter=_true_peak_trim)
    limited, report = master(mix, sr, MASTER_PROFILES["podcast"])
    assert report.limited is True
    assert report.true_peak_dbtp <= -1.0 + 1e-6  # by the report's own meter
    assert report.output_lufs > static.output_lufs + 0.5  # the bed is not turned down
    assert limited.dtype == mix.dtype and limited.shape == mix.shape
    mono = _transient_program(sr)
    out = lookahead_true_peak_limit(mono, sr, -1.0)
    assert out.shape == mono.shape and out.dtype == mono.dtype
    assert true_peak_dbtp(out, sr) <= -1.0 + 1e-6


def test_lookahead_limiter_returns_an_unclipped_mix_as_is():
    from foley.weave.master import lookahead_true_peak_limit

    sr = 48000
    quiet = _sine_stereo(200, 1.0, sr, 0.1)
    assert lookahead_true_peak_limit(quiet, sr, -1.0) is quiet
    mono = quiet[:, 0]
    assert lookahead_true_peak_limit(mono, sr, -1.0) is mono


def test_master_true_peak_holds_on_near_nyquist_content():
    # mixing's polyphase true-peak meter reads under foley's FFT one up here; the
    # static residual trim keeps the reported ceiling honest.
    from foley.weave.master import lookahead_true_peak_limit
    from foley.qc import true_peak_dbtp

    sr = 48000
    noise = np.random.default_rng(1).normal(0, 0.3, sr * 2).clip(-1, 1)
    out = lookahead_true_peak_limit(noise.astype("float32"), sr, -1.0)
    assert true_peak_dbtp(out, sr) <= -1.0 + 1e-6
