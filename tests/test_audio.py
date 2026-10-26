"""Tests for foley's audio I/O + DSP primitives (``foley.audio``).

Strategy (testing-trophy: cheap, stable, numpy-only where possible):

    * Most checks synthesize arrays directly and exercise pure numpy paths
      (``to_mono``, ``ensure_channels``, ``fade``) with no optional dependency.
    * DSP that wraps an optional library is guarded with
      ``pytest.importorskip`` (``soxr`` for resample, ``librosa`` for trim,
      ``pyloudnorm`` for loudness).
    * File-codec round-trips (``encode``/``save``/``load``) additionally carry
      the ``audiofile`` marker and ``importorskip('soundfile')`` so a lean env
      skips them cleanly.

``foley.audio`` itself imports with the stdlib only, so importing it never needs
any of these libraries.
"""

import pytest

np = pytest.importorskip("numpy")

from foley import audio  # noqa: E402  (after importorskip, by design)


# ---------------------------------------------------------------------------
# Fixtures / synthesis helpers
# ---------------------------------------------------------------------------


def _sine(*, freq: float = 440.0, sr: int = 48_000, dur: float = 1.0, amp: float = 0.5):
    """A mono float32 sine — the canonical working-array shape."""
    t = np.linspace(0.0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _stereo(**kw):
    """A 2-channel (frames, 2) float32 array (time on axis 0)."""
    mono = _sine(**kw)
    return np.stack([mono, mono], axis=1)


# ---------------------------------------------------------------------------
# Module imports with stdlib only (no heavy deps needed to import)
# ---------------------------------------------------------------------------


def test_module_constants_are_named_not_magic():
    assert audio.WORKING_SAMPLE_RATE == 48_000
    assert audio.WORKING_DTYPE == "float32"
    assert audio.ARCHIVE_FORMAT == "flac"
    assert audio.DEFAULT_LOUDNESS_TARGET_LUFS == audio.LUFS_PODCAST
    assert audio.LUFS_GATE_FLOOR == -70.0


# ---------------------------------------------------------------------------
# resample (soxr)
# ---------------------------------------------------------------------------


def test_resample_halves_length():
    pytest.importorskip("soxr")
    y = _sine(sr=48_000, dur=1.0)
    out = audio.resample(y, 48_000, target_sr=24_000)
    assert abs(out.shape[0] - y.shape[0] // 2) <= 2
    assert out.dtype == np.float32


def test_resample_noop_when_rate_matches():
    # No soxr needed on the no-op path (returns the input unchanged).
    y = _sine()
    out = audio.resample(y, 48_000, target_sr=48_000)
    assert out is y


# ---------------------------------------------------------------------------
# channel ops (numpy only)
# ---------------------------------------------------------------------------


def test_to_mono_downmixes_stereo():
    stereo = _stereo(dur=0.25)
    mono = audio.to_mono(stereo)
    assert mono.ndim == 1
    assert mono.shape[0] == stereo.shape[0]


def test_to_mono_passes_through_1d():
    mono = _sine(dur=0.25)
    assert audio.to_mono(mono) is mono


def test_ensure_channels_up_and_down():
    mono = _sine(dur=0.25)
    stereo = audio.ensure_channels(mono, channels=2)
    assert stereo.shape == (mono.shape[0], 2)
    # duplicated identical channels
    assert np.array_equal(stereo[:, 0], stereo[:, 1])
    back = audio.ensure_channels(stereo, channels=1)
    assert back.ndim == 1
    assert back.shape[0] == mono.shape[0]


def test_ensure_channels_same_count_is_passthrough():
    stereo = _stereo(dur=0.1)
    assert audio.ensure_channels(stereo, channels=2) is stereo


def test_ensure_channels_remaps_n_to_m():
    # N -> M (N != M, both > 1): collapse to mono then tile up to M. Here 3ch->2ch.
    mono = _sine(dur=0.1)
    three = np.stack([mono, mono * 0.5, mono * 0.25], axis=1)
    assert three.shape[1] == 3
    two = audio.ensure_channels(three, channels=2)
    assert two.shape == (mono.shape[0], 2)
    # both output channels are the same mono down-mix (tiled), by construction
    assert np.array_equal(two[:, 0], two[:, 1])
    expected_mono = three.mean(axis=1)
    assert np.allclose(two[:, 0], expected_mono)


def test_ensure_channels_rejects_zero():
    with pytest.raises(ValueError):
        audio.ensure_channels(_sine(dur=0.1), channels=0)


# ---------------------------------------------------------------------------
# fade (numpy only)
# ---------------------------------------------------------------------------


def test_fade_zeros_edges_keeps_interior():
    sr = 48_000
    y = np.ones(sr, dtype=np.float32)
    out = audio.fade(y, sr, fade_in_s=0.01, fade_out_s=0.01)
    assert abs(float(out[0])) < 1e-6
    assert abs(float(out[-1])) < 1e-6
    # interior well past a 10 ms (480-sample) ramp is untouched
    assert float(out[sr // 2]) == pytest.approx(1.0)
    # input not mutated
    assert float(y[0]) == 1.0


def test_fade_clamps_ramps_on_tiny_input():
    y = np.ones(10, dtype=np.float32)
    out = audio.fade(y, 48_000, fade_in_s=0.01, fade_out_s=0.01)
    assert out.shape == y.shape
    assert float(out[0]) == pytest.approx(0.0)
    assert float(out[-1]) == pytest.approx(0.0)


def test_fade_equal_power_is_sqrt_of_linear():
    sr = 48_000
    y = np.ones(sr, dtype=np.float32)
    n = int(0.02 * sr)
    lin = audio.fade(y, sr, fade_in_s=0.02, fade_out_s=0.0, kind="linear")
    eqp = audio.fade(y, sr, fade_in_s=0.02, fade_out_s=0.0, kind="equal_power")
    # equal-power ramp sits above the linear ramp everywhere in (0, 1)
    mid = n // 2
    assert eqp[mid] == pytest.approx(np.sqrt(lin[mid]), rel=1e-4)


def test_fade_preserves_channel_shape():
    stereo = np.ones((48_000, 2), dtype=np.float32)
    out = audio.fade(stereo, 48_000, fade_in_s=0.01, fade_out_s=0.01)
    assert out.shape == stereo.shape
    assert np.allclose(out[0], 0.0)
    assert np.allclose(out[-1], 0.0)


# ---------------------------------------------------------------------------
# trim_silence (librosa)
# ---------------------------------------------------------------------------


def test_trim_silence_removes_pads():
    pytest.importorskip("librosa")
    sr = 48_000
    pad = np.zeros(int(0.2 * sr), dtype=np.float32)
    sig = _sine(sr=sr, dur=0.5, amp=0.5)
    y = np.concatenate([pad, sig, pad])
    trimmed, (start, end) = audio.trim_silence(y, sr, top_db=30.0)
    assert trimmed.shape[0] < y.shape[0]
    assert start > 0
    assert end <= y.shape[0]


def test_trim_silence_all_silent_unchanged():
    pytest.importorskip("librosa")
    sr = 48_000
    y = np.zeros(sr, dtype=np.float32)
    trimmed, span = audio.trim_silence(y, sr)
    assert span == (0, y.shape[0])
    assert trimmed.shape[0] == y.shape[0]


def test_trim_silence_preserves_channels():
    pytest.importorskip("librosa")
    sr = 48_000
    pad = np.zeros((int(0.2 * sr), 2), dtype=np.float32)
    sig = _stereo(sr=sr, dur=0.5, amp=0.5)
    y = np.concatenate([pad, sig, pad], axis=0)
    trimmed, _ = audio.trim_silence(y, sr, top_db=30.0)
    assert trimmed.ndim == 2
    assert trimmed.shape[1] == 2
    assert trimmed.shape[0] < y.shape[0]


# ---------------------------------------------------------------------------
# loudness_normalize (pyloudnorm)
# ---------------------------------------------------------------------------


def test_loudness_normalize_near_silent_unchanged():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = np.zeros(sr, dtype=np.float32)
    out, measured = audio.loudness_normalize(y, sr)
    assert out is y  # returned unchanged (flag, don't amplify)
    assert measured <= audio.LUFS_GATE_FLOOR


def test_loudness_normalize_scales_quiet_sine():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=2.0, amp=0.1)  # >= 0.4 s so the meter is valid
    out, measured = audio.loudness_normalize(y, sr, target_lufs=audio.LUFS_PODCAST)
    assert out.shape == y.shape
    assert np.isfinite(measured)
    assert measured > audio.LUFS_GATE_FLOOR
    # a quiet input is boosted toward the target => it actually changed
    assert not np.allclose(out, y)


def test_loudness_normalize_respects_true_peak_ceiling():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=2.0, amp=0.05)
    out, _ = audio.loudness_normalize(y, sr, peak_ceiling_dbfs=audio.TRUE_PEAK_MAX_DBTP)
    ceiling = 10.0 ** (audio.TRUE_PEAK_MAX_DBTP / 20.0)
    assert float(np.max(np.abs(out))) <= ceiling + 1e-6


def test_loudness_normalize_short_clip_returns_unchanged():
    # A clip shorter than one BS.1770 gating block (0.4 s) cannot be measured;
    # pyloudnorm would raise. It must be returned unchanged, flagged -inf — this
    # is routine for one-shots (clicks, blips, gunshots).
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=0.1, amp=0.5)  # 0.1 s < 0.4 s
    out, measured = audio.loudness_normalize(y, sr)
    assert out is y  # unchanged (no scaling, no exception)
    assert measured == float("-inf")


def test_loudness_normalize_guard_mirrors_pyloudnorm_at_fractional_boundary():
    # At a sample rate where 0.4*sr is NOT integral (0.4*10001 = 4000.4), a clip
    # of exactly 4000 samples is one below pyloudnorm's block threshold and would
    # raise ValueError. The math.ceil guard must catch it (int(round) would not).
    pyln = pytest.importorskip("pyloudnorm")
    sr = 10_001
    y = np.zeros(4000, dtype=np.float32)  # 4000 < ceil(4000.4)=4001 => too short
    # sanity: pyloudnorm really does raise on this clip (so the guard is load-bearing)
    with pytest.raises(Exception):
        pyln.Meter(sr).integrated_loudness(y.astype(np.float64))
    out, measured = audio.loudness_normalize(y, sr)  # must NOT raise
    assert out is y
    assert measured == float("-inf")


# ---------------------------------------------------------------------------
# to_working (soxr for the resample leg)
# ---------------------------------------------------------------------------


def test_to_working_downmixes_resamples_and_casts():
    pytest.importorskip("soxr")
    sr = 44_100
    stereo = _stereo(sr=sr, dur=0.5)
    work = audio.to_working(stereo, sr)
    assert work.ndim == 1  # mono
    assert str(work.dtype) == audio.WORKING_DTYPE
    assert abs(work.shape[0] - int(0.5 * audio.WORKING_SAMPLE_RATE)) <= 3


# ---------------------------------------------------------------------------
# file-codec round-trips (soundfile) — carry the audiofile marker
# ---------------------------------------------------------------------------


@pytest.mark.audiofile
def test_encode_then_load_roundtrip():
    pytest.importorskip("soundfile")
    sr = 48_000
    y = _sine(sr=sr, dur=0.5, amp=0.5)
    blob = audio.encode(y, sr)
    assert isinstance(blob, (bytes, bytearray))
    assert len(blob) > 0
    y2, sr2 = audio.load(blob)
    assert sr2 == sr
    assert y2.shape[0] == y.shape[0]
    # FLAC PCM_24 is lossless to well under this tolerance
    assert np.allclose(y2, y, atol=1e-3)


@pytest.mark.audiofile
def test_save_then_load_roundtrip(tmp_path):
    pytest.importorskip("soundfile")
    sr = 48_000
    y = _sine(sr=sr, dur=0.5, amp=0.5)
    path = tmp_path / "clip.flac"
    audio.save(y, sr, str(path))
    assert path.exists()
    y2, sr2 = audio.load(str(path))
    assert sr2 == sr
    assert np.allclose(y2, y, atol=1e-3)


@pytest.mark.audiofile
def test_load_can_resample_and_downmix_on_read(tmp_path):
    pytest.importorskip("soundfile")
    pytest.importorskip("soxr")
    sr = 44_100
    stereo = _stereo(sr=sr, dur=0.5)
    path = tmp_path / "stereo.flac"
    audio.save(stereo, sr, str(path))
    y, out_sr = audio.load(str(path), target_sr=48_000, mono=True)
    assert out_sr == 48_000
    assert y.ndim == 1
    assert abs(y.shape[0] - int(0.5 * 48_000)) <= 3


# ---------------------------------------------------------------------------
# loudness_gain_db: the one rule loudness_normalize and reference_gain_db share
# ---------------------------------------------------------------------------


def test_loudness_gain_db_lands_a_quiet_clip_on_target():
    pyln = pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=2.0, amp=0.01)
    gain, measured = audio.loudness_gain_db(y, sr, target_lufs=-30.0)
    after = pyln.Meter(sr).integrated_loudness(y.astype(np.float64) * 10 ** (gain / 20))
    assert after == pytest.approx(-30.0, abs=0.05)
    assert gain == pytest.approx(-30.0 - measured)


