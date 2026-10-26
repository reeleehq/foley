"""Tier-0 deterministic audio QC for foley (research report 08 §3).

Pure, per-clip range-checks over a floating-point waveform in ``[-1, 1]``:
clipping, true-peak, DC offset, whole-clip silence, SNR, edge clicks, loudness
(LUFS), duration, and ``NaN``/``Inf`` sanity. Every threshold is an explicit
:class:`QCThresholds` field — there are **no inline policy literals** — so the
whole table is a single, overridable source of truth.

Zero-dependency import contract:
    This module imports **stdlib only** at the top level. ``numpy`` is
    lazy-imported inside each function body (like ``foley.audio``), so
    ``import foley.qc`` succeeds on a bare install with no scientific stack.
    :func:`measure_lufs` additionally lazy-imports ``pyloudnorm`` and returns
    ``None`` when it (or a measurable clip) is absent; everything else is
    numpy-only.

Waveform convention:
    ``samples`` is a float array shaped ``(frames,)`` (mono) or
    ``(frames, channels)``. dBFS is ``20·log10(|x|)`` with full scale at 1.0.

Typical use (at ingest, a later phase)::

    report = run_qc(working_array, sample_rate)
    sound_record.qc = report.to_dict()   # becomes filterable metadata
"""

from __future__ import annotations

import math
import warnings
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # annotations only — never imported at runtime
    import numpy as np


#: BS.1770 integrated-loudness gating block = 400 ms; a clip shorter than one
#: block cannot be measured (``pyloudnorm`` raises), so :func:`measure_lufs`
#: returns ``None`` for it. This is a fixed property of the algorithm, not a
#: tunable QC policy threshold, hence a module constant rather than a field.
LUFS_MIN_BLOCK_S: float = 0.4


class QCStatus(str, Enum):
    """Overall verdict for a clip (subclasses ``str`` so it is JSON-safe)."""

    pass_ = "pass"
    warn = "warn"
    fail = "fail"


#: Admission ordering of :class:`QCStatus` values (worse -> better): the SSOT for
#: "is this clip below the floor?" — :func:`is_below`, the ingest gate's ``min_status``
#: and :mod:`foley.repair` all read it.
QC_STATUS_RANK: dict = {
    QCStatus.fail.value: 0,
    QCStatus.warn.value: 1,
    QCStatus.pass_.value: 2,
}

#: The admission floor foley's ingest uses unless told otherwise: ``warn`` clips are
#: stored (their notes travel with the record); only ``fail`` clips are quarantined.
DEFAULT_MIN_STATUS: QCStatus = QCStatus.warn


def is_below(status, min_status=DEFAULT_MIN_STATUS) -> bool:
    """True when ``status`` is worse than the admission floor ``min_status``.

    Accepts :class:`QCStatus` members or their string values; an unknown value ranks
    as ``fail`` (fail-closed).

    >>> is_below(QCStatus.fail, QCStatus.warn), is_below("warn", "warn")
    (True, False)
    """

    def rank(value) -> int:
        return QC_STATUS_RANK.get(getattr(value, "value", value), 0)

    return rank(status) < rank(min_status)


