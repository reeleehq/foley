"""A diegetic broadcast bed: speech lines heard through a radio/TV/PA/phone over a bed (#108).

A scene needs "the car radio": a commentator's lines over a stadium crowd, coloured as
the device that plays them, looped for the scene. :func:`broadcast_bed` makes it in one
call and returns a :class:`BroadcastBed` whose licence carries the rights of **both**
sources, narrowed, never widened::

    bed = foley.broadcast_bed(
        [line1, line2],                      # speech already spoken (arrays, bytes, paths)
        bed_prompt="football stadium crowd", # or bed=<library id or audio>
        speech_license=speech_rights,        # the speech's provenance, as given
        duration=90.0,
    )
    bed.audio, bed.sr, bed.license

The pipeline is small pure stages, each its own function:

1. **speech** — each line becomes a mono clip at ``sr`` (:func:`as_clip`); lines given as
   text go through the injected ``tts=`` seam first. :func:`join_lines` puts ``gap_s`` of
   silence after each line.
2. **bed** — a library sound id, raw bed audio (with its ``bed_license``), or
   ``bed_prompt`` through :func:`foley.generate` (budget, consent and licence rules
   unchanged; the ``generate=`` seam replaces it in tests).
3. **mix** — :func:`mix_program` loops speech and bed to ``duration`` (the WEAVE
   :func:`~foley.weave.mix.fit_duration` loop with its equal-power seam) and sets the bed
   ``bed_under_speech_db`` below the speech by integrated loudness.
4. **treatment** — the whole program goes through the device (a radio colours the crowd
   it carries as much as the voice): a named :class:`TreatmentPreset` from
   :data:`TREATMENTS` (band-pass -> RMS compressor -> lookahead peak limiter), or any
   ``(samples, sr) -> samples`` callable.

**The treatment is a seam.** It is an audio "look" with no foley-specific knowledge, so
its eventual home is the fleet's audio package (``mixing``, beside
:mod:`mixing.loudness`), not foley; until it lands there, foley's in-house preset chain
is the default (numpy + scipy, which ``foley[audio]`` already brings through
``mixing[loudness]``; the limiter *is* :func:`mixing.loudness.limit_peaks`). Swapping in
the fleet's one is ``treatment=<its callable>``.

**Text-to-speech is a seam with no default.** ``tts`` is any ``text -> audio`` callable
(an array at ``sr``, ``(samples, sr)``, encoded bytes, or a path); foley adds no TTS
dependency. Two that exist in the fleet::

    import voxy
    tts = lambda text: voxy.text_to_speech(text, "commentator").audio  # encoded bytes

    from an.audio.elevenlabs_tts import ElevenLabsTTS
    eleven = ElevenLabsTTS(output_format="pcm_44100")  # a format soundfile decodes
    tts = lambda text: eleven.synthesize(text, VOICE_ID).bytes_

The speech's rights are never inferred from the TTS call: pass them as
``speech_license`` (e.g. a :class:`~foley.base.LicenseRecord` for the TTS vendor's
terms). Without it the result is fail-closed: the speech counts as unknown rights.

Import cost: stdlib + :mod:`foley.base` only; numpy, scipy and :mod:`mixing.loudness`
are imported inside the functions that need them, so ``import foley.weave`` stays
dol-only.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Union

from ..base import LicenseRecord, SoundRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

# --- named defaults (no literal hides in code) -------------------------------------
#: Silence after each spoken line (s); the 0.6 s that read naturally in the #108 starter.
LINE_GAP_S: float = 0.6
#: Where the bed sits under the speech, in LU of integrated loudness (#108: -12 dB).
BED_UNDER_SPEECH_DB: float = -12.0
#: Equal-power crossfade at each loop seam of the speech and the bed (s).
LOOP_CROSSFADE_S: float = 0.05
#: The device a broadcast is heard through when none is named.
DEFAULT_TREATMENT: str = "am_radio"
#: Butterworth order of the treatment's band-pass (per edge).
FILTER_ORDER: int = 4
#: The band-pass's upper edge is held under this fraction of Nyquist (a low ``sr``).
MAX_CUTOFF_NYQUIST_FRACTION: float = 0.95
#: Time constant of the compressor's RMS level detector (s).
COMPRESSOR_DETECTOR_S: float = 0.02
#: The treatment's peak ceiling (dBFS) after make-up gain.
TREATMENT_CEILING_DB: float = -1.0
#: Floor of the compressor's level detector, so silence has a finite level (dBFS).
DETECTOR_FLOOR_DB: float = -120.0
#: The ``transformations`` op recorded on the result's licence.
BROADCAST_OP: str = "broadcast_bed"


# --- treatment: the device the broadcast is heard through ---------------------------


@dataclass(frozen=True)
class TreatmentPreset:
    """A diegetic-source colouring: band-pass -> RMS compressor -> make-up -> limiter.

    Callable as ``preset(samples, sample_rate)``, so a preset is just one value of the
    ``treatment=`` strategy (any ``(samples, sr) -> samples`` callable is another).

    Attributes:
        name: The preset's name (recorded on the result's licence).
        highpass_hz: Lower edge of the device's passband (Hz).
        lowpass_hz: Upper edge of the device's passband (Hz).
        threshold_db: Compressor threshold (dBFS of the RMS detector).
        ratio: Compressor ratio above the threshold (``1`` = none).
        makeup_db: Gain after the compressor (dB).
        filter_order: Butterworth order of the band-pass.
        detector_s: RMS detector time constant (s).
        ceiling_db: Peak ceiling of the final limiter (dBFS).
    """

    name: str
    highpass_hz: float
    lowpass_hz: float
    threshold_db: float
    ratio: float
    makeup_db: float = 0.0
    filter_order: int = FILTER_ORDER
    detector_s: float = COMPRESSOR_DETECTOR_S
    ceiling_db: float = TREATMENT_CEILING_DB

    def __call__(self, samples: "ndarray", sample_rate: int) -> "ndarray":
        return apply_treatment(samples, sample_rate, self)


#: The named devices. Passbands: ``am_radio`` is the #108 starter's chain (highpass 450,
#: lowpass 3200); ``phone`` is the narrowband telephone channel (300-3400 Hz, ITU-T
#: G.712); ``tv`` a small TV speaker; ``pa`` a horn loudspeaker, squashed hardest.
TREATMENTS: "dict[str, TreatmentPreset]" = {
    p.name: p
    for p in (
        TreatmentPreset(
            "am_radio", 450.0, 3200.0, threshold_db=-24.0, ratio=4.0, makeup_db=6.0
        ),
        TreatmentPreset(
            "tv", 150.0, 7000.0, threshold_db=-20.0, ratio=3.0, makeup_db=4.0
        ),
        TreatmentPreset(
            "pa", 400.0, 4000.0, threshold_db=-26.0, ratio=6.0, makeup_db=8.0
        ),
        TreatmentPreset(
            "phone", 300.0, 3400.0, threshold_db=-22.0, ratio=4.0, makeup_db=6.0
        ),
    )
}

#: What ``treatment=`` takes: a :data:`TREATMENTS` name, a :class:`TreatmentPreset`,
#: any ``(samples, sr) -> samples`` callable, or ``None`` (dry, no device).
Treatment = Union[str, TreatmentPreset, Callable[["ndarray", int], "ndarray"], None]


def _band_pass(samples, sample_rate: int, preset: TreatmentPreset):
    """Butterworth band-pass along axis 0 (causal, as the device is)."""
    from scipy.signal import butter, sosfilt

    nyquist = sample_rate / 2.0
    high = min(preset.lowpass_hz, MAX_CUTOFF_NYQUIST_FRACTION * nyquist)
    if not 0 < preset.highpass_hz < high:
        raise ValueError(
            f"treatment {preset.name!r}: passband {preset.highpass_hz}-{high} Hz is empty "
            f"at {sample_rate} Hz"
        )
    sos = butter(
        preset.filter_order,
        [preset.highpass_hz, high],
        btype="bandpass",
        fs=sample_rate,
        output="sos",
    )
    return sosfilt(sos, samples, axis=0)


def _compress(samples, sample_rate: int, preset: TreatmentPreset):
    """Feed-forward compressor on a one-pole RMS detector (channels linked)."""
    import numpy as np
    from scipy.signal import lfilter

    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    a = float(np.exp(-1.0 / max(1.0, preset.detector_s * sample_rate)))
    power = lfilter([1.0 - a], [1.0, -a], mono.astype("float64") ** 2)
    floor = 10.0 ** (DETECTOR_FLOOR_DB / 10.0)
    level_db = 10.0 * np.log10(np.maximum(power, floor))
    over = np.maximum(0.0, level_db - preset.threshold_db)
    gain = 10.0 ** ((-over * (1.0 - 1.0 / preset.ratio) + preset.makeup_db) / 20.0)
    return samples * (gain if samples.ndim == 1 else gain[:, None])


def _limit(samples, sample_rate: int, ceiling_db: float):
    """Peak-limit to ``ceiling_db`` with the shared lookahead limiter (mixing.loudness)."""
    from ..audio import loudness_component

    data = samples if samples.ndim == 2 else samples[:, None]
    limited = loudness_component().limit_peaks(
        data, ceiling=10.0 ** (ceiling_db / 20.0), fs=sample_rate
    )
    return limited if samples.ndim == 2 else limited[:, 0]


def apply_treatment(
    samples: "ndarray", sample_rate: int, preset: TreatmentPreset
) -> "ndarray":
    """Colour ``samples`` as heard through ``preset``'s device (mono or ``(n, ch)``).

    Band-pass -> RMS compressor with make-up gain -> lookahead peak limiter
    (:func:`mixing.loudness.limit_peaks`). Returns ``float32``, same shape.

    Lazy dependencies: numpy, scipy, ``mixing[loudness]`` (all in ``foley[audio]``).
    """
    import numpy as np

    if samples.shape[0] == 0:
        return samples.astype("float32")
    shaped = _compress(_band_pass(samples, sample_rate, preset), sample_rate, preset)
    return np.asarray(_limit(shaped, sample_rate, preset.ceiling_db), dtype="float32")


def resolve_treatment(treatment: Treatment) -> Callable[["ndarray", int], "ndarray"]:
    """``treatment=`` as a ``(samples, sr) -> samples`` callable (``None``: dry).

    >>> resolve_treatment("phone").name
    'phone'
    >>> resolve_treatment(None)(1, 2)
    1
    """
    if treatment is None:
        return lambda samples, sample_rate: samples
    if isinstance(treatment, str):
        try:
            return TREATMENTS[treatment]
        except KeyError:
            raise ValueError(
                f"unknown treatment {treatment!r}; one of {sorted(TREATMENTS)}, "
                "a TreatmentPreset, or a (samples, sr) -> samples callable"
            ) from None
    if callable(treatment):
        return treatment
    raise TypeError(
        f"treatment must be a name, a preset or a callable, not {treatment!r}"
    )


def _treatment_name(treatment: Treatment) -> str:
    """The device's name as recorded on the result (``'dry'`` for none)."""
    if treatment is None or isinstance(treatment, str):
        return treatment or "dry"
    return getattr(treatment, "name", None) or getattr(
        treatment, "__name__", type(treatment).__name__
    )


