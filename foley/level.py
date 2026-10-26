"""Level a clip to a stated loudness target for its class, so relative levels are sane.

A generated clip comes out at whatever level its model likes: Stable Audio 3 peaks near
-20 dBFS, ElevenLabs much hotter, so two sounds meant to sit side by side differ by
10 dB or more before anyone touches a fader. :func:`level_bytes` measures a clip's
integrated loudness (ITU-R BS.1770-4) and scales it to the target for its class,
then keeps the sample peak under foley's ceiling.

The class targets are not new numbers. They are the dialogue-relative layer gains the
WEAVE mixer already uses (:data:`foley.weave.mix.LAYER_GAIN_DB`: a one-shot sits
9 dB under the voice, an ambience bed 21 dB under) applied to a voice at the
reference programme loudness (:data:`foley.audio.DEFAULT_LOUDNESS_TARGET_LUFS`,
-16 LUFS). So a levelled one-shot is at -25 LUFS and a levelled bed at -37 LUFS:
what they would be under a voice at -16 LUFS, and how they should sound side by side.

Two cases are left unchanged and said so, never amplified: a clip too short to
measure (under one 400 ms gating block: a click, a page flick) and a near-silent one.

:func:`foley.generate` levels a clip when asked (``level='sfx_fg'``, a
:class:`~foley.base.Layer`, or a LUFS number), for export and listening. It does not by
default: the library keeps clips as generated, and the WEAVE render brings every clip to
the reference loudness itself (below), so a stored clip's level does not matter to the mix.

**The WEAVE render levels by measurement** (:func:`reference_gain_db`, used by
:class:`foley.weave.render.FullRender`): each clip is first brought to the reference
loudness, then the layer gain is applied, so a hot ElevenLabs clip and a quiet Stable
Audio one land at the same place in the mix and ``generate(level=...)`` stays an export
tool. A clip too short for a loudness reading is levelled by its peak instead.

Zero-dependency import: ``numpy``, ``pyloudnorm`` and ``soundfile`` load inside the
functions.
"""

from __future__ import annotations

from typing import Optional, Union

from .base import Layer

#: What ``level=`` accepts: a layer (or its name) for its class target, or a LUFS value.
LevelSpec = Union[Layer, str, float, int]


def class_target_lufs(layer: Union[Layer, str]) -> float:
    """The integrated-loudness target (LUFS) for a clip of ``layer``.

    The reference voice loudness plus the layer's dialogue-relative gain (see the
    module docstring), so it moves with both SSOTs.

    >>> class_target_lufs("sfx_fg")
    -25.0
    >>> class_target_lufs(Layer.ambience)
    -37.0
    """
    from .audio import DEFAULT_LOUDNESS_TARGET_LUFS
    from .weave.mix import LAYER_GAIN_DB

    return float(DEFAULT_LOUDNESS_TARGET_LUFS + LAYER_GAIN_DB[Layer(layer)])


def resolve_target_lufs(spec: LevelSpec) -> float:
    """A ``level=`` value as a LUFS target: a number as is, a layer via :func:`class_target_lufs`.

    >>> resolve_target_lufs(-30)
    -30.0
    >>> resolve_target_lufs("stinger")
    -22.0
    """
    if isinstance(spec, bool):
        raise TypeError("level= takes a layer name or a LUFS number, not a bool")
    if isinstance(spec, (int, float)):
        return float(spec)
    try:
        return class_target_lufs(spec)
    except ValueError:
        raise ValueError(
            f"level={spec!r}: give a LUFS number or one of {[m.value for m in Layer]}"
        ) from None


def require_loudness_meter() -> None:
    """Raise ``ImportError`` (with the install line) when ``pyloudnorm`` is missing."""
    try:
        import pyloudnorm  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "level= measures loudness with pyloudnorm: pip install 'foley[audio]'"
        ) from exc