@dataclass(frozen=True)
class QCThresholds:
    """All Tier-0 QC defaults (report 08 §3 table), each an explicit field.

    Grouped by check. Pass a customized instance to :func:`run_qc` (or the
    per-check keyword arguments) to override any threshold without editing code.
    """

    # clipping
    clip_full_scale: float = 0.999  # |x| >= this counts as full-scale
    clip_min_run: int = 3  # consecutive full-scale samples = a clip event
    clip_reject_ratio: float = 0.0001  # 0.01% clipped-sample ratio => fail
    clip_reject_run: int = 10  # any run >= 10 samples => fail
    # true peak
    true_peak_max_dbtp: float = -1.0
    true_peak_oversample: int = 4
    # dc offset
    dc_offset_fail: float = 0.01  # |mean| > 0.01 => correct/warn
    dc_offset_warn: float = 0.001  # 0.001..0.01 => note
    # silence
    silence_rms_dbfs: float = -60.0  # whole-clip RMS below => empty (fail)
    # SNR
    snr_clean_db: float = 20.0  # >= clean; below => warn (advisory)
    snr_quiet_percentile: float = 10.0  # noise floor from quietest 10% of frames
    snr_frame_s: float = 0.025  # 25 ms short-time RMS frames
    snr_hop_s: float = 0.010
    # edge click / fade
    edge_rel_peak_dbfs: float = -40.0  # first/last sample above this rel-peak => fade
    edge_fade_s: float = 0.01
    # loudness
    lufs_gate_floor: float = -70.0
    lufs_outlier_lu: float = 6.0  # +/- from library median (library-level check)
    # duration / format
    duration_min_s: float = 0.1
    # reserved: a DELIVERY-time target (enforced with the master profile at the
    # weave stage), NOT a Tier-0 source-clip gate — kept in this one table so all
    # rate/loudness policy has a single home. run_qc does not evaluate it.
    deliver_min_sample_rate: int = 44_100


#: The shipped default thresholds; the default for every keyword below.
DEFAULT_QC_THRESHOLDS = QCThresholds()


# ---------------------------------------------------------------------------
# Private numpy helpers (each lazy-imports numpy so the module stays zero-dep)
# ---------------------------------------------------------------------------


def _as_2d(samples: "np.ndarray") -> "np.ndarray":
    """Return ``samples`` as a float64 ``(frames, channels)`` array.

    Mono ``(frames,)`` input is promoted to ``(frames, 1)``.
    """
    import numpy as np

    a = np.asarray(samples, dtype=np.float64)
    return a[:, None] if a.ndim == 1 else a


def _to_mono_1d(samples: "np.ndarray") -> "np.ndarray":
    """Down-mix to a 1-D float64 array (channel mean); 1-D passes through."""
    import numpy as np

    a = np.asarray(samples, dtype=np.float64)
    return a if a.ndim == 1 else a.mean(axis=1)