# --- speech --------------------------------------------------------------------------

#: One clip: an array at ``sr``, ``(samples, its_sr)``, encoded bytes, or a file path.
ClipLike = Union["ndarray", tuple, bytes, str, os.PathLike]


def as_clip(item: ClipLike, sample_rate: int) -> "ndarray":
    """``item`` as a mono ``float32`` working array at ``sample_rate``.

    A bare array is taken to be at ``sample_rate`` already; ``(samples, sr)`` is
    resampled; bytes and paths are decoded with :func:`foley.audio.load`.
    """
    from ..audio import load, to_working

    if isinstance(item, tuple) and len(item) == 2:
        samples, orig = item
    elif isinstance(item, (bytes, bytearray, str, os.PathLike)):
        samples, orig = load(bytes(item) if isinstance(item, bytearray) else item)
    else:
        samples, orig = item, sample_rate
    return to_working(samples, orig, mono=True, target_sr=sample_rate)


def join_lines(
    clips: "Sequence[ndarray]", sample_rate: int, *, gap_s: float = LINE_GAP_S
) -> "ndarray":
    """Concatenate mono ``clips`` with ``gap_s`` of silence after each one.

    >>> import numpy as np
    >>> join_lines([np.ones(2), np.ones(3)], 10, gap_s=0.1).tolist()
    [1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0]
    """
    import numpy as np

    gap = np.zeros(max(0, int(round(gap_s * sample_rate))), dtype="float32")
    parts = [p for clip in clips for p in (np.asarray(clip, dtype="float32"), gap)]
    return np.concatenate(parts) if parts else gap[:0]


