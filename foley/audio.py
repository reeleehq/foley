"""Audio I/O and DSP primitives for foley.

The foundation every other foley layer decodes/encodes/transforms audio through.
It commits to a small, explicit set of representations (report 09):

    * **Working** (in RAM, between DSP ops): a ``float32`` NumPy array at
      ``48 kHz`` — shape ``(frames,)`` mono or ``(frames, channels)``. This is
      the lingua franca of ``soundfile``/``librosa``/``soxr`` and exactly what
      CLAP expects.
    * **Archive** (bytes at rest): **FLAC**, source sample-rate and bit-depth
      preserved — lossless, ~40-60% smaller than WAV, self-describing.
    * **Delivery / preview** (derived): **Opus** by default (not implemented in
      the foundation — an FFmpeg/`foley[ffmpeg]` concern surfaced later).

Design rules honoured here:

    * **Zero-dep import.** This module imports only the stdlib at top level; the
      heavy libraries (``numpy``, ``soundfile``, ``soxr``, ``librosa``,
      ``pyloudnorm``) are lazy-imported *inside* the functions that need them, so
      ``import foley.audio`` always succeeds on a bare install and only the
      function you call pays for (and requires) its dependency.
    * **No magic numbers.** Every default (sample rate, dtype, archive subtype,
      resample quality, trim/fade/loudness targets) is a named module-level
      constant used as a keyword-only argument default.
    * **Never bundle FFmpeg / pydub / torchaudio.** MP3/AAC/Opus transcode is an
      optional external-tool concern, not part of this royalty-free core.

All ops assume the working representation (float array, time on axis 0). ``load``
is the one function that produces it from arbitrary sources (path, raw bytes, or
a file-like object).
"""

from __future__ import annotations

import io
import math
import os
from typing import TYPE_CHECKING, BinaryIO, Callable, Optional, Union

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from numpy import ndarray

# ---------------------------------------------------------------------------
# Canonical representation + operation defaults (no literal hides in code)
# ---------------------------------------------------------------------------

WORKING_SAMPLE_RATE: int = 48_000  # CLAP + video/broadcast standard (report 09)
WORKING_DTYPE: str = "float32"  # float avoids clipping across chained DSP ops
ARCHIVE_FORMAT: str = "flac"  # lossless, small, metadata-rich, royalty-free
ARCHIVE_SUBTYPE: str = "PCM_24"  # recording-grade archive depth (24-bit)
DELIVERY_FORMAT: str = "opus"  # royalty-free preview codec (transcode = later)
RESAMPLE_QUALITY: str = "HQ"  # soxr preset: QQ | LQ | MQ | HQ | VHQ

TRIM_TOP_DB: float = 30.0  # librosa trim: silence = >= this many dB below peak
DEFAULT_FADE_S: float = 0.01  # 10 ms declick ramp at edit points
FADE_KIND: str = "linear"  # 'linear' | 'equal_power' (sqrt, for crossfades)

# Loudness targets (LUFS), each named so no literal hides in code.
LUFS_STREAMING: float = -14.0  # Spotify/YouTube-class streaming target
LUFS_PODCAST: float = -16.0  # foley default (matches WEAVE MasterProfile)
LUFS_EBU: float = -23.0  # EBU R128 broadcast target
LUFS_ATSC: float = -24.0  # ATSC A/85 broadcast target
DEFAULT_LOUDNESS_TARGET_LUFS: float = LUFS_PODCAST
TRUE_PEAK_MAX_DBTP: float = -1.0  # ceiling after loudness normalization
LUFS_GATE_FLOOR: float = -70.0  # pyloudnorm near-silent gate; flag, don't amplify
LUFS_MIN_BLOCK_S: float = 0.4  # BS.1770 gating block; shorter clips can't be measured
SILENT_PEAK_DBFS: float = -80.0  # a clip whose sample peak is under this is silent

