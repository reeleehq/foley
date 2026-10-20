"""Repair instead of quarantine: the fixes a Tier-0 QC report suggests, applied and re-checked (#107).

A paid generation (or any clip) that :func:`foley.qc.run_qc` would quarantine for a
*trivially repairable* fault — a clipped run just over the gate, an edge click, a true
peak over the ceiling — is worth a 20 ms fade and a true-peak attenuation more than it
is worth the bin: the bytes were paid for. :func:`repair` applies exactly the fixes the
report names, with foley's own numpy primitives (:func:`foley.audio.fade`,
:func:`foley.audio.limit_true_peak`), runs QC again on the result the way ingest will
(:func:`foley.audio.to_working` then :func:`foley.qc.run_qc`), and says what it did.
What it cannot fix it leaves alone, and says why (:func:`unrepairable`): NaN/Inf,
silence, a too-short clip, or clipping heavy enough to be distortion rather than a run
just over the gate.

:func:`foley.generate` runs this by default (``repair=True``) on a generation QC would
quarantine; ``repair=False`` keeps the quarantine, and a callable with this function's
signature replaces the policy (an ffmpeg ``afade`` + ``alimiter`` repair, say). Every
repair is recorded on the candidate's ``notes`` and in the licence's ``transformations``,
so the credit reads "(modified)" and the content credential carries an edit action.

Zero-dependency import: stdlib only at the top level; ``numpy`` (and ``soxr`` when the
clip is not at the working rate) load inside :func:`repair`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .qc import (
    DEFAULT_MIN_STATUS,
    DEFAULT_QC_THRESHOLDS,
    QCReport,
    QCStatus,
    QCThresholds,
    is_below,
    run_qc,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: The declick fade applied to an edge click: 20 ms, the upper end of the 10-20 ms the
#: QC note asks for (the Tier-0 ``edge_fade_s`` floor is 10 ms).
DEFAULT_REPAIR_FADE_S: float = 0.02

#: Where the true-peak attenuation lands: 0.5 dB under foley's -1 dBTP ceiling, so the
#: re-check never sits on the threshold (the production's ffmpeg repair used
#: ``alimiter=limit=0.85``, about -1.4 dB).
DEFAULT_REPAIR_CEILING_DBTP: float = -1.5

#: A clipped ratio above this is distortion, not "just over the gate": ten times the
#: reject gate (``QCThresholds.clip_reject_ratio``, 0.01 %). Attenuating such a clip
#: would make it pass the range check while its flat tops stay audible, so it is left
#: to the quarantine (regenerate instead).
DEFAULT_REPAIR_MAX_CLIPPED_RATIO: float = 10 * DEFAULT_QC_THRESHOLDS.clip_reject_ratio

#: The fix names :func:`suggested_fixes` can return, in the order :func:`repair` applies
#: them (the fade first: an edge sample can be the peak the attenuation then measures).
FIX_FADE = "fade"
FIX_LIMIT = "limit"


@dataclass
class RepairResult:
    """What :func:`repair` did to a clip.

    ``samples`` is the (possibly) repaired clip at ``sample_rate``; ``applied`` names
    each fix in the order applied (empty when nothing was done — ``reason`` says why);
    ``before`` is the QC report the decision was made on and ``after`` the re-check
    (``None`` when nothing was applied).
    """

    samples: "ndarray"
    sample_rate: int
    before: QCReport
    after: Optional[QCReport] = None
    applied: list = field(default_factory=list)
    reason: Optional[str] = None

    @property
    def repaired(self) -> bool:
        """True when at least one fix was applied."""
        return bool(self.applied)

    def cleared(self, min_status: QCStatus = DEFAULT_MIN_STATUS) -> bool:
        """True when the clip (as it now stands) meets the admission floor ``min_status``."""
        report = self.after if self.after is not None else self.before
        return not is_below(report.status, min_status)


def unrepairable(
    report: QCReport,
    *,
    thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS,
    max_clipped_ratio: float = DEFAULT_REPAIR_MAX_CLIPPED_RATIO,
) -> Optional[str]:
    """Why ``report``'s faults are beyond a Tier-0 repair — ``None`` when they are not.

    Args:
        report: The clip's QC report.
        thresholds: The QC thresholds the report was made with.
        max_clipped_ratio: The most clipping still treated as a run just over the gate.
    """
    if report.has_nan_inf:
        return "NaN/Inf samples (corrupt)"
    if report.is_silent:
        return "near-silent"
    if report.duration_s < thresholds.duration_min_s:
        return f"too short ({report.duration_s:.3f} s)"
    if report.clipped_ratio > max_clipped_ratio:
        return (
            f"clipped ratio {report.clipped_ratio:.4%} > {max_clipped_ratio:.4%}: "
            "distortion, not a run just over the gate"
        )
    return None


def suggested_fixes(
    report: QCReport, *, thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS
) -> "list[str]":
    """The fixes ``report`` calls for: :data:`FIX_FADE` (an edge click) and/or
    :data:`FIX_LIMIT` (a clip event, or a true peak over the ceiling)."""
    fixes = []
    if report.needs_edge_fade:
        fixes.append(FIX_FADE)
    over_ceiling = (
        report.true_peak_dbtp is not None
        and report.true_peak_dbtp > thresholds.true_peak_max_dbtp
    )
    if report.clipped_max_run > 0 or report.clipped_ratio > 0 or over_ceiling:
        fixes.append(FIX_LIMIT)
    return fixes


def repair(
    samples: "ndarray",
    sample_rate: int,
    *,
    report: Optional[QCReport] = None,
    thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS,
    min_status: QCStatus = DEFAULT_MIN_STATUS,
    fade_s: float = DEFAULT_REPAIR_FADE_S,
    ceiling_dbtp: float = DEFAULT_REPAIR_CEILING_DBTP,
    max_clipped_ratio: float = DEFAULT_REPAIR_MAX_CLIPPED_RATIO,
) -> RepairResult:
    """Apply the fixes ``report`` suggests to ``samples`` and QC the result again.

    Acts only on a clip the admission gate would quarantine (``report.status`` below
    ``min_status``) and whose faults a fade and an attenuation can fix
    (:func:`unrepairable`); otherwise the clip comes back untouched with ``reason``
    set. Fixes, in order: a ``fade_s`` in/out declick when the report flags an edge
    click; a static true-peak attenuation to ``ceiling_dbtp`` when it flags a clip
    event or an over-ceiling peak. The re-check runs on the working array exactly as
    ingest does, so what clears here clears there.

    Args:
        samples: The clip to repair — the native-rate decoded array (mono or
            ``(frames, channels)``), so what is stored afterwards is the repaired clip.
        sample_rate: Its rate in Hz.
        report: The clip's QC report (default: computed here on the working array).
        thresholds: The QC thresholds (default: the shipped table).
        min_status: The admission floor (default: ingest's, ``warn``).
        fade_s: Declick fade length in seconds.
        ceiling_dbtp: The true-peak ceiling the attenuation lands at.
        max_clipped_ratio: The most clipping still treated as repairable.

    Returns:
        A :class:`RepairResult`.

    Lazy dependencies: ``numpy``; ``soxr`` when ``sample_rate`` is not the working rate.
    """
    from .audio import WORKING_SAMPLE_RATE, fade, limit_true_peak, to_working

    def qc(clip):
        return run_qc(
            to_working(clip, sample_rate), WORKING_SAMPLE_RATE, thresholds=thresholds
        )

    before = report if report is not None else qc(samples)
    result = RepairResult(samples=samples, sample_rate=sample_rate, before=before)
    if not is_below(before.status, min_status):
        result.reason = f"QC {before.status.value}: nothing to repair"
        return result
    why = unrepairable(
        before, thresholds=thresholds, max_clipped_ratio=max_clipped_ratio
    )
    if why is not None:
        result.reason = f"not repairable: {why}"
        return result
    fixes = suggested_fixes(before, thresholds=thresholds)
    if not fixes:
        result.reason = "no Tier-0 fix for: " + "; ".join(before.notes)
        return result

    out = samples
    if FIX_FADE in fixes:
        out = fade(out, sample_rate, fade_in_s=fade_s, fade_out_s=fade_s)
        result.applied.append(f"fade {fade_s * 1000:.0f} ms in/out (edge click)")
    if FIX_LIMIT in fixes:
        out, gain_db = limit_true_peak(out, sample_rate, ceiling_dbtp=ceiling_dbtp)
        result.applied.append(
            f"true peak attenuated {gain_db:+.2f} dB to {ceiling_dbtp:g} dBTP "
            "(clipping / over-ceiling peak)"
        )
    result.samples = out
    result.after = qc(out)
    return result
