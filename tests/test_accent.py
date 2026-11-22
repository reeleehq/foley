"""``foley.audio.accent``: the accent-ready clip step (foley#296)."""

import numpy as np
import pytest

pytest.importorskip("mixing.loudness")
pytest.importorskip("scipy")

from foley.audio import ACCENT_TARGET_LUFS, accent, integrated_lufs, onset_offset_s  # noqa: E402

SR = 48_000


def _hit(*, lead_s=0.3, ring_s=1.2, tau_s=0.15, tone_hz=220.0, amp=0.8, noise_db=-80.0, channels=None):
    """Silence (with a noise floor), then a struck tone that decays exponentially."""
    rng = np.random.default_rng(7)
    n_lead, n_ring = int(lead_s * SR), int(ring_s * SR)
    t = np.arange(n_ring) / SR
    ring = amp * np.exp(-t / tau_s) * np.sin(2 * np.pi * tone_hz * t + np.pi / 2)  # peak on its first sample
    x = np.concatenate([np.zeros(n_lead), ring]) + 10 ** (noise_db / 20) * rng.standard_normal(n_lead + n_ring)
    x = x.astype("float32")
    return np.stack([x, 0.5 * x], axis=1) if channels == 2 else x


def test_the_transient_lands_at_zero_to_the_sample():
    clip, report = accent(_hit(), SR)
    assert report.trimmed_start_s == pytest.approx(0.3, abs=1 / SR)  # the cut is at the transient
    # What the clip reports is measured on it: the 3 ms declick ramp holds its first
    # samples under the threshold, so the transient reads within the ramp, never later.
    assert 0.0 <= report.onset_s < 0.003
    assert onset_offset_s(clip, SR) == report.onset_s
    _clip, no_declick = accent(_hit(), SR, fade_in_s=0.0)
    assert no_declick.onset_s == 0.0


def test_pre_keeps_a_lead_in_before_the_transient():
    _clip, report = accent(_hit(), SR, pre_s=0.01)
    assert report.onset_s == pytest.approx(0.01, abs=1 / SR)
    assert report.trimmed_start_s == pytest.approx(0.29, abs=1 / SR)


def test_the_decay_is_kept_down_to_tail_db():
    tau = 0.15
    _clip, report = accent(_hit(tau_s=tau, noise_db=-140.0), SR)  # no floor to stretch the tail
    decays_to_50_db = tau * 50 / (20 * np.log10(np.e))  # exp(-t/tau) reaches -50 dB here
    assert report.duration_s == pytest.approx(decays_to_50_db, abs=0.003)  # one window
    _clip, shorter = accent(_hit(tau_s=tau), SR, tail_db=20.0)
    assert shorter.duration_s < report.duration_s


def test_a_long_clip_is_levelled_to_the_target():
    clip, report = accent(_hit(tau_s=0.3), SR)
    assert not report.lufs_padded
    assert report.lufs == pytest.approx(ACCENT_TARGET_LUFS, abs=0.1)
    assert integrated_lufs(clip.astype("float64"), SR) == pytest.approx(ACCENT_TARGET_LUFS, abs=0.1)


def test_a_one_shot_shorter_than_a_block_is_levelled_on_its_padded_loudness():
    clip, report = accent(_hit(tau_s=0.02, ring_s=0.2), SR, target_lufs=-30.0)
    assert clip.shape[0] / SR < 0.4
    assert report.lufs_padded
    assert report.lufs == pytest.approx(-30.0, abs=0.1)
    assert report.gain_db != 0.0


def test_the_peak_ceiling_holds_back_a_loud_target():
    _clip, report = accent(_hit(), SR, target_lufs=-3.0)
    assert report.peak_dbfs <= -3.0 + 1e-6
    assert report.lufs < -3.0


def test_max_len_caps_the_clip():
    _clip, report = accent(_hit(tau_s=0.5), SR, max_len_s=0.25)
    assert report.duration_s == pytest.approx(0.25, abs=1 / SR)


def test_multichannel_keeps_its_channels_and_a_silent_clip_is_left_alone():
    clip, _report = accent(_hit(channels=2), SR)
    assert clip.ndim == 2 and clip.shape[1] == 2
    silent = np.zeros(SR, dtype="float32")
    out, report = accent(silent, SR)
    assert out is silent or np.array_equal(out, silent)
    assert report.gain_db == 0.0 and report.peak_dbfs == float("-inf")