#: A source ``load`` can decode: a filesystem path, raw encoded bytes, or an
#: already-open binary file-like object (e.g. ``io.BytesIO``).
AudioSource = Union[str, os.PathLike, bytes, BinaryIO]


# ---------------------------------------------------------------------------
# I/O — decode / encode between bytes/files and the working array
# ---------------------------------------------------------------------------


def load(
    src: AudioSource,
    *,
    target_sr: Optional[int] = None,
    mono: bool = False,
    dtype: str = WORKING_DTYPE,
) -> tuple["ndarray", int]:
    """Decode audio into a float working array.

    ``src`` may be a filesystem path, raw encoded ``bytes`` (wrapped in a
    ``BytesIO`` so nothing touches disk), or any binary file-like object.

    Args:
        src: Path, raw bytes, or file-like object to decode.
        target_sr: If given, resample the decoded audio to this rate (via
            :func:`resample`); otherwise the native rate is returned.
        mono: If ``True``, down-mix multichannel audio to mono.
        dtype: NumPy dtype string for the returned array (default ``float32``).

    Returns:
        A ``(samples, sample_rate)`` tuple. ``samples`` has shape ``(frames,)``
        (mono) or ``(frames, channels)``; ``sample_rate`` reflects any resample.

    Lazy dependencies: ``soundfile`` (and ``soxr`` when ``target_sr`` differs).
    """
    import soundfile as sf

    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(bytes(src))
    samples, sample_rate = sf.read(src, dtype=dtype, always_2d=False)
    if mono and samples.ndim == 2:
        samples = to_mono(samples)
    if target_sr is not None and target_sr != sample_rate:
        samples = resample(samples, sample_rate, target_sr=target_sr)
        sample_rate = target_sr
    return samples, sample_rate


def save(
    samples: "ndarray",
    sample_rate: int,
    dst: Union[str, os.PathLike, BinaryIO],
    *,
    fmt: str = ARCHIVE_FORMAT,
    subtype: str = ARCHIVE_SUBTYPE,
) -> None:
    """Write ``samples`` to ``dst`` as ``fmt``/``subtype`` (default = FLAC archive).

    Args:
        samples: The working array to write (shape ``(frames,)`` or
            ``(frames, channels)``).
        sample_rate: Sample rate in Hz.
        dst: Destination path or writable binary file-like object.
        fmt: Container/codec name (case-insensitive; passed to libsndfile).
        subtype: Sample subtype (e.g. ``PCM_24``, ``PCM_16``, ``FLOAT``).

    Lazy dependency: ``soundfile``.
    """
    import soundfile as sf

    sf.write(dst, samples, sample_rate, format=fmt.upper(), subtype=subtype)


def encode(
    samples: "ndarray",
    sample_rate: int,
    *,
    fmt: str = ARCHIVE_FORMAT,
    subtype: str = ARCHIVE_SUBTYPE,
) -> bytes:
    """Encode ``samples`` fully in memory and return the container bytes.

    This is the producer for the content-addressed byte store: default output is
    the FLAC archive form.

    Args:
        samples: The working array to encode.
        sample_rate: Sample rate in Hz.
        fmt: Container/codec name (case-insensitive).
        subtype: Sample subtype (e.g. ``PCM_24``).

    Returns:
        The encoded audio as ``bytes``.

    Lazy dependency: ``soundfile``.
    """
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format=fmt.upper(), subtype=subtype)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DSP primitives — resample / channels / trim / fade / loudness
# ---------------------------------------------------------------------------


