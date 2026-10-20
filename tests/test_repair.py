"""Tests for ``foley.repair`` + ``foley.audio.limit_true_peak`` + ``foley.qc.is_below`` (#107).

numpy-only, synthesized at the working rate (no resample, no codec, no audio files).
The star fixture is the production's case: a one-shot with a flat-topped run that puts
its clipped ratio *just* over the 0.01 % gate, an edge click, and a true peak over the
ceiling — quarantined before, repaired now.
"""

import pytest

np = pytest.importorskip("numpy")

from foley.audio import limit_true_peak  # noqa: E402
from foley.qc import (  # noqa: E402
    DEFAULT_MIN_STATUS,
    DEFAULT_QC_THRESHOLDS as TH,
    QC_STATUS_RANK,
    QCStatus,
    is_below,
    run_qc,
    true_peak_dbtp,
)
from foley.repair import (  # noqa: E402
    DEFAULT_REPAIR_CEILING_DBTP,
    DEFAULT_REPAIR_FADE_S,
    DEFAULT_REPAIR_MAX_CLIPPED_RATIO,
    FIX_FADE,
    FIX_LIMIT,
    RepairResult,
    repair,
    suggested_fixes,
    unrepairable,
)

SR = 48_000


def _sine(seconds=1.0, *, amp=0.5, freq=1000.0):
    t = np.arange(int(round(seconds * SR))) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _cosine(seconds=1.0, *, amp=0.9, freq=1000.0):
    """Starts at its peak => an edge click."""
    t = np.arange(int(round(seconds * SR))) / SR
    return (amp * np.cos(2 * np.pi * freq * t)).astype(np.float32)


def _with_run(x, *, run, value=1.0):
    x = x.copy()
    mid = len(x) // 2
    x[mid : mid + run] = value
    return x


def just_over_the_gate():
    """The production's apple bite: ratio just over 0.01 %, an edge click, > -1 dBTP."""
    run = int(TH.clip_reject_ratio * SR) + 2  # 0.01 % of 1 s = 4.8 -> 6 samples (>= min_run)
    assert TH.clip_min_run <= run < TH.clip_reject_run
    return _with_run(_cosine(), run=run)


# ---------------------------------------------------------------------------
# qc: the shared status floor
# ---------------------------------------------------------------------------


def test_is_below_ranks_statuses_fail_closed():
    assert QC_STATUS_RANK["fail"] < QC_STATUS_RANK["warn"] < QC_STATUS_RANK["pass"]
    assert DEFAULT_MIN_STATUS is QCStatus.warn
    assert is_below(QCStatus.fail, QCStatus.warn) is True
    assert is_below("fail", "warn") is True
    assert is_below(QCStatus.warn, QCStatus.warn) is False
    assert is_below("pass", "fail") is False
    assert is_below("bogus", "warn") is True  # unknown ranks as fail


# ---------------------------------------------------------------------------
# audio.limit_true_peak — a static gain to a true-peak ceiling
# ---------------------------------------------------------------------------


def test_limit_true_peak_attenuates_a_hot_clip_to_the_ceiling():
    hot = _sine(amp=1.0)
    assert true_peak_dbtp(hot, SR) > TH.true_peak_max_dbtp
    out, gain_db = limit_true_peak(hot, SR)
    assert gain_db < 0.0
    assert true_peak_dbtp(out, SR) <= TH.true_peak_max_dbtp + 1e-6
    assert out.dtype == hot.dtype
    assert float(np.abs(out).max()) < TH.clip_full_scale


def test_limit_true_peak_leaves_a_quiet_or_silent_clip_untouched():
    quiet = _sine(amp=0.3)
    out, gain_db = limit_true_peak(quiet, SR)
    assert out is quiet and gain_db == 0.0
    silent = np.zeros(SR, dtype=np.float32)
    out, gain_db = limit_true_peak(silent, SR)
    assert out is silent and gain_db == 0.0


def test_limit_true_peak_honours_a_custom_ceiling_and_stereo():
    stereo = np.stack([_sine(amp=1.0), _sine(amp=0.2)], axis=1)  # (frames, 2)
    out, gain_db = limit_true_peak(stereo, SR, ceiling_dbtp=-6.0)
    assert out.shape == stereo.shape
    assert true_peak_dbtp(out, SR) <= -6.0 + 1e-6
    assert gain_db == pytest.approx(-6.0 - true_peak_dbtp(stereo, SR))


# ---------------------------------------------------------------------------
# repair — the policy
# ---------------------------------------------------------------------------


