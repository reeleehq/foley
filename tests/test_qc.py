"""Tests for foley's Tier-0 deterministic audio QC (``foley.qc``).

numpy-only — no audio files, no ``soundfile``. Every fixture is a synthesized
array (clean tone, clipped run, DC-offset tone, silence, NaN/Inf, edge-click
tone, noisy tone). The loudness meter (``mixing.loudness``) is exercised when
present and skipped otherwise; ``run_qc`` is verified to still produce a report without it.
"""

import pytest

np = pytest.importorskip("numpy")  # noqa: E402 — QC tests synthesize numpy arrays

from foley.qc import (  # noqa: E402  (after importorskip, by design)
    DEFAULT_QC_THRESHOLDS,
    LUFS_MIN_BLOCK_S,
    QCReport,
    QCStatus,
    QCThresholds,
    _upsample_fft,
    detect_clipping,
    dc_offset,
    duration_s,
    estimate_snr,
    has_nan_inf,
    is_silent,
    measure_lufs,
    needs_edge_fade,
    run_qc,
    true_peak_dbtp,
)

SR = 48_000
TH = DEFAULT_QC_THRESHOLDS


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------


def _sine(seconds: float, *, freq: float = 1000.0, amp: float = 0.5) -> np.ndarray:
    """A plain continuous sine (starts at phase 0)."""
    t = np.arange(int(round(seconds * SR))) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _cosine(seconds: float, *, freq: float = 1000.0, amp: float = 0.8) -> np.ndarray:
    """A cosine — starts at its peak (``cos(0) == 1``) => edge click."""
    t = np.arange(int(round(seconds * SR))) / SR
    return (amp * np.cos(2 * np.pi * freq * t)).astype(np.float32)