def resample(
    samples: "ndarray",
    sample_rate: int,
    *,
    target_sr: int = WORKING_SAMPLE_RATE,
    quality: str = RESAMPLE_QUALITY,
) -> "ndarray":
    """Resample ``samples`` to ``target_sr`` (a no-op when already there).

    Args:
        samples: Working array (mono ``(frames,)`` or ``(frames, channels)``).
        sample_rate: The array's current rate in Hz.
        target_sr: Desired output rate in Hz (default = the working rate).
        quality: soxr quality preset (``QQ``/``LQ``/``MQ``/``HQ``/``VHQ``).

    Returns:
        The resampled array (the input unchanged when ``sample_rate ==
        target_sr``). dtype is preserved by soxr.

    Lazy dependency: ``soxr``.
    """
    if sample_rate == target_sr:
        return samples
    import soxr

    return soxr.resample(samples, sample_rate, target_sr, quality=quality)


def to_mono(samples: "ndarray") -> "ndarray":
    """Down-mix to mono by averaging channels; 1-D input passes through.

    Args:
        samples: Mono ``(frames,)`` or multichannel ``(frames, channels)`` array.

    Returns:
        A 1-D mono array (dtype preserved).
    """
    if samples.ndim == 2:
        return samples.mean(axis=1)
    return samples


def ensure_channels(samples: "ndarray", *, channels: int) -> "ndarray":
    """Coerce ``samples`` to exactly ``channels`` channels.

    Mappings: mono -> N by duplication; N -> mono by mean; N -> M (N != M, both
    > 1) by collapsing to mono then tiling up to M.

    Args:
        samples: Mono or multichannel working array.
        channels: Target channel count (must be >= 1).

    Returns:
        A ``(frames,)`` array when ``channels == 1``, else a
        ``(frames, channels)`` array.

    Raises:
        ValueError: If ``channels < 1``.

    Lazy dependency: ``numpy`` (only for the up-mix / tile path).
    """
    if channels < 1:
        raise ValueError(f"channels must be >= 1, got {channels}")
    current = 1 if samples.ndim == 1 else samples.shape[1]
    if channels == 1:
        return to_mono(samples)
    if samples.ndim == 2 and current == channels:
        return samples
    import numpy as np

    mono = to_mono(samples)  # 1-D
    return np.tile(mono[:, None], (1, channels))


def trim_silence(
    samples: "ndarray",
    sample_rate: int,
    *,
    top_db: float = TRIM_TOP_DB,
) -> tuple["ndarray", tuple[int, int]]:
    """Strip leading/trailing silence, returning the clip and its kept span.

    Silence detection runs on a transient mono down-mix (so librosa's time-last
    convention never clashes with foley's time-first ``(frames, channels)``
    layout); the returned sample indices then slice the *original* array along
    axis 0, preserving its channel layout.

    Args:
        samples: Working array (mono or multichannel).
        sample_rate: Sample rate in Hz (kept in the signature for API symmetry;
            trimming is index-based).
        top_db: A frame is silent when it sits at least this many dB below the
            reference (peak) level.

    Returns:
        ``(trimmed, (start_sample, end_sample))``. On all-silent (or otherwise
        degenerate) input the original array is returned unchanged with a
        full-length span ``(0, len(samples))``.

    Lazy dependency: ``librosa``.
    """
    import librosa

    n = samples.shape[0]
    mono = to_mono(samples)
    _, index = librosa.effects.trim(mono, top_db=top_db)
    start, end = int(index[0]), int(index[1])
    if end <= start:  # degenerate / all-silent guard
        return samples, (0, n)
    return samples[start:end], (start, end)


def _fade_ramp(length: int, *, dtype: object, kind: str) -> "ndarray":
    """Return an ascending 0->1 gain ramp of ``length`` samples.

    Args:
        length: Number of samples in the ramp.
        dtype: NumPy dtype for the ramp (matches the signal being faded).
        kind: ``'linear'`` or ``'equal_power'`` (square-root of the linear ramp,
            for dip-free crossfades).

    Returns:
        A 1-D ramp array rising from 0.0 to 1.0.
    """
    import numpy as np

    ramp = np.linspace(0.0, 1.0, length, dtype=dtype)
    if kind == "equal_power":
        return np.sqrt(ramp)
    return ramp