def _speak(lines, sample_rate: int, tts) -> "list[ndarray]":
    """Each line as a clip: through ``tts`` when given, else as audio (never as text)."""
    clips = []
    for i, line in enumerate(lines):
        if tts is not None:
            line = tts(line)
        elif isinstance(line, str) and not os.path.exists(line):
            raise ValueError(
                f"line {i} is text, not audio ({line[:40]!r}): pass tts= (a text -> "
                "audio callable) or the spoken audio"
            )
        clips.append(as_clip(line, sample_rate))
    return clips


# --- bed -----------------------------------------------------------------------------


def _unknown_rights(source: str) -> LicenseRecord:
    """A fail-closed licence for a source whose rights were not given."""
    from ..licensing import apply_license_flags

    return apply_license_flags(LicenseRecord(source=source, license_id="unknown"))


def _resolve_bed(
    bed, bed_prompt, *, bed_license, library, generate, generate_options, sample_rate
):
    """``(samples, provenance, notes)`` for the bed, from exactly one of its three forms."""
    from .render import load_clip_mono

    if (bed is None) == (bed_prompt is None):
        raise ValueError(
            "give exactly one of bed= (a sound id or audio) and bed_prompt="
        )
    if bed_prompt is not None:
        if generate is None:
            from .. import generate
        cand = generate(bed_prompt, library=library, **(generate_options or {}))
        record = cand.sound
        if getattr(cand, "audio_bytes", None):  # a store=False preview holds its bytes
            return as_clip(cand.audio_bytes, sample_rate), record, list(cand.notes)
        lib = library if library is not None else _default_library()
        return load_clip_mono(lib, record.id, sr=sample_rate), record, list(cand.notes)
    if isinstance(bed, str) and not os.path.exists(bed):  # a sound id, not a file
        if bed_license is not None:
            raise ValueError(
                "bed_license= is for raw bed audio; a library sound carries its own licence"
            )
        lib = library if library is not None else _default_library()
        if bed not in lib:
            raise KeyError(f"bed {bed!r} is neither a file nor a sound in the library")
        return load_clip_mono(lib, bed, sr=sample_rate), lib[bed], []
    notes = []
    if bed_license is None:
        bed_license = _unknown_rights("bed")
        notes.append(
            "bed rights not given (bed_license=): treated as unknown, fail-closed"
        )
    return as_clip(bed, sample_rate), bed_license, notes