def level_bytes(
    audio_bytes: bytes, target: LevelSpec
) -> "tuple[bytes, Optional[str], Optional[float]]":
    """Scale an encoded clip to ``target`` loudness; return ``(bytes, applied, measured)``.

    Args:
        audio_bytes: Any clip ``soundfile`` decodes.
        target: A layer (its class target) or a LUFS number (see :func:`resolve_target_lufs`).

    Returns:
        ``(bytes, applied, measured_lufs)``: the levelled clip re-encoded in foley's FLAC
        archive form and a one-line account of the gain applied (for the licence's
        ``transformations``); or, for a clip too short or too quiet to measure, the
        bytes unchanged, ``applied=None`` and ``measured_lufs=None``.
    """
    import numpy as np

    from .audio import (
        LUFS_GATE_FLOOR,
        encode,
        limit_true_peak,
        load,
        loudness_normalize,
    )
    from .repair import DEFAULT_REPAIR_CEILING_DBTP

    target_lufs = resolve_target_lufs(target)
    wav, sr = load(audio_bytes)
    levelled, measured = loudness_normalize(wav, sr, target_lufs=target_lufs)
    if not np.isfinite(measured) or measured <= LUFS_GATE_FLOOR:
        return audio_bytes, None, None
    # A quiet clip raised to its target can overshoot the QC true-peak gate between
    # samples; keep it under the same ceiling the repair aims for.
    levelled, _ = limit_true_peak(
        levelled, sr, ceiling_dbtp=DEFAULT_REPAIR_CEILING_DBTP
    )
    peak_in = float(np.max(np.abs(wav))) or 1.0
    peak_out = float(np.max(np.abs(levelled))) or 1.0
    gain_db = 20.0 * float(np.log10(peak_out / peak_in))
    applied = (
        f"levelled from {measured:.1f} LUFS toward {target_lufs:.1f} LUFS "
        f"({gain_db:+.1f} dB, true peak kept under {DEFAULT_REPAIR_CEILING_DBTP:g} dBTP)"
    )
    return encode(levelled, sr), applied, float(measured)


#: Sample-peak ceiling (dBFS) a reference-levelled clip must stay under, so the layer
#: gain and the master limiter start from a clip that does not clip.
REFERENCE_PEAK_CEILING_DBFS = -1.0
#: Where a clip too short for a loudness reading (a click, a page flick) puts its sample
#: peak. Provisional: the peak a typical one-shot has when its integrated loudness is the
#: reference (about 10 dB of crest above -16 LUFS).
SHORT_CLIP_PEAK_DBFS = -6.0
#: The most a clip is boosted to reach the reference (dB), so a near-silent clip's noise
#: floor is not raised without bound. The 29 dB spread seen on a real film fits inside.
MAX_REFERENCE_BOOST_DB = 36.0
#: A clip whose sample peak is under this (dBFS) is silent for levelling purposes.
SILENT_PEAK_DBFS = -80.0


def reference_gain_db(
    clip,
    sample_rate: int,
    *,
    reference_lufs: Optional[float] = None,
    peak_ceiling_dbfs: float = REFERENCE_PEAK_CEILING_DBFS,
    short_peak_dbfs: float = SHORT_CLIP_PEAK_DBFS,
    max_boost_db: float = MAX_REFERENCE_BOOST_DB,
) -> float:
    """The gain (dB) that brings ``clip`` to the reference loudness; ``0.0`` if it cannot.

    Integrated loudness (BS.1770, gated) is measured and the gain is
    ``reference_lufs - measured``. A clip too short or too quiet to measure is levelled by
    its sample peak (to ``short_peak_dbfs``) instead. Either way the gain is capped so the
    clip's sample peak stays at or under ``peak_ceiling_dbfs`` and the boost at
    ``max_boost_db``; a silent or non-finite clip gets ``0.0``. Pure and deterministic.

    Args:
        clip: Mono or multichannel samples, time on axis 0.
        sample_rate: Sample rate in Hz.
        reference_lufs: The loudness every clip is brought to (default: foley's
            reference programme loudness, :data:`foley.audio.DEFAULT_LOUDNESS_TARGET_LUFS`).
    """
    import numpy as np

    from .audio import DEFAULT_LOUDNESS_TARGET_LUFS
    from .qc import measure_lufs

    reference = (
        DEFAULT_LOUDNESS_TARGET_LUFS if reference_lufs is None else reference_lufs
    )
    x = np.asarray(clip, dtype=np.float64)
    if not np.isfinite(x).all() or x.size == 0:
        return 0.0
    peak = float(np.max(np.abs(x)))
    peak_db = 20.0 * float(np.log10(peak)) if peak > 0 else float("-inf")
    if peak_db <= SILENT_PEAK_DBFS:
        return 0.0
    measured = measure_lufs(x, sample_rate)
    wanted = short_peak_dbfs - peak_db if measured is None else reference - measured
    return float(min(wanted, peak_ceiling_dbfs - peak_db, max_boost_db))