def fade(
    samples: "ndarray",
    sample_rate: int,
    *,
    fade_in_s: float = DEFAULT_FADE_S,
    fade_out_s: float = DEFAULT_FADE_S,
    kind: str = FADE_KIND,
) -> "ndarray":
    """Apply in/out gain ramps to ``samples`` (a short declick by default).

    Ramp lengths are clamped to at most ``len(samples) // 2`` so the in- and
    out-ramps never overlap on tiny inputs.

    Args:
        samples: Working array (mono or multichannel).
        sample_rate: Sample rate in Hz (converts the fade durations to samples).
        fade_in_s: Fade-in duration in seconds.
        fade_out_s: Fade-out duration in seconds.
        kind: ``'linear'`` or ``'equal_power'`` ramp shape.

    Returns:
        A new array with the fade envelope applied (input is not mutated).

    Lazy dependency: ``numpy``.
    """
    import numpy as np

    n = samples.shape[0]
    max_ramp = n // 2
    n_in = min(int(fade_in_s * sample_rate), max_ramp)
    n_out = min(int(fade_out_s * sample_rate), max_ramp)

    env = np.ones(n, dtype=samples.dtype)
    if n_in > 0:
        env[:n_in] = _fade_ramp(n_in, dtype=samples.dtype, kind=kind)
    if n_out > 0:
        env[-n_out:] = _fade_ramp(n_out, dtype=samples.dtype, kind=kind)[::-1]

    return samples * env[:, None] if samples.ndim == 2 else samples * env


def limit_true_peak(
    samples: "ndarray",
    sample_rate: int,
    *,
    ceiling_dbtp: float = TRUE_PEAK_MAX_DBTP,
    oversample: Optional[int] = None,
) -> tuple["ndarray", float]:
    """Attenuate ``samples`` so their inter-sample true peak sits at or below ``ceiling_dbtp``.

    A **static** gain — the whole clip is turned down by one factor, never boosted —
    which is transparent and exactly what a Tier-0 range fault needs: after it, a
    flat-topped run or an over-ceiling peak is no longer at full scale. It is not a
    dynamic look-ahead limiter (a shared one is planned: foley#91), so the distortion
    of a heavily clipped clip stays in the waveform; that is why :mod:`foley.repair`
    applies it only to a clip just over the clipping gate.

    Args:
        samples: Working array (mono or multichannel).
        sample_rate: Sample rate in Hz (passed to the true-peak measurement).
        ceiling_dbtp: The true-peak ceiling in dBTP (default: foley's -1 dBTP).
        oversample: Oversampling factor for the true-peak estimate (default: the
            QC table's ``true_peak_oversample``).

    Returns:
        ``(attenuated, gain_db)``. ``gain_db`` is ``0.0`` — and ``samples`` comes back
        as is — when the clip is already under the ceiling or is silent.

    Lazy dependency: ``numpy`` (via :func:`foley.qc.true_peak_dbtp`).
    """
    from .qc import DEFAULT_QC_THRESHOLDS, true_peak_dbtp

    if oversample is None:
        oversample = DEFAULT_QC_THRESHOLDS.true_peak_oversample
    peak = true_peak_dbtp(samples, sample_rate, oversample=oversample)
    if not math.isfinite(peak) or peak <= ceiling_dbtp:
        return samples, 0.0
    gain_db = float(ceiling_dbtp - peak)
    return samples * (10.0 ** (gain_db / 20.0)), gain_db


#: A loudness meter: ``(samples, sample_rate) -> integrated LUFS`` (time on axis 0).
Meter = Callable[["ndarray", int], float]


def pyloudnorm_meter(samples: "ndarray", sample_rate: int) -> float:
    """The default :data:`Meter`: ``pyloudnorm`` (lazy), BS.1770-4 integrated loudness."""
    import pyloudnorm as pyln

    return float(pyln.Meter(sample_rate).integrated_loudness(samples))