def _default_library():
    from ..index import default_library

    return default_library()


# --- mix -----------------------------------------------------------------------------


def _exact(x: "ndarray", n: int) -> "ndarray":
    """``x`` trimmed or zero-padded to exactly ``n`` frames."""
    import numpy as np

    if x.shape[0] >= n:
        return x[:n]
    return np.concatenate([x, np.zeros(n - x.shape[0], dtype=x.dtype)])


def bed_gain_db(
    speech: "ndarray",
    bed: "ndarray",
    sample_rate: int,
    *,
    under_db: float = BED_UNDER_SPEECH_DB,
) -> "tuple[float, Optional[str]]":
    """The gain that puts ``bed`` ``under_db`` below ``speech`` in integrated loudness.

    Returns ``(gain_db, note)``. When either is too short or too quiet to measure, the
    gain is ``under_db`` applied to the bed as is, and ``note`` says so. A boost is
    capped at :data:`mixing.loudness.MAX_GAIN_DB`.
    """
    import math

    from ..audio import integrated_lufs, loudness_component

    speech_lufs = integrated_lufs(speech, sample_rate)
    bed_lufs = integrated_lufs(bed, sample_rate)
    if not (math.isfinite(speech_lufs) and math.isfinite(bed_lufs)):
        return under_db, (
            f"speech or bed too short/quiet to measure: bed at {under_db} dB as is"
        )
    gain = speech_lufs + under_db - bed_lufs
    return min(gain, loudness_component().MAX_GAIN_DB), None