def _true_run_lengths(mask: "np.ndarray") -> "np.ndarray":
    """Lengths of every maximal run of ``True`` in a 1-D boolean array.

    Vectorized via a padded first-difference: rising edges start runs, falling
    edges end them. Returns an empty array when there are no ``True`` runs.
    """
    import numpy as np

    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return np.empty(0, dtype=int)
    padded = np.concatenate(([False], m, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return ends - starts


def _upsample_fft(x: "np.ndarray", factor: int) -> "np.ndarray":
    """Band-limited ``factor``x upsampling of a 1-D real signal via zero-padding
    the ``rfft`` spectrum. Amplitude-preserving (scaled by ``factor``)."""
    import numpy as np

    n = x.shape[0]
    if factor <= 1 or n < 2:
        return x
    n_up = n * factor
    spec = np.fft.rfft(x)
    spec_up = np.zeros(n_up // 2 + 1, dtype=complex)
    m = min(spec.shape[0], spec_up.shape[0])
    spec_up[:m] = spec[:m]
    # For even n, bin n//2 is the original Nyquist (a real cosine at f_s/2). After
    # zero-pad upsampling it is no longer the Nyquist of the longer signal, so its
    # energy must be split in half — else the reconstruction (and the true-peak
    # estimate riding on it) over-reports by up to +6 dB (cf. scipy.signal.resample).
    if n % 2 == 0 and m == n // 2 + 1:
        spec_up[n // 2] *= 0.5
    return np.fft.irfft(spec_up, n=n_up) * factor


def _frame_rms(x: "np.ndarray", frame_len: int, hop: int) -> "np.ndarray":
    """Short-time RMS of a 1-D signal over ``frame_len`` windows every ``hop``.

    If the signal is shorter than one frame it yields a single whole-signal RMS.
    """
    import numpy as np

    n = x.shape[0]
    if n <= frame_len:
        return np.array([float(np.sqrt(np.mean(x * x)))])
    starts = np.arange(0, n - frame_len + 1, hop)
    return np.array(
        [float(np.sqrt(np.mean(x[s : s + frame_len] ** 2))) for s in starts]
    )


def _rms_dbfs(samples: "np.ndarray") -> float:
    """Whole-clip RMS level in dBFS (``-inf`` for exact/zero silence)."""
    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0:
        return float("-inf")
    mean_square = float(np.mean(x * x))
    if mean_square <= 0.0:
        return float("-inf")
    return float(10.0 * np.log10(mean_square))  # 10·log10(ms) == 20·log10(rms)


# ---------------------------------------------------------------------------
# Public per-check functions (deterministic; numpy-only unless noted)
# ---------------------------------------------------------------------------


def has_nan_inf(samples: "np.ndarray") -> bool:
    """Return ``True`` if any sample is ``NaN`` or ``Inf`` (corrupt-clip guard)."""
    import numpy as np

    return bool(not np.isfinite(np.asarray(samples)).all())


def duration_s(samples: "np.ndarray", sample_rate: int) -> float:
    """Clip duration in seconds: ``frames / sample_rate``."""
    import numpy as np

    a = np.asarray(samples)
    frames = a.shape[0] if a.ndim else 0
    return float(frames) / float(sample_rate)


def dc_offset(samples: "np.ndarray") -> float:
    """Largest per-channel absolute DC offset, ``max_c |mean_n x[n, c]|``."""
    import numpy as np

    a = _as_2d(samples)
    if a.shape[0] == 0:
        return 0.0
    return float(np.max(np.abs(a.mean(axis=0))))


def is_silent(
    samples: "np.ndarray",
    *,
    rms_floor_dbfs: float = DEFAULT_QC_THRESHOLDS.silence_rms_dbfs,
) -> bool:
    """Return ``True`` when whole-clip RMS falls below ``rms_floor_dbfs``.

    A zero (exactly silent) clip has RMS ``0`` -> ``-inf`` dBFS -> ``True``.
    """
    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0:
        return True
    mean_square = float(np.mean(x * x))
    if mean_square <= 0.0:
        return True
    dbfs = 10.0 * np.log10(mean_square)
    return bool(dbfs < rms_floor_dbfs)


def detect_clipping(
    samples: "np.ndarray",
    *,
    full_scale: float = DEFAULT_QC_THRESHOLDS.clip_full_scale,
    min_run: int = DEFAULT_QC_THRESHOLDS.clip_min_run,
) -> tuple[float, int]:
    """Detect hard (flat-topped) clipping.

    A frame is "hot" when any channel reaches ``|x| >= full_scale``. Only
    maximal hot runs of length ``>= min_run`` count as clip events.

    Args:
        samples: Waveform in ``[-1, 1]``.
        full_scale: Absolute level at/above which a sample is full-scale.
        min_run: Minimum consecutive full-scale frames to count as clipping.

    Returns:
        ``(clipped_ratio, max_run_length)`` — the fraction of frames inside
        counting runs, and the longest counting run (``(0.0, 0)`` if none).
    """
    import numpy as np

    a = np.abs(_as_2d(samples))
    total = a.shape[0]
    if total == 0:
        return 0.0, 0
    hot = np.max(a, axis=1) >= full_scale
    runs = _true_run_lengths(hot)
    clip_runs = runs[runs >= min_run]
    if clip_runs.size == 0:
        return 0.0, 0
    return float(clip_runs.sum()) / float(total), int(clip_runs.max())


def true_peak_dbtp(
    samples: "np.ndarray",
    sample_rate: int,
    *,
    oversample: int = DEFAULT_QC_THRESHOLDS.true_peak_oversample,
) -> float:
    """Inter-sample true-peak level in dBTP.

    Each channel is band-limited-upsampled ``oversample``x (numpy FFT), the
    peak magnitude is taken across all channels, and converted to dBTP. Returns
    ``-inf`` for a fully silent clip. ``sample_rate`` is accepted for interface
    symmetry (FFT interpolation is rate-independent).
    """
    import numpy as np

    a = _as_2d(samples)
    peak = 0.0
    for c in range(a.shape[1]):
        up = _upsample_fft(a[:, c], oversample)
        chan_peak = float(np.max(np.abs(up))) if up.size else 0.0
        peak = max(peak, chan_peak)
    if peak <= 0.0:
        return float("-inf")
    return float(20.0 * np.log10(peak))


def estimate_snr(
    samples: "np.ndarray",
    sample_rate: int,
    *,
    quiet_percentile: float = DEFAULT_QC_THRESHOLDS.snr_quiet_percentile,
    frame_s: float = DEFAULT_QC_THRESHOLDS.snr_frame_s,
    hop_s: float = DEFAULT_QC_THRESHOLDS.snr_hop_s,
) -> float:
    """Estimate SNR in dB (advisory — a busy-street SFX legitimately scores low).

    The noise floor is the mean short-time RMS of the quietest
    ``quiet_percentile`` percent of frames; the signal level is the whole-clip
    RMS. A near-noise-free clip (quiet frames -> ~0) yields a very high value;
    an exactly-zero floor returns ``inf`` and a silent clip returns ``-inf``.

    Args:
        samples: Waveform in ``[-1, 1]`` (down-mixed to mono internally).
        sample_rate: Sample rate in Hz (sizes the frames).
        quiet_percentile: Percent of quietest frames forming the noise floor.
        frame_s: Short-time frame length in seconds.
        hop_s: Hop between frames in seconds.

    Returns:
        SNR in dB.
    """
    import numpy as np

    x = _to_mono_1d(samples)
    if x.shape[0] == 0:
        return float("-inf")
    signal_rms = float(np.sqrt(np.mean(x * x)))
    if signal_rms <= 0.0:
        return float("-inf")
    frame_len = max(1, int(round(frame_s * sample_rate)))
    hop = max(1, int(round(hop_s * sample_rate)))
    frame_rms = _frame_rms(x, frame_len, hop)
    if frame_rms.size == 0:
        return float("inf")
    k = max(1, int(np.ceil(frame_rms.size * quiet_percentile / 100.0)))
    quietest = np.sort(frame_rms)[:k]
    noise_floor = float(np.mean(quietest))
    if noise_floor <= 0.0:
        return float("inf")
    return float(20.0 * np.log10(signal_rms / noise_floor))


def needs_edge_fade(
    samples: "np.ndarray",
    *,
    rel_peak_dbfs: float = DEFAULT_QC_THRESHOLDS.edge_rel_peak_dbfs,
) -> bool:
    """Return ``True`` when the first or last sample sits above ``rel_peak_dbfs``
    relative to the clip peak — i.e. a nonzero boundary that clicks under
    narration and needs a short fade."""
    import numpy as np

    a = np.abs(_as_2d(samples))
    if a.shape[0] == 0:
        return False
    peak = float(a.max())
    if peak <= 0.0:
        return False
    edge = float(max(a[0].max(), a[-1].max()))
    if edge <= 0.0:
        return False
    rel_db = 20.0 * np.log10(edge / peak)
    return bool(rel_db > rel_peak_dbfs)


def measure_lufs(
    samples: "np.ndarray",
    sample_rate: int,
    *,
    gate_floor_lufs: float = DEFAULT_QC_THRESHOLDS.lufs_gate_floor,
    min_block_s: float = LUFS_MIN_BLOCK_S,
    meter: "Optional[Meter]" = None,
) -> Optional[float]:
    """Integrated loudness (LUFS, ITU-R BS.1770-4) via :func:`foley.audio.integrated_lufs`.

    The one meter (``pyloudnorm`` by default, lazy; ``meter`` swaps it).

    Returns ``None`` when ``pyloudnorm`` is unavailable, the clip is shorter than
    one gating block (``min_block_s``), the samples are non-finite, or the
    measured loudness is at/below the gate floor (near-silent / unstable — do
    not amplify, just flag).
    """
    import numpy as np

    from .audio import integrated_lufs

    x = np.asarray(samples, dtype=np.float64)
    if not np.isfinite(x).all():
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:  # a missing pyloudnorm / an unreadable layout is "not measurable"
            loudness = integrated_lufs(
                x, sample_rate, min_block_s=min_block_s, meter=meter
            )
        except Exception:
            return None
    if not np.isfinite(loudness) or loudness <= gate_floor_lufs:
        return None
    return loudness


# ---------------------------------------------------------------------------
# QCReport + the run_qc orchestrator
# ---------------------------------------------------------------------------


@dataclass
class QCReport:
    """Per-clip Tier-0 QC result.

    Mirrors the fields the ``SoundRecord`` schema already carries
    (``duration_s``, ``sample_rate``, ``channels``, ``loudness_lufs``) plus the
    deterministic check outputs, an overall ``status``, and human-readable
    ``notes`` for every firing condition. Serialize with :meth:`to_dict` into
    ``SoundRecord.qc``.
    """

    duration_s: float
    sample_rate: int
    channels: int
    clipped_ratio: float
    clipped_max_run: int
    dc_offset: float
    rms_dbfs: Optional[float]  # None when non-finite (silent clip => -inf): JSON-safe
    is_silent: bool
    needs_edge_fade: bool
    has_nan_inf: bool
    true_peak_dbtp: Optional[float] = None
    snr_db: Optional[float] = None
    loudness_lufs: Optional[float] = None
    status: QCStatus = QCStatus.pass_
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a plain, JSON-safe dict (``status`` as its string value).

        Non-finite floats are swept to ``None`` at this boundary too (belt-and-
        suspenders over the construction-time :func:`_json_safe` guard) so no
        ``Infinity``/``NaN`` can ever reach ``json.dumps`` regardless of who set a
        field.
        """
        d = asdict(self)
        d["status"] = self.status.value
        return {
            k: (None if isinstance(v, float) and not math.isfinite(v) else v)
            for k, v in d.items()
        }


def _is_finite(value: Optional[float]) -> bool:
    """True when ``value`` is a finite number (guards ``None``/``inf``/``nan``)."""
    import numpy as np

    return value is not None and bool(np.isfinite(value))


def _json_safe(value: Optional[float]) -> Optional[float]:
    """Clamp a non-finite float to ``None`` so :meth:`QCReport.to_dict` ->
    ``json.dumps`` is strict-JSON safe.

    ``estimate_snr`` can return ``+inf`` (zero-padded one-shot: noise floor 0) or
    ``-inf`` (silent); ``_rms_dbfs`` / ``true_peak_dbtp`` return ``-inf`` (silent).
    Left raw, ``json.dumps`` emits ``Infinity``/``-Infinity``, which Postgres
    JSONB and JS ``JSON.parse`` reject — breaking the cloud-store-swap invariant.
    This is the single SSOT for that clamp.
    """
    return value if _is_finite(value) else None


def run_qc(
    samples: "np.ndarray",
    sample_rate: int,
    *,
    thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS,
) -> QCReport:
    """Run every Tier-0 check and fold the results into a :class:`QCReport`.

    Status rules (evaluated in order):
        FAIL if ``has_nan_inf`` OR ``is_silent`` OR
        ``clipped_max_run >= clip_reject_run`` OR
        ``clipped_ratio > clip_reject_ratio`` OR ``duration_s < duration_min_s``.
        WARN if ``dc_offset > dc_offset_fail`` OR ``needs_edge_fade`` OR
        (``snr_db`` is a finite value ``< snr_clean_db``) OR
        (``true_peak_dbtp`` is a finite value ``> true_peak_max_dbtp``).
        Otherwise PASS.

    Each firing condition appends a human-readable string to ``notes``. Two
    thresholds are intentionally NOT evaluated on a single source clip here
    because they belong to later stages: the library-median loudness-outlier
    check (``+/- lufs_outlier_lu``, a library-level concern) and the delivery
    sample-rate target (``deliver_min_sample_rate``, enforced at the weave/master
    stage).

    Args:
        samples: Waveform in ``[-1, 1]`` (mono or ``(frames, channels)``).
        sample_rate: Sample rate in Hz.
        thresholds: Overridable QC thresholds (defaults to shipped values).

    Returns:
        A populated :class:`QCReport`.
    """
    import numpy as np

    a = np.asarray(samples)
    channels = 1 if a.ndim <= 1 else int(a.shape[1])

    duration = duration_s(a, sample_rate)
    nan_inf = has_nan_inf(a)
    rms_db = _rms_dbfs(a)
    silent = is_silent(a, rms_floor_dbfs=thresholds.silence_rms_dbfs)
    clipped_ratio, clipped_max_run = detect_clipping(
        a, full_scale=thresholds.clip_full_scale, min_run=thresholds.clip_min_run
    )
    dc = dc_offset(a)
    edge = needs_edge_fade(a, rel_peak_dbfs=thresholds.edge_rel_peak_dbfs)
    true_peak = true_peak_dbtp(
        a, sample_rate, oversample=thresholds.true_peak_oversample
    )
    snr = estimate_snr(
        a,
        sample_rate,
        quiet_percentile=thresholds.snr_quiet_percentile,
        frame_s=thresholds.snr_frame_s,
        hop_s=thresholds.snr_hop_s,
    )
    lufs = measure_lufs(a, sample_rate, gate_floor_lufs=thresholds.lufs_gate_floor)

    notes: list = []
    fail = False
    if nan_inf:
        fail = True
        notes.append("NaN/Inf samples present (corrupt file) => reject")
    if silent:
        fail = True
        notes.append(
            f"near-silent: RMS {rms_db:.1f} dBFS < "
            f"{thresholds.silence_rms_dbfs} dBFS floor => reject"
        )
    if clipped_max_run >= thresholds.clip_reject_run:
        fail = True
        notes.append(
            f"hard clipping: run of {clipped_max_run} >= "
            f"{thresholds.clip_reject_run} full-scale samples => reject"
        )
    if clipped_ratio > thresholds.clip_reject_ratio:
        fail = True
        notes.append(
            f"hard clipping: clipped ratio {clipped_ratio:.4%} > "
            f"{thresholds.clip_reject_ratio:.4%} => reject"
        )
    if duration < thresholds.duration_min_s:
        fail = True
        notes.append(
            f"too short: {duration:.3f} s < {thresholds.duration_min_s} s => reject"
        )

    warn = False
    if dc > thresholds.dc_offset_fail:
        warn = True
        notes.append(
            f"DC offset {dc:.4f} > {thresholds.dc_offset_fail} => high-pass/correct"
        )
    elif dc > thresholds.dc_offset_warn:
        notes.append(
            f"minor DC offset {dc:.4f} (> {thresholds.dc_offset_warn}) "
            "— within tolerance, no action"
        )
    if edge:
        warn = True
        notes.append(
            f"edge click: boundary above {thresholds.edge_rel_peak_dbfs} dBFS "
            f"rel-peak => apply >= {thresholds.edge_fade_s * 1000:.0f} ms fade"
        )
    if _is_finite(snr) and snr < thresholds.snr_clean_db:
        warn = True
        notes.append(f"low SNR {snr:.1f} dB < {thresholds.snr_clean_db} dB (advisory)")
    if _is_finite(true_peak) and true_peak > thresholds.true_peak_max_dbtp:
        warn = True
        notes.append(
            f"true peak {true_peak:.2f} dBTP > {thresholds.true_peak_max_dbtp} dBTP"
        )

    if fail:
        status = QCStatus.fail
    elif warn:
        status = QCStatus.warn
    else:
        status = QCStatus.pass_

    return QCReport(
        duration_s=duration,
        sample_rate=int(sample_rate),
        channels=channels,
        clipped_ratio=clipped_ratio,
        clipped_max_run=clipped_max_run,
        dc_offset=dc,
        # Non-finite (+/-inf / nan) floats are clamped to None (see _json_safe):
        # rms_dbfs is -inf for a silent clip; snr_db is +inf for a zero-padded
        # one-shot (noise floor 0) and -inf when silent.
        rms_dbfs=_json_safe(rms_db),
        is_silent=silent,
        needs_edge_fade=edge,
        has_nan_inf=nan_inf,
        true_peak_dbtp=_json_safe(true_peak),
        snr_db=_json_safe(snr),
        loudness_lufs=_json_safe(lufs),
        status=status,
        notes=notes,
    )