def integrated_lufs(
    samples: "ndarray",
    sample_rate: int,
    *,
    min_block_s: float = LUFS_MIN_BLOCK_S,
    meter: Optional[Meter] = None,
) -> float:
    """Integrated loudness (LUFS, BS.1770-4) of ``samples``; ``-inf`` when too short to gate.

    The one measurer :func:`loudness_gain_db` and the WEAVE master share. The length
    guard uses ``math.ceil`` (not ``int(round)``) to mirror pyloudnorm's float threshold
    ``n < block_size*rate`` at every sample rate, including rates where ``0.4*sr`` is
    not integral; identical to ``int(round)`` at all standard (÷5) rates.

    ``meter`` (default :func:`pyloudnorm_meter`) is the seam for another BS.1770
    implementation (foley#91); the too-short guard stays here, outside the meter, so
    every meter sees the same clips.

    Lazy dependency: ``pyloudnorm`` (default meter only).
    """
    if samples.shape[0] < math.ceil(min_block_s * sample_rate):
        return float("-inf")
    return float((meter or pyloudnorm_meter)(samples, sample_rate))


def loudness_gain_db(
    samples: "ndarray",
    sample_rate: int,
    *,
    target_lufs: float,
    peak_ceiling_dbfs: float = TRUE_PEAK_MAX_DBTP,
    short_peak_dbfs: Optional[float] = None,
    max_boost_db: Optional[float] = None,
    min_block_s: float = LUFS_MIN_BLOCK_S,
    gate_floor_lufs: float = LUFS_GATE_FLOOR,
    silent_peak_dbfs: float = SILENT_PEAK_DBFS,
    meter: Optional[Meter] = None,
) -> tuple[float, float]:
    """The one loudness-gain rule: ``(gain_db, measured_lufs)`` to bring a clip to a target.

    The policy for short, near-silent and high-crest clips lives here, and
    :func:`loudness_normalize` and :func:`foley.level.reference_gain_db` both apply it:

    * a silent (peak at or under ``silent_peak_dbfs``) or non-finite clip: ``0.0``;
    * integrated loudness (BS.1770-4, gated) at or under ``gate_floor_lufs``:
      near-silent, ``0.0`` (flag, don't amplify);
    * a clip shorter than one gating block (``min_block_s``) cannot be measured
      (``measured = -inf``): with ``short_peak_dbfs`` it is levelled by its sample peak
      to that level, without it ``0.0``;
    * otherwise ``target_lufs - measured``;

    and a non-zero gain is capped so the sample peak stays at or under
    ``peak_ceiling_dbfs`` (a high-crest clip is held back) and, when ``max_boost_db`` is
    given, the boost at that many dB. ``meter`` swaps the loudness measurer (see
    :data:`Meter`). Pure and deterministic.

    Returns:
        ``(gain_db, measured_lufs)``; ``measured_lufs`` is ``-inf`` for a clip too short
        to measure, a value at or under :data:`LUFS_GATE_FLOOR` for a near-silent one.

    Lazy dependencies: ``pyloudnorm`` (+ ``numpy``).
    """
    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0 or not np.isfinite(x).all():
        return 0.0, float("-inf")
    peak = float(np.max(np.abs(x)))
    peak_db = 20.0 * math.log10(peak) if peak > 0 else float("-inf")
    if peak_db <= silent_peak_dbfs:
        return 0.0, float("-inf")

    measured = integrated_lufs(x, sample_rate, min_block_s=min_block_s, meter=meter)
    if measured == float("-inf") and x.shape[0] < math.ceil(min_block_s * sample_rate):
        if short_peak_dbfs is None:
            return 0.0, measured  # too short to gate; flag, don't amplify
        wanted = short_peak_dbfs - peak_db
    elif measured <= gate_floor_lufs:  # near-silent: flag, don't amplify
        return 0.0, measured
    else:
        wanted = target_lufs - measured

    gain = min(wanted, peak_ceiling_dbfs - peak_db)
    if max_boost_db is not None:
        gain = min(gain, max_boost_db)
    return float(gain), measured