def mix_program(
    speech: "ndarray",
    bed: "ndarray",
    sample_rate: int,
    *,
    duration: Optional[float] = None,
    bed_under_speech_db: float = BED_UNDER_SPEECH_DB,
    loop_speech: bool = True,
    crossfade_s: float = LOOP_CROSSFADE_S,
) -> "tuple[ndarray, list[str]]":
    """Speech over the bed, both fitted to ``duration`` (default: the speech's length).

    The bed always loops (seamless, equal-power seams); the speech loops too when
    ``loop_speech``, else plays once and the bed carries on. Returns ``(mono, notes)``.
    """
    from .mix import db_to_lin, fit_duration

    if bed.shape[0] == 0:
        raise ValueError("the bed is empty")
    n = (
        speech.shape[0]
        if duration is None
        else max(0, int(round(duration * sample_rate)))
    )
    span = n / sample_rate
    speech_track = _exact(
        fit_duration(
            speech,
            sample_rate,
            duration=span,
            loop=loop_speech,
            crossfade_s=crossfade_s,
        ),
        n,
    )
    bed_track = _exact(
        fit_duration(
            bed, sample_rate, duration=span, loop=True, crossfade_s=crossfade_s
        ),
        n,
    )
    gain, note = bed_gain_db(speech, bed, sample_rate, under_db=bed_under_speech_db)
    return speech_track + bed_track * db_to_lin(gain), [note] if note else []


# --- provenance ----------------------------------------------------------------------


def _license_of(source) -> LicenseRecord:
    return source.license if isinstance(source, SoundRecord) else source


def broadcast_license(
    bed: "SoundRecord | LicenseRecord",
    speech: Optional[LicenseRecord],
    *,
    treatment: str,
) -> LicenseRecord:
    """The broadcast's rights: the bed's, narrowed to the speech's (never widened).

    A copy of the bed's licence, narrowed to the speech's through the same lineage an
    edit records (:class:`foley.sources.edit.EditLineage`: the permissions both hold,
    either's attribution and notice, the stricter AI-use scope, and a ``transformations``
    entry the credits and content credential read as "derived from" the speech). It is
    AI-generated if either source is, its bytes may be stored only if both allow it, and
    its rights are verified only if both are. ``speech=None`` narrows to unknown rights.
    """
    from ..provenance.credits import attribution_line
    from ..sources.edit import EditLineage

    speech = speech if speech is not None else _unknown_rights("speech")
    out = copy.deepcopy(_license_of(bed))
    out.content_sha256 = None  # these bytes are the mix, not the bed
    EditLineage(
        op=BROADCAST_OP,
        source_id=speech.source_id,
        source_license=speech,
        source_credit=attribution_line(speech, fmt="plain"),
        params={"treatment": treatment, "role": "speech"},
    ).apply(out)
    out.is_ai_generated = out.is_ai_generated or speech.is_ai_generated
    out.cache_bytes_ok = out.cache_bytes_ok and speech.cache_bytes_ok
    out.rights_verified = out.rights_verified and speech.rights_verified
    return out


# --- the façade ----------------------------------------------------------------------


@dataclass
class BroadcastBed:
    """A rendered broadcast bed: the audio and the rights of everything in it.

    Attributes:
        audio: Mono ``float32`` samples.
        sr: Sample rate (Hz).
        license: The mix's rights (:func:`broadcast_license`): the bed's narrowed to the
            speech's, never wider than either.
        sources: ``(bed, speech)`` provenance as given: the bed's
            :class:`~foley.base.SoundRecord` (library or generated) or
            :class:`~foley.base.LicenseRecord`, and the speech's licence (``None`` if not
            given). For the credit line use :attr:`credits`, which reads both off
            ``license``.
        treatment: The device's name (``'dry'`` for none).
        notes: What the caller should know (unmeasurable levels, missing rights, the
            bed generation's own notes).
    """

    audio: "ndarray"
    sr: int
    license: LicenseRecord
    sources: tuple
    treatment: str
    notes: list = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        """Length of :attr:`audio` in seconds."""
        return self.audio.shape[0] / self.sr

    @property
    def credits(self):
        """The attribution :class:`~foley.provenance.Credits`: the bed, "derived from" the speech."""
        from ..provenance.credits import credits_for

        return credits_for([self.license])