def _clean_tone(seconds: float = 1.0, *, amp: float = 0.5) -> np.ndarray:
    """A clean, well-formed one-shot: a faded sine burst in the middle over a
    very low (1e-4) noise floor.

    The frame-based SNR estimate needs genuinely quiet regions to read a noise
    floor, so a *gapless* pure tone would score ~0 dB SNR. This windowed burst
    with a realistic low floor is the honest "clean clip" fixture: high SNR, no
    edge click, no clipping, no DC, not silent => PASS.
    """
    n = int(round(seconds * SR))
    rng = np.random.default_rng(0)
    x = (1e-4 * rng.standard_normal(n)).astype(np.float32)  # low noise floor
    start, end = int(0.2 * SR), int(0.8 * SR)
    t = np.arange(end - start) / SR
    burst = (amp * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    fade = int(round(TH.edge_fade_s * SR))
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    burst[:fade] *= ramp
    burst[-fade:] *= ramp[::-1]
    x[start:end] += burst
    return x


def _clipped(seconds: float = 1.0, *, run: int = 20) -> np.ndarray:
    """A sine with a flat-topped full-scale run of ``run`` samples (hard clip)."""
    x = _sine(seconds, amp=0.5)
    mid = len(x) // 2
    x[mid : mid + run] = 1.0
    return x


# ---------------------------------------------------------------------------
# Per-check functions
# ---------------------------------------------------------------------------


def test_has_nan_inf():
    clean = _sine(0.5)
    assert has_nan_inf(clean) is False
    with_nan = clean.copy()
    with_nan[10] = np.nan
    assert has_nan_inf(with_nan) is True
    with_inf = clean.copy()
    with_inf[10] = np.inf
    assert has_nan_inf(with_inf) is True


def test_duration_s():
    assert duration_s(np.zeros(SR, dtype=np.float32), SR) == 1.0
    assert duration_s(np.zeros(SR // 2, dtype=np.float32), SR) == pytest.approx(0.5)


def test_dc_offset():
    sine = _sine(1.0)
    assert dc_offset(sine) == pytest.approx(0.0, abs=1e-3)
    assert dc_offset(sine + 0.05) == pytest.approx(0.05, abs=1e-3)


def test_dc_offset_multichannel_takes_max():
    sine = _sine(1.0)
    stereo = np.stack([sine, sine + 0.05], axis=1)  # (frames, 2)
    assert dc_offset(stereo) == pytest.approx(0.05, abs=1e-3)


def test_is_silent():
    assert is_silent(np.zeros(SR, dtype=np.float32)) is True
    assert is_silent(_sine(1.0)) is False


def test_detect_clipping_flags_long_run():
    ratio, max_run = detect_clipping(_clipped(run=20))
    assert max_run >= TH.clip_reject_run
    assert ratio > 0.0


def test_detect_clipping_clean_sine_is_clean():
    ratio, max_run = detect_clipping(_sine(1.0, amp=0.5))
    assert (ratio, max_run) == (0.0, 0)


def test_detect_clipping_short_runs_ignored():
    # A single isolated full-scale sample (< clip_min_run) is not a clip event.
    x = np.zeros(SR, dtype=np.float32)
    x[100] = 1.0
    assert detect_clipping(x) == (0.0, 0)


def test_needs_edge_fade_true_for_peak_start_false_after_fade():
    tone = _cosine(0.5)  # starts at peak
    assert needs_edge_fade(tone) is True

    faded = tone.copy()
    fade = int(round(TH.edge_fade_s * SR))
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    faded[:fade] *= ramp
    faded[-fade:] *= ramp[::-1]
    assert needs_edge_fade(faded) is False


def test_estimate_snr_clean_higher_than_noisy():
    clean = _clean_tone()
    rng = np.random.default_rng(1)
    noisy = clean + (0.02 * rng.standard_normal(clean.shape)).astype(np.float32)
    assert estimate_snr(clean, SR) > estimate_snr(noisy, SR)


def test_true_peak_dbtp_is_finite_for_sine():
    tp = true_peak_dbtp(_sine(0.5, amp=0.5), SR)
    assert np.isfinite(tp)
    # a -6 dBFS sine's inter-sample true peak is comfortably below full scale
    assert tp < 0.0


def test_true_peak_dbtp_silence_is_neg_inf():
    assert true_peak_dbtp(np.zeros(SR, dtype=np.float32), SR) == float("-inf")


def test_upsample_fft_does_not_over_report_nyquist():
    # A full-scale Nyquist tone (alternating +1/-1, even length) reconstructs to
    # a cosine whose true peak is 1.0 (the samples ARE the peaks). Zero-pad FFT
    # upsampling double-counts the even-n Nyquist bin unless it is halved — the
    # bug this guards against inflated the peak to ~2.0 (+6 dB).
    x = np.array([1.0, -1.0] * 8, dtype=np.float64)  # n=16 (even)
    up = _upsample_fft(x, 4)
    assert float(np.max(np.abs(up))) <= 1.0 + 1e-6  # was ~2.0 before the fix


def test_upsample_fft_preserves_midband_peak():
    # A tone well below Nyquist must be unaffected by the Nyquist-bin correction.
    t = np.arange(64)
    mid = np.sin(2.0 * np.pi * 8 * t / 64)  # bin 8 of 64 — mid-band
    up = _upsample_fft(mid, 4)
    assert abs(float(np.max(np.abs(up))) - 1.0) <= 1e-6


def test_true_peak_dbtp_nyquist_tone_not_over_reported():
    # End-to-end: the public metric must not report a Nyquist tone as > +6 dBFS.
    x = np.array([1.0, -1.0] * (SR // 2), dtype=np.float32)  # 1 s Nyquist tone
    tp = true_peak_dbtp(x, SR)
    assert tp <= 0.5  # ~0 dBFS true peak; was ~+6 dBFS before the fix


# ---------------------------------------------------------------------------
# measure_lufs (optional dependency)
# ---------------------------------------------------------------------------


def test_measure_lufs_when_available():
    pytest.importorskip("mixing.loudness")
    lufs = measure_lufs(_sine(1.0, amp=0.5), SR)
    assert lufs is not None
    assert isinstance(lufs, float)
    assert np.isfinite(lufs)


def test_measure_lufs_none_for_too_short_clip():
    pytest.importorskip("mixing.loudness")
    short = _sine(LUFS_MIN_BLOCK_S / 2, amp=0.5)  # < one gating block
    assert measure_lufs(short, SR) is None


# ---------------------------------------------------------------------------
# run_qc — the orchestrator and its status rules
# ---------------------------------------------------------------------------


def test_run_qc_pass_on_clean_tone():
    report = run_qc(_clean_tone(), SR)
    assert isinstance(report, QCReport)
    assert report.status is QCStatus.pass_
    assert report.notes == []
    assert report.channels == 1
    assert report.duration_s == pytest.approx(1.0)
    assert report.has_nan_inf is False
    assert report.is_silent is False


def test_run_qc_fail_on_clipping():
    report = run_qc(_clipped(run=20), SR)
    assert report.status is QCStatus.fail
    assert report.clipped_max_run >= TH.clip_reject_run
    assert report.notes  # non-empty


def test_run_qc_fail_on_silence():
    report = run_qc(np.zeros(SR, dtype=np.float32), SR)
    assert report.status is QCStatus.fail
    assert report.is_silent is True
    assert report.notes


def test_run_qc_fail_on_nan():
    x = _sine(1.0)
    x[123] = np.nan
    report = run_qc(x, SR)
    assert report.status is QCStatus.fail
    assert report.has_nan_inf is True
    assert report.notes


def test_run_qc_fail_on_too_short():
    short = _sine(TH.duration_min_s / 2, amp=0.5)  # < duration_min_s
    report = run_qc(short, SR)
    assert report.status is QCStatus.fail
    assert report.duration_s < TH.duration_min_s
    assert report.notes


def test_run_qc_warn_on_dc_offset():
    report = run_qc(_clean_tone() + 0.05, SR)  # DC 0.05 > dc_offset_fail (0.01)
    assert report.status is QCStatus.warn
    assert report.dc_offset > TH.dc_offset_fail
    assert any("DC" in note for note in report.notes)


def test_run_qc_notes_minor_dc_offset():
    # DC in the note band (dc_offset_warn < dc <= dc_offset_fail) emits an
    # advisory note — i.e. the dc_offset_warn threshold is actually consulted —
    # distinct from the louder dc_offset_fail "high-pass/correct" warning.
    dc = (TH.dc_offset_warn + TH.dc_offset_fail) / 2  # ~0.0055, inside the band
    report = run_qc(_clean_tone() + dc, SR)
    assert TH.dc_offset_warn < report.dc_offset <= TH.dc_offset_fail
    assert any("minor DC offset" in note for note in report.notes)
    assert not any("high-pass/correct" in note for note in report.notes)


def test_run_qc_handles_missing_lufs(monkeypatch):
    # Simulate the loudness meter being unavailable: run_qc must still produce a report.
    import foley.qc as qc

    monkeypatch.setattr(qc, "measure_lufs", lambda *a, **k: None)
    report = qc.run_qc(_clean_tone(), SR)
    assert report.loudness_lufs is None
    assert report.status is QCStatus.pass_


def test_qc_report_to_dict_is_json_safe():
    report = run_qc(_clean_tone(), SR)
    d = report.to_dict()
    assert d["status"] == "pass"  # enum -> string value
    assert isinstance(d["status"], str)
    # round-trips through json without a custom encoder
    import json

    reloaded = json.loads(json.dumps(d))
    assert reloaded["status"] == "pass"


def _assert_strict_json(report):
    # allow_nan=False raises on exactly the tokens Postgres JSONB / JS JSON.parse
    # reject (Infinity / -Infinity / NaN) — the precise regression oracle.
    import json

    d = report.to_dict()
    json.dumps(d, allow_nan=False)
    assert json.loads(json.dumps(d)) == d  # round-trips


def test_json_safe_unit():
    from foley.qc import _json_safe

    assert _json_safe(float("inf")) is None
    assert _json_safe(float("-inf")) is None
    assert _json_safe(float("nan")) is None
    assert _json_safe(None) is None
    assert _json_safe(-3.5) == -3.5


def test_qc_report_json_safe_for_silent_clip():
    # a fully silent clip: rms_dbfs -> -inf, snr_db -> -inf; both clamp to None.
    report = run_qc(np.zeros(SR, dtype=np.float32), SR)
    assert report.is_silent and report.status is QCStatus.fail
    assert report.rms_dbfs is None and report.snr_db is None
    assert report.true_peak_dbtp is None and report.loudness_lufs is None
    _assert_strict_json(report)


def test_qc_report_json_safe_for_zero_padded_one_shot():
    # a short burst padded with exact zeros: estimate_snr's noise floor is 0 =>
    # snr_db is +inf; it clamps to None while rms_dbfs stays finite.
    padded = np.concatenate(
        [_sine(0.1, amp=0.5), np.zeros(int(0.9 * SR), dtype=np.float32)]
    ).astype(np.float32)
    report = run_qc(padded, SR)
    assert report.snr_db is None  # +inf clamped
    assert report.rms_dbfs is not None  # signal present => finite
    _assert_strict_json(report)


def test_custom_thresholds_are_honored():
    # Tightening the silence floor upward can flip a quiet clip to "silent".
    quiet = _sine(1.0, amp=0.5) * 1e-3  # ~ -69 dBFS RMS
    lenient = run_qc(quiet, SR, thresholds=QCThresholds(silence_rms_dbfs=-80.0))
    strict = run_qc(quiet, SR, thresholds=QCThresholds(silence_rms_dbfs=-40.0))
    assert lenient.is_silent is False
    assert strict.is_silent is True
    assert strict.status is QCStatus.fail


def test_measure_lufs_is_the_audio_meter_with_none_contract():
    import numpy as np

    from foley import audio
    from foley.qc import measure_lufs

    sr = 48000
    x = (0.1 * np.sin(2 * np.pi * 300 * np.arange(sr * 2) / sr)).astype("float64")
    assert measure_lufs(x, sr) == pytest.approx(audio.integrated_lufs(x, sr))
    assert measure_lufs(x, sr, meter=lambda s, r: -25.0) == -25.0
    assert measure_lufs(x[: sr // 10], sr) is None  # shorter than a gating block
    assert measure_lufs(x, sr, meter=lambda s, r: -90.0) is None  # at/below the gate floor
    bad = x.copy()
    bad[5] = np.nan
    assert measure_lufs(bad, sr) is None
    six = np.tile(x[:, None], (1, 6))  # the numpy meter reads any channel count
    assert measure_lufs(six, sr) == pytest.approx(audio.integrated_lufs(six, sr))

    def unreadable(samples, rate):  # e.g. pyloudnorm on more than five channels
        raise ValueError("unsupported layout")

    assert measure_lufs(six, sr, meter=unreadable) is None