def test_the_production_case_is_quarantined_by_qc_and_cleared_by_repair():
    x = just_over_the_gate()
    before = run_qc(x, SR)
    assert before.status is QCStatus.fail
    assert TH.clip_reject_ratio < before.clipped_ratio <= DEFAULT_REPAIR_MAX_CLIPPED_RATIO
    assert before.needs_edge_fade and before.true_peak_dbtp > TH.true_peak_max_dbtp
    assert unrepairable(before) is None
    assert suggested_fixes(before) == [FIX_FADE, FIX_LIMIT]

    result = repair(x, SR)
    assert isinstance(result, RepairResult) and result.repaired
    assert result.before.status is QCStatus.fail and result.reason is None
    assert [a.split(" ")[0] for a in result.applied] == ["fade", "true"]
    assert f"{DEFAULT_REPAIR_FADE_S * 1000:.0f} ms" in result.applied[0]
    assert f"{DEFAULT_REPAIR_CEILING_DBTP:g} dBTP" in result.applied[1]
    after = result.after
    assert after is not None and after.status is not QCStatus.fail
    assert result.cleared() and result.cleared(QCStatus.warn)
    assert after.clipped_ratio == 0.0 and after.clipped_max_run == 0
    assert after.needs_edge_fade is False
    assert after.true_peak_dbtp <= TH.true_peak_max_dbtp
    assert float(np.abs(result.samples).max()) < TH.clip_full_scale
    assert result.samples.shape == x.shape and result.samples.dtype == x.dtype
    assert result.sample_rate == SR
    assert np.array_equal(x, just_over_the_gate())  # the input is not mutated


def test_repair_applies_only_the_fixes_the_report_names():
    # clipping only: a sine starts at zero, so no edge click => no fade
    x = _with_run(_sine(amp=0.5), run=6)
    result = repair(x, SR)
    assert result.repaired and len(result.applied) == 1
    assert result.applied[0].startswith("true peak attenuated")
    assert result.after.clipped_ratio == 0.0 and result.cleared()


def test_repair_accepts_a_precomputed_report_and_multichannel_input():
    mono = just_over_the_gate()
    stereo = np.stack([mono, 0.5 * mono], axis=1)
    report = run_qc(stereo, SR)
    result = repair(stereo, SR, report=report)
    assert result.before is report and result.repaired
    assert result.samples.shape == stereo.shape and result.cleared()


def test_repair_leaves_an_admitted_clip_alone():
    x = _sine(amp=0.5)  # a gapless tone: QC warn (low SNR), never quarantined
    result = repair(x, SR)
    assert not result.repaired and result.samples is x and result.after is None
    assert result.reason.startswith("QC warn: nothing to repair")
    assert result.cleared()


@pytest.mark.parametrize(
    "clip,why",
    [
        (np.zeros(SR, dtype=np.float32), "near-silent"),
        (_with_run(_sine(amp=0.5), run=1, value=np.nan), "NaN/Inf"),
        (_sine(TH.duration_min_s / 2, amp=0.5), "too short"),
    ],
)
def test_repair_refuses_what_a_fade_and_a_gain_cannot_fix(clip, why):
    result = repair(clip, SR)
    assert not result.repaired and result.samples is clip
    assert result.reason.startswith("not repairable: ") and why in result.reason
    assert not result.cleared()


def test_repair_refuses_heavy_clipping_as_distortion_not_a_run_over_the_gate():
    heavy = _with_run(_sine(amp=0.5), run=int(0.05 * SR))  # 5 % flat-topped
    before = run_qc(heavy, SR)
    assert before.clipped_ratio > DEFAULT_REPAIR_MAX_CLIPPED_RATIO
    assert "distortion" in unrepairable(before)
    result = repair(heavy, SR)
    assert not result.repaired and "distortion" in result.reason
    # ... unless the caller widens the bound on purpose
    widened = repair(heavy, SR, max_clipped_ratio=0.1)
    assert widened.repaired and widened.cleared()


def test_repair_knobs_are_keyword_arguments_with_named_defaults():
    x = just_over_the_gate()
    result = repair(x, SR, fade_s=0.05, ceiling_dbtp=-3.0)
    assert "50 ms" in result.applied[0] and "-3 dBTP" in result.applied[1]
    assert result.after.true_peak_dbtp <= -3.0 + 1e-6
    assert DEFAULT_REPAIR_MAX_CLIPPED_RATIO == pytest.approx(10 * TH.clip_reject_ratio)