def broadcast_bed(
    lines: Sequence,
    *,
    bed=None,
    bed_prompt: Optional[str] = None,
    treatment: Treatment = DEFAULT_TREATMENT,
    gap_s: float = LINE_GAP_S,
    duration: Optional[float] = None,
    bed_under_speech_db: float = BED_UNDER_SPEECH_DB,
    loop_speech: bool = True,
    crossfade_s: float = LOOP_CROSSFADE_S,
    speech_license: Optional[LicenseRecord] = None,
    bed_license: Optional[LicenseRecord] = None,
    tts: Optional[Callable[[str], ClipLike]] = None,
    library=None,
    generate: Optional[Callable] = None,
    generate_options: Optional[dict] = None,
    sr: Optional[int] = None,
) -> BroadcastBed:
    """Speech lines heard through a radio/TV/PA/phone over a bed, looped for a scene (#108).

    Args:
        lines: The spoken lines, in order: each an array at ``sr``, ``(samples, sr)``,
            encoded bytes or a path; or, with ``tts=``, text.
        bed: The bed: a library sound id, or its audio (any ``lines`` form).
        bed_prompt: Instead of ``bed``: a prompt for :func:`foley.generate` (its budget,
            paid-generation consent and licence gate apply unchanged).
        treatment: The device: a :data:`TREATMENTS` name (``'am_radio'`` default,
            ``'tv'``, ``'pa'``, ``'phone'``), a :class:`TreatmentPreset`, any
            ``(samples, sr) -> samples`` callable (e.g. the fleet's, once ``mixing`` has
            it), or ``None`` for dry. Applied to the whole program, crowd included.
        gap_s: Silence after each line (s).
        duration: Length of the result (s); ``None``: the lines once, with their gaps.
        bed_under_speech_db: The bed's level under the speech (LU, integrated loudness).
        loop_speech: Repeat the lines to fill ``duration`` (else they play once).
        crossfade_s: Equal-power crossfade at each loop seam (s).
        speech_license: The speech's rights, as given (e.g. the TTS vendor's terms).
            ``None``: unknown, so the result's rights fail closed.
        bed_license: The rights of raw bed audio given as ``bed`` (a library or
            generated bed carries its own).
        tts: A ``text -> audio`` callable that speaks text lines (no default: see the
            module docstring for voxy and an's ElevenLabs provider).
        library: Where a bed id is looked up and a generated bed is stored (default:
            the process-wide library).
        generate: The bed generator (default :func:`foley.generate`; a test seam).
        generate_options: Keyword arguments for it (``backend``, ``budget``,
            ``duration_s``, ``store``, ...).
        sr: Working sample rate (default :data:`foley.audio.WORKING_SAMPLE_RATE`).

    Returns:
        A :class:`BroadcastBed`.
    """
    from ..audio import WORKING_SAMPLE_RATE
    from .mix import declick

    sr = WORKING_SAMPLE_RATE if sr is None else sr
    device = resolve_treatment(treatment)  # fail fast on a bad name, before any spend
    if not lines:
        raise ValueError("no speech lines given")
    speech = join_lines(_speak(lines, sr, tts), sr, gap_s=gap_s)
    bed_audio, bed_source, notes = _resolve_bed(
        bed,
        bed_prompt,
        bed_license=bed_license,
        library=library,
        generate=generate,
        generate_options=generate_options,
        sample_rate=sr,
    )
    program, mix_notes = mix_program(
        speech,
        bed_audio,
        sr,
        duration=duration,
        bed_under_speech_db=bed_under_speech_db,
        loop_speech=loop_speech,
        crossfade_s=crossfade_s,
    )
    if speech_license is None:
        notes.append(
            "speech rights not given (speech_license=): treated as unknown, fail-closed"
        )
    name = _treatment_name(treatment)
    audio = declick(device(program, sr), sr).astype("float32", copy=False)
    return BroadcastBed(
        audio=audio,
        sr=sr,
        license=broadcast_license(bed_source, speech_license, treatment=name),
        sources=(bed_source, speech_license),
        treatment=name,
        notes=[*notes, *mix_notes],
    )
