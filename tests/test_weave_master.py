"""WEAVE mastering — LUFS target + true-peak ceiling on synth signals."""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyloudnorm")

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
    _, report = master(_sine_stereo(200, 3.0, sr, 0.05), sr, MASTER_PROFILES["streaming"])
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