def test_loudness_gain_db_holds_a_high_crest_clip_at_the_ceiling():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=1.0, amp=0.01)
    y[sr // 2] = 0.9  # a spike: boosting to the target would clip it
    gain, _ = audio.loudness_gain_db(y, sr, target_lufs=audio.LUFS_PODCAST)
    assert gain == pytest.approx(audio.TRUE_PEAK_MAX_DBTP - 20 * np.log10(0.9), abs=1e-4)


def test_loudness_gain_db_caps_the_boost():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=1.0, amp=0.001)
    gain, _ = audio.loudness_gain_db(y, sr, target_lufs=-16.0, max_boost_db=6.0)
    assert gain == 6.0


def test_loudness_gain_db_gate_floor_is_a_keyword():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=1.0, amp=0.05)
    _, measured = audio.loudness_gain_db(y, sr, target_lufs=-16.0)
    assert audio.loudness_gain_db(
        y, sr, target_lufs=-16.0, gate_floor_lufs=measured + 1.0
    ) == (0.0, pytest.approx(measured))


def test_loudness_gain_db_short_clip_policy_is_one_switch():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    y = _sine(sr=sr, dur=0.1, amp=0.5)
    assert audio.loudness_gain_db(y, sr, target_lufs=-16.0) == (0.0, float("-inf"))
    gain, measured = audio.loudness_gain_db(
        y, sr, target_lufs=-16.0, short_peak_dbfs=-6.0
    )
    assert measured == float("-inf")
    assert 20 * np.log10(0.5) + gain == pytest.approx(-6.0)


def test_loudness_gain_db_leaves_silent_and_non_finite_clips_alone():
    pytest.importorskip("pyloudnorm")
    sr = 48_000
    assert audio.loudness_gain_db(np.zeros(sr), sr, target_lufs=-16.0)[0] == 0.0
    assert audio.loudness_gain_db(np.full(sr, np.nan), sr, target_lufs=-16.0)[0] == 0.0


def test_injected_meter_drives_gain_and_short_guard_stays_outside_it():
    import numpy as np

    sr = 48000
    x = (0.05 * np.sin(2 * np.pi * 200 * np.arange(sr * 2) / sr)).astype("float64")
    gain, measured = audio.loudness_gain_db(x, sr, target_lufs=-20.0, meter=lambda s, r: -30.0)
    assert measured == -30.0 and gain == pytest.approx(10.0)
    called = []
    short = x[: sr // 10]  # under one gating block
    assert audio.integrated_lufs(short, sr, meter=lambda s, r: called.append(1) or 0.0) == float("-inf")
    assert called == []
    out, m = audio.loudness_normalize(x, sr, target_lufs=-20.0, meter=lambda s, r: -30.0)
    assert m == -30.0 and float(np.max(np.abs(out))) > float(np.max(np.abs(x)))