def loudness_normalize(
    samples: "ndarray",
    sample_rate: int,
    *,
    target_lufs: float = DEFAULT_LOUDNESS_TARGET_LUFS,
    peak_ceiling_dbfs: float = TRUE_PEAK_MAX_DBTP,
    min_block_s: float = LUFS_MIN_BLOCK_S,
    meter: Optional[Meter] = None,
) -> tuple["ndarray", float]:
    """Loudness-normalize to ``target_lufs``, then keep it peak-safe.

    Integrated loudness is measured (ITU-R BS.1770-4 / EBU R128), the signal is
    scaled to ``target_lufs``, and finally attenuated so its sample peak sits at
    or below ``peak_ceiling_dbfs``: the gain is :func:`loudness_gain_db`. Inputs are
    returned **unchanged** (flag them, don't amplify) when silent or non-finite,
    near-silent (measured loudness at or below ``LUFS_GATE_FLOOR``), or shorter than one
    BS.1770 gating block (``min_block_s``) — which ``pyloudnorm`` cannot measure and
    would otherwise raise ``ValueError`` on (routine for one-shots: clicks, blips,
    gunshots).

    Args:
        samples: Working array (mono or multichannel, time on axis 0 — the layout
            pyloudnorm expects).
        sample_rate: Sample rate in Hz.
        target_lufs: Desired integrated loudness (default = foley's podcast
            target).
        peak_ceiling_dbfs: Sample-peak ceiling (dBFS) applied after loudness
            normalization. Note this is a *sample*-peak limit, not an inter-sample
            true-peak (dBTP) limit — see :func:`foley.qc.true_peak_dbtp` for the
            oversampled measurement.
        min_block_s: Minimum clip length (seconds) that can be loudness-measured;
            shorter clips are returned unchanged with ``measured = -inf``.
        meter: A :data:`Meter` (default ``pyloudnorm``).

    Returns:
        ``(normalized, measured_input_lufs)``. When the input is near-silent or
        too short to measure, ``normalized`` is the unchanged input and
        ``measured_input_lufs`` is at or below ``LUFS_GATE_FLOOR`` (``-inf`` for
        the too-short case).

    Lazy dependencies: ``pyloudnorm`` (+ ``numpy``).
    """
    gain_db, measured = loudness_gain_db(
        samples,
        sample_rate,
        target_lufs=target_lufs,
        peak_ceiling_dbfs=peak_ceiling_dbfs,
        min_block_s=min_block_s,
        meter=meter,
    )
    if measured <= LUFS_GATE_FLOOR:  # silent, too short or near-silent: unchanged
        return samples, measured
    return samples * (10.0 ** (gain_db / 20.0)), measured


def to_working(
    samples: "ndarray",
    sample_rate: int,
    *,
    mono: bool = True,
    target_sr: int = WORKING_SAMPLE_RATE,
    dtype: str = WORKING_DTYPE,
) -> "ndarray":
    """Produce the canonical CLAP/QC working array from an arbitrary clip.

    Down-mixes (when ``mono``), resamples to ``target_sr``, and casts to
    ``dtype`` — the ``float32`` @ 48 kHz mono array every embedder/tagger/QC
    check consumes.

    Args:
        samples: Decoded working array (mono or multichannel).
        sample_rate: The array's current rate in Hz.
        mono: If ``True``, down-mix to mono.
        target_sr: Working sample rate in Hz.
        dtype: Output NumPy dtype string.

    Returns:
        The canonical working array.

    Lazy dependency: ``soxr`` (only when ``sample_rate != target_sr``).
    """
    if mono:
        samples = to_mono(samples)
    samples = resample(samples, sample_rate, target_sr=target_sr)
    return samples.astype(dtype, copy=False)
