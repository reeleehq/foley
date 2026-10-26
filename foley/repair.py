"""Repair instead of quarantine: the fixes a Tier-0 QC report suggests, applied and re-checked (#107).

A paid generation (or any clip) that :func:`foley.qc.run_qc` would quarantine for a
*trivially repairable* fault — a clipped run just over the gate, which usually rides
with an edge click and a true peak over the ceiling — is worth a 20 ms fade and a
true-peak attenuation more than it is worth the bin: the bytes were paid for.
:func:`repair` applies exactly the fixes the report names, with foley's own numpy
primitives (:func:`foley.audio.fade`, :func:`foley.audio.limit_true_peak`), runs QC
again on the result the way ingest will (:func:`foley.audio.to_working` then
:func:`foley.qc.run_qc`), and says what it did. What it cannot fix it leaves alone,
and says why (:func:`unrepairable`): NaN/Inf, silence, a too-short clip, or clipping
heavy enough to be distortion — a flat top longer than about a millisecond, or more
than a tenth of a percent of the clip — rather than a run just over the gate.

Only clipping quarantines a clip (an edge click and an over-ceiling peak are warnings,
admitted), so by default the policy acts only on a clip QC would refuse; the fade and
the attenuation then also clear the warnings it carries. To declick and attenuate
clips QC admits with a warning too, lower the trigger:
``functools.partial(repair, min_status=QCStatus.pass_)``.

:func:`foley.generate` runs this by default (``repair=True``); ``repair=False`` keeps
the quarantine, and a callable with :func:`repair`'s signature replaces the policy (an
ffmpeg ``afade`` + ``alimiter`` repair, say). :func:`repair_bytes` is the same policy
over encoded bytes — what ``generate`` calls, and the route for bytes a quarantine
kept (``foley.generations.get(key)``). Every repair is recorded on the candidate's
``notes`` and in the licence's ``transformations``, so the credit reads "(modified)"
and the content credential carries an edit action.

Zero-dependency import: stdlib only at the top level; ``numpy`` (and ``soxr`` when the
clip is not at the working rate, ``soundfile`` for :func:`repair_bytes`) load inside
the functions.
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

#: The longest single flat top still treated as repairable, in samples at the working
#: rate: five times the reject run (``QCThresholds.clip_reject_run``, 10), about a
#: millisecond. The ratio bound scales with the clip's length, so a long clip could
#: otherwise hide a long plateau under it; this one does not.
DEFAULT_REPAIR_MAX_CLIPPED_RUN: int = 5 * DEFAULT_QC_THRESHOLDS.clip_reject_run

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
    min_status: QCStatus = DEFAULT_MIN_STATUS  # the trigger the policy acted below

    @property
    def repaired(self) -> bool:
        """True when at least one fix was applied."""
        return bool(self.applied)

    @property
    def report(self) -> QCReport:
        """The QC report of the clip as it now stands (``after`` when repaired)."""
        return self.after if self.after is not None else self.before

    def cleared(self, admit: QCStatus = DEFAULT_MIN_STATUS) -> bool:
        """True when the clip, as it now stands, meets the admission floor ``admit``."""
        return not is_below(self.report.status, admit)

    def note(self, admit: QCStatus = DEFAULT_MIN_STATUS) -> Optional[str]:
        """One line for a result's notes: what was done, or why nothing was.

        ``None`` when there was nothing to do (the clip met ``admit`` and the policy
        left it alone) — the common case says nothing.
        """
        faults = "; ".join(self.before.notes)
        was = self.before.status.value
        if self.repaired:
            applied = "; ".join(self.applied)
            if self.cleared(admit):
                return (
                    f"repaired before QC admission: {applied}; QC was {was}: {faults}"
                )
            still = "; ".join(self.after.notes) if self.after else ""
            return (
                f"repair tried ({applied}) but QC still {self.report.status.value}: "
                f"{still}; kept the clip as received"
            )
        if is_below(self.before.status, admit):
            return f"repair skipped ({self.reason}); QC {was}: {faults}"
        return None


def unrepairable(
    report: QCReport,
    *,
    thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS,
    max_clipped_ratio: float = DEFAULT_REPAIR_MAX_CLIPPED_RATIO,
    max_clipped_run: int = DEFAULT_REPAIR_MAX_CLIPPED_RUN,
) -> Optional[str]:
    """Why ``report``'s faults are beyond a Tier-0 repair — ``None`` when they are not.

    Both clipping prongs QC fails on are bounded: the clipped ratio (a share of the
    clip) and the longest flat top (a length, so a long clip cannot hide a long
    plateau under a small ratio).

    Args:
        report: The clip's QC report.
        thresholds: The QC thresholds the report was made with.
        max_clipped_ratio: The most clipping still treated as a run just over the gate.
        max_clipped_run: The longest flat top (samples at the working rate) still
            treated as one.
    """
    if report.has_nan_inf:
        return "NaN/Inf samples (corrupt)"
    if report.is_silent:
        return "near-silent"
    if report.duration_s < thresholds.duration_min_s:
        return f"too short ({report.duration_s:.3f} s)"
    if report.clipped_max_run > max_clipped_run:
        return (
            f"flat top of {report.clipped_max_run} samples > {max_clipped_run}: "
            "distortion, not a run just over the gate"
        )
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
    max_clipped_run: int = DEFAULT_REPAIR_MAX_CLIPPED_RUN,
) -> RepairResult:
    """Apply the fixes ``report`` suggests to ``samples`` and QC the result again.

    Acts only on a clip whose status is below ``min_status`` — by default ingest's
    admission floor, so only a clip that would be quarantined (clipping) — and whose
    faults a fade and an attenuation can fix (:func:`unrepairable`); otherwise the
    clip comes back untouched with ``reason`` set. Fixes, in order: a ``fade_s``
    in/out declick when the report flags an edge click; a static true-peak
    attenuation to ``ceiling_dbtp`` when it flags a clip event or an over-ceiling
    peak. The re-check runs on the working array exactly as ingest does, so what
    clears here clears there.

    Args:
        samples: The clip to repair — the native-rate decoded array (mono or
            ``(frames, channels)``), so what is stored afterwards is the repaired clip.
        sample_rate: Its rate in Hz.
        report: The clip's QC report (default: computed here on the working array).
        thresholds: The QC thresholds (default: the shipped table).
        min_status: Act on a clip whose status is below this (default: ingest's
            admission floor, ``warn``: only a clip that would be quarantined;
            ``QCStatus.pass_`` also declicks/attenuates clips admitted with a warning).
        fade_s: Declick fade length in seconds.
        ceiling_dbtp: The true-peak ceiling the attenuation lands at.
        max_clipped_ratio: The most clipping still treated as repairable.
        max_clipped_run: The longest flat top (working-rate samples) still repairable.

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
    result = RepairResult(
        samples=samples, sample_rate=sample_rate, before=before, min_status=min_status
    )
    if not is_below(before.status, min_status):
        result.reason = f"QC {before.status.value}: nothing to repair"
        return result
    why = unrepairable(
        before,
        thresholds=thresholds,
        max_clipped_ratio=max_clipped_ratio,
        max_clipped_run=max_clipped_run,
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


def repair_bytes(
    audio_bytes: bytes,
    *,
    policy=True,
    admit: QCStatus = DEFAULT_MIN_STATUS,
    thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS,
) -> "tuple[bytes, RepairResult]":
    """:func:`repair` over an encoded clip: decode, QC, apply ``policy``, re-encode if it cleared.

    What :func:`foley.generate` calls on a fresh generation, and the route for bytes a
    quarantine kept: ``raw = foley.generations.get(key); fixed, result =
    foley.repair.repair_bytes(raw)``. The QC pass here is the one ingest runs (the
    working array, the same thresholds), so a clip the gate admits as is costs one
    decode and nothing else.

    Args:
        audio_bytes: Any clip ``soundfile`` decodes (the provider's WAV/MP3/FLAC).
        policy: ``True`` for :func:`repair` with its defaults, or a callable with its
            signature (``(samples, sample_rate, *, report) -> RepairResult``).
        admit: The admission floor a repair has to clear to be kept (ingest's).
        thresholds: The QC thresholds (default: the shipped table).

    Returns:
        ``(bytes, result)``: the repaired clip re-encoded in the FLAC archive form when
        the policy repaired it and the re-check meets ``admit`` — a record made from it
        then describes this re-encode (``format='flac'``, 24-bit), while the provider's
        bytes as received stay where they were — else ``audio_bytes`` unchanged; and the
        :class:`RepairResult` (``result.note(admit)`` is the one-line account, ``None``
        when there was nothing to do).

    Lazy dependencies: ``soundfile``, ``numpy``; ``soxr`` off the working rate.
    """
    from .audio import WORKING_SAMPLE_RATE, encode, load, to_working

    fn = repair if policy is True else policy
    wav, sr = load(audio_bytes)
    before = run_qc(to_working(wav, sr), WORKING_SAMPLE_RATE, thresholds=thresholds)
    result = fn(wav, sr, report=before)
    if result.repaired and result.cleared(admit):
        return encode(result.samples, sr), result
    return audio_bytes, result
