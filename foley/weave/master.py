"""Mastering — loudness-normalize + true-peak-limit the finished mix (report 06 §5).

Normalises the whole program to a :class:`~foley.base.MasterProfile` integrated-loudness
target (ITU-R BS.1770-4 / EBU R128 via ``pyloudnorm``) and holds an inter-sample
**true-peak** ceiling. It reuses :func:`foley.audio.loudness_normalize` (the same
BS.1770 meter Tier-0 QC uses) for the LUFS stage and :func:`foley.qc.true_peak_dbtp`
(oversampled) for the ceiling — so ``pyloudnorm`` comes from the existing ``audio``
extra (no redundant dependency) and is imported function-locally, keeping ``import
foley.weave`` dol-only.

The default ``engine='auto'`` masters fully in-process (portable, testable).
``engine='ffmpeg'`` runs the two-pass ``ffmpeg loudnorm`` "guarantee the numbers" master
(report 06 §5.4) — measure, then apply a linear loudnorm to the measured values — and
**fails safe** back to the in-process path when the ``ffmpeg`` binary is unavailable or
errors, so weaving never depends on it. ``ffmpeg`` is a WEAVE system requirement (see
:mod:`foley.weave.requirements`); everything is lazy so ``import foley.weave`` stays dol-only.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ..base import MasterProfile
from .mix import db_to_lin

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray


@dataclass
class MasterReport:
    """What the master stage did — a JSON-serialisable audit row for the run-artifact."""

    target_lufs: float
    input_lufs: float
    output_lufs: float
    true_peak_dbtp: float
    true_peak_ceiling_db: float
    gain_db: float
    limited: bool
    engine: str

    def to_dict(self) -> dict:
        """Return the plain-dict form (for ``WeaveResult.master_report`` / obs)."""
        return asdict(self)


def _measure_lufs(samples: "ndarray", sample_rate: int) -> float:
    """Integrated loudness (LUFS) of ``samples``; ``-inf`` when too short to gate."""
    from ..audio import integrated_lufs

    return integrated_lufs(samples, sample_rate)


def _tp(mix: "ndarray", sample_rate: int) -> float:
    """Inter-sample true-peak (dBTP) of ``mix`` (the oversampled Tier-0 QC meter)."""
    from ..qc import true_peak_dbtp

    return float(true_peak_dbtp(mix, sample_rate))


def _true_peak_limit(
    mix: "ndarray", sample_rate: int, ceiling_db: float
) -> "tuple[ndarray, float, bool]":
    """Scale ``mix`` so its inter-sample true peak sits at/below ``ceiling_db``.

    Returns ``(mix, true_peak_dbtp, limited)``. A true-peak-safe *scale* (not a
    lookahead limiter) — simple, deterministic, and never raises the ceiling.
    """
    import numpy as np

    from ..qc import true_peak_dbtp

    tp = true_peak_dbtp(mix, sample_rate)
    if not np.isfinite(tp) or tp <= ceiling_db:
        return mix, tp, False
    out = mix * db_to_lin(ceiling_db - tp)
    return out, true_peak_dbtp(out, sample_rate), True


def _parse_loudnorm_json(stderr: str) -> dict:
    """Extract ffmpeg ``loudnorm=print_format=json`` measurements from a pass-1 stderr.

    ffmpeg prints the JSON block last on stderr; parse the final ``{...}`` object.
    """
    import json

    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no loudnorm JSON found in ffmpeg output")
    return json.loads(stderr[start : end + 1])


def _master_ffmpeg(
    mix: "ndarray", sample_rate: int, profile: MasterProfile
) -> "ndarray":
    """Two-pass ``ffmpeg loudnorm`` master (report 06 §5.4) — "guarantee the numbers".

    Pass 1 measures the program (I/TP/LRA/thresh/offset); pass 2 applies a linear
    loudnorm to the measured values so the output hits the profile's integrated-loudness
    and true-peak targets to broadcast tolerance. Needs the ``ffmpeg`` binary (a WEAVE
    system requirement); everything is lazy so ``import foley.weave`` stays dol-only.
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    import numpy as np
    import soundfile as sf

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    target_i = profile.target_lufs
    target_tp = profile.true_peak_db
    lra = getattr(profile, "lra", None) or 11.0
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        sf.write(str(src), np.asarray(mix, dtype="float32"), sample_rate)
        measure = f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:print_format=json"
        p1 = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(src),
                "-af",
                measure,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
        )
        m = _parse_loudnorm_json(p1.stderr)
        apply_ = (
            f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:linear=true:"
            f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:print_format=summary"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-y",
                "-i",
                str(src),
                "-af",
                apply_,
                "-ar",
                str(sample_rate),
                str(dst),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        out, _ = sf.read(str(dst), dtype="float32", always_2d=True)
    return out


def master(
    mix: "ndarray",
    sample_rate: int,
    profile: MasterProfile,
    *,
    engine: str = "auto",
) -> "tuple[ndarray, MasterReport]":
    """Master ``mix`` to ``profile`` — LUFS-normalise then true-peak-limit (report 06 §5).

    Args:
        mix: The summed working mix (stereo ``(frames, 2)`` float32).
        sample_rate: Sample rate in Hz.
        profile: The :class:`~foley.base.MasterProfile` (target LUFS / true-peak / LRA).
        engine: ``'auto'``/``'inprocess'`` master in-process (default, portable). ``'ffmpeg'``
            uses the two-pass ``ffmpeg loudnorm`` "guarantee the numbers" master (report 06
            §5.4) and **fails safe** back to in-process if ffmpeg is unavailable or errors.

    Returns:
        ``(mastered_mix, MasterReport)``. Loudness is measured before and after so the
        report is a faithful audit; when a true-peak limit engages, output LUFS may
        sit slightly below target (peak-safety wins over exact loudness).
    """
    if engine == "ffmpeg":
        try:
            mastered = _master_ffmpeg(mix, sample_rate, profile)
            out_lufs = _measure_lufs(mastered, sample_rate)
            in_lufs = _measure_lufs(mix, sample_rate)
            return mastered, MasterReport(
                target_lufs=profile.target_lufs,
                input_lufs=in_lufs,
                output_lufs=out_lufs,
                true_peak_dbtp=_tp(mastered, sample_rate),
                true_peak_ceiling_db=profile.true_peak_db,
                gain_db=(out_lufs - in_lufs)
                if math.isfinite(out_lufs) and math.isfinite(in_lufs)
                else 0.0,
                limited=True,
                engine="ffmpeg",
            )
        except Exception:
            pass  # fail-safe: degrade to the portable in-process master below

    from ..audio import loudness_normalize

    normalized, input_lufs = loudness_normalize(
        mix,
        sample_rate,
        target_lufs=profile.target_lufs,
        peak_ceiling_dbfs=profile.true_peak_db,
    )
    limited_mix, tp, limited = _true_peak_limit(
        normalized, sample_rate, profile.true_peak_db
    )
    output_lufs = _measure_lufs(limited_mix, sample_rate)
    gain_db = (
        output_lufs - input_lufs
        if math.isfinite(output_lufs) and math.isfinite(input_lufs)
        else 0.0
    )
    report = MasterReport(
        target_lufs=profile.target_lufs,
        input_lufs=input_lufs,
        output_lufs=output_lufs,
        true_peak_dbtp=tp,
        true_peak_ceiling_db=profile.true_peak_db,
        gain_db=gain_db,
        limited=limited,
        engine="inprocess",
    )
    return limited_mix, report
