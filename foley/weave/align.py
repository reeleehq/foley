"""Forced-alignment adapters — the ``Aligner`` seam's fake default + WhisperX real impl.

Forced alignment takes narration audio and its known transcript and returns
word-level timestamps (report 06 §2). foley ships two implementations behind the
:class:`~foley.weave.protocols.Aligner` seam, mirroring
:mod:`foley.agent.decompose`'s fake/real discipline exactly:

* :class:`FakeAligner` — the deterministic, **torch-free** default: it evenly
  spaces the transcript's words across the clip's duration. No model, no network,
  fully reproducible — so hermetic CI (and any bare install) gets a usable
  ``word_timeline`` with zero heavy dependencies.
* :class:`WhisperXAligner` — the real ≈±50 ms impl behind ``foley[align]``
  (``whisperx`` + ``torch``), lazy-imported inside its method so ``import
  foley.weave`` stays dol-only.

Montreal Forced Aligner and aeneas run as external programs
(:mod:`foley.weave.cli_aligners`); inject one with ``aligner=``.

:class:`SegmentedAligner` wraps any of them for narration made of segments whose
start offsets are known (one audio file per beat, concatenated): it aligns each
segment's words against that segment's own slice of the audio and shifts the
timings back, so even the fake spreads words over the right span.

``_default_aligner`` auto-upgrades to WhisperX when ``foley[align]`` is installed,
else falls back to the fake — the progressive-disclosure rule.
"""

from __future__ import annotations

import math
from functools import cached_property
from typing import TYPE_CHECKING, Optional, Sequence

from ..audio import resample, to_mono

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

    from .protocols import Aligner

#: Fallback speaking cadence used only when the clip's duration is unknown
#: (empty audio); otherwise :class:`FakeAligner` spreads words across the real
#: audio duration so its timings are audio-length-aware.
WORDS_PER_SECOND: float = 2.5

#: WhisperX runs alignment at 16 kHz mono (its wav2vec2 CTC model's native rate).
WHISPERX_SAMPLE_RATE: int = 16_000


class FakeAligner:
    """Deterministic, torch-free :class:`Aligner` — evenly spaces the transcript's words.

    The hermetic default: given a transcript, it returns one ``{'word','start','end'}``
    per whitespace token, spread uniformly across the clip's duration (or at
    :data:`WORDS_PER_SECOND` when the audio is empty). No transcript → an empty
    ``word_timeline`` (the render then falls back to absolute anchors).
    """

    name = "fake"

    def word_timeline(
        self,
        audio: "ndarray",
        sample_rate: int,
        *,
        transcript: Optional[str] = None,
        language: str = "en",
    ) -> "list[dict]":
        """Return an evenly-spaced word timeline for ``transcript`` over ``audio``'s duration."""
        words = (transcript or "").split()
        if not words:
            return []
        n = len(words)
        frames = (
            int(getattr(audio, "shape", [len(audio)])[0]) if audio is not None else 0
        )
        duration = (
            (frames / sample_rate)
            if (sample_rate and frames)
            else (n / WORDS_PER_SECOND)
        )
        step = duration / n
        return [
            {
                "word": w,
                "start": round(i * step, 6),
                "end": round((i + 1) * step, 6),
            }
            for i, w in enumerate(words)
        ]


def _offline_kwargs(whisperx) -> dict:
    """``{"local_files_only": True}`` under an offline posture, when whisperX accepts it."""
    import inspect

    from ..runtime import EXTERNAL, current_runtime

    if current_runtime().allows(EXTERNAL):
        return {}
    try:
        params = inspect.signature(whisperx.load_model).parameters
    except (TypeError, ValueError):  # pragma: no cover - a C-level callable
        return {}
    return {"local_files_only": True} if "local_files_only" in params else {}


class WhisperXAligner:
    """The real ≈±50 ms :class:`Aligner` (``foley[align]``) — faster-whisper ASR + wav2vec2 CTC.

    Lazy-imports ``whisperx`` inside :meth:`word_timeline` so ``import foley.weave``
    stays dol-only. Transcribes (if no transcript) then force-aligns at 16 kHz mono.
    The loaded models are kept on the instance (per model size, device and language),
    so aligning many clips, or a :class:`SegmentedAligner`'s segments, loads them once.

    Args:
        model_size: faster-whisper model name (``tiny``/``base``/``small``/…).
        device: ``'cpu'`` or ``'cuda'``.
        batch_size: Transcription batch size.
    """

    name = "whisperx"

    def __init__(
        self, *, model_size: str = "small", device: str = "cpu", batch_size: int = 16
    ):
        self.model_size = model_size
        self.device = device
        self.batch_size = batch_size
        self._models: "dict[tuple, tuple]" = {}

    def _loaded(self, whisperx, language: str) -> tuple:
        """``(asr_model, align_model, align_meta)`` for ``language``, loaded on first use."""
        key = (self.model_size, self.device, language)
        if key not in self._models:
            from ..runtime import no_download

            with no_download(
                f"the whisperX models ({self.model_size!r}, {language!r} alignment)",
                how_to_fetch="align one clip with foley.weave once while online.",
            ):
                model = whisperx.load_model(
                    self.model_size,
                    self.device,
                    language=language,
                    **_offline_kwargs(whisperx),
                )
                align_model, meta = whisperx.load_align_model(
                    language_code=language, device=self.device
                )
            self._models[key] = (model, align_model, meta)
        return self._models[key]

    def word_timeline(
        self,
        audio: "ndarray",
        sample_rate: int,
        *,
        transcript: Optional[str] = None,
        language: str = "en",
    ) -> "list[dict]":
        """Force-align ``audio`` to its transcript, returning word-level timestamps."""
        import whisperx  # lazy: foley[align]

        audio16 = resample(
            to_mono(audio), sample_rate, target_sr=WHISPERX_SAMPLE_RATE
        ).astype("float32")
        model, align_model, meta = self._loaded(whisperx, language)
        result = model.transcribe(audio16, batch_size=self.batch_size)
        aligned = whisperx.align(
            result["segments"], align_model, meta, audio16, self.device
        )
        return [
            {
                "word": w["word"],
                "start": float(w["start"]),
                "end": float(w["end"]),
            }
            for seg in aligned["segments"]
            for w in seg.get("words", [])
            if "start" in w and "end" in w
        ]


def _whisperx_available() -> bool:
    """True iff ``whisperx`` (the ``foley[align]`` extra) is importable."""
    import importlib.util

    return importlib.util.find_spec("whisperx") is not None


def aligner_name(aligner) -> str:
    """The aligner's ``name`` (``fake``, ``whisperx``, ``mfa``, …), else its class name (run manifest)."""
    return getattr(aligner, "name", None) or type(aligner).__name__


def _default_aligner() -> "Aligner":
    """The zero-config aligner: :class:`WhisperXAligner` when installed, else the fake."""
    return WhisperXAligner() if _whisperx_available() else FakeAligner()


def _validate_segment_starts(
    starts: "Sequence[float]", *, n_segments: int
) -> "tuple[float, ...]":
    """``starts`` as floats, checked: one per segment, finite, ``>= 0``, non-decreasing.

    >>> _validate_segment_starts([0, 2.5, 7], n_segments=3)
    (0.0, 2.5, 7.0)
    >>> _validate_segment_starts([0, 3, 2], n_segments=3)
    Traceback (most recent call last):
    ...
    ValueError: segment_starts must be non-decreasing: segment 2 starts at 2.0s, before segment 1 (3.0s)
    """
    out = tuple(float(s) for s in starts)
    if len(out) != n_segments:
        raise ValueError(
            f"segment_starts has {len(out)} value(s) for {n_segments} segment(s): "
            "give one start (seconds into the narration audio) per segment"
        )
    for i, s in enumerate(out):
        if not math.isfinite(s) or s < 0:
            raise ValueError(f"segment_starts[{i}] = {s!r}: must be finite and >= 0")
        if i and s < out[i - 1]:
            raise ValueError(
                f"segment_starts must be non-decreasing: segment {i} starts at {s}s, "
                f"before segment {i - 1} ({out[i - 1]}s)"
            )
    return out


def _segment_spans(
    starts: "Sequence[float]",
    word_counts: "Sequence[int]",
    *,
    duration: float,
    sample_rate: int,
) -> "list[tuple[float, float]]":
    """Each segment's ``(start, end)``, clipped to the audio; checked for worded segments.

    A segment ends where the next starts, the last at ``duration``. A segment with words
    must start before the audio's end and span at least one sample at ``sample_rate``
    (what its slice will hold); an empty one may lie anywhere.

    >>> _segment_spans([0, 4, 12], [3, 2, 0], duration=10, sample_rate=1000)
    [(0, 4), (4, 10), (12, 10)]
    """
    spans = [(s, min(e, duration)) for s, e in zip(starts, [*starts[1:], duration])]
    for i, ((s, e), n) in enumerate(zip(spans, word_counts)):
        if n and s >= duration:
            raise ValueError(
                f"segment {i} starts at {s}s, at or past the end of the narration "
                f"audio ({duration:.3f}s)"
            )
        if n and round(e * sample_rate) <= round(s * sample_rate):
            raise ValueError(
                f"segment {i} has {n} word(s) but no audio: it starts at {s}s and "
                f"the next segment at {e}s"
            )
    return spans


def _shifted(word: dict, offset: float) -> dict:
    """``word`` with its ``start``/``end`` moved ``offset`` seconds later."""
    return {
        **word,
        "start": round(float(word["start"]) + offset, 6),
        "end": round(float(word["end"]) + offset, 6),
    }


class SegmentedAligner:
    """An :class:`Aligner` for narration whose segments start at known offsets.

    Splits the transcript's words by segment (each segment's word count), aligns each
    piece with ``base`` against that segment's slice of the audio, and adds the slice's
    start to the timings. Segment ``i`` spans ``starts[i]`` to ``starts[i + 1]``; the
    last runs to the end of the audio; a segment with no words is skipped. Words keep the
    transcript's order, so anchors resolve exactly as with a whole-file aligner.

    ``base`` is called once per segment: :class:`WhisperXAligner` loads its models once
    and reuses them, but a subprocess aligner (:class:`~foley.weave.MFAAligner`,
    :class:`~foley.weave.AeneasAligner`) starts one process per segment.

    ``base`` must align the audio it is given: one that returns precomputed whole-file
    timings should be passed to ``weave(aligner=)`` directly, not wrapped.

    Args:
        starts: Each segment's start, in seconds into the narration audio (one per
            segment, non-decreasing).
        segments: The segments' texts; only their word counts are used, to split the
            transcript ``word_timeline`` receives.
        base: The aligner run on each slice (default: WhisperX if installed, else the
            fake, chosen at first use).
    """

    def __init__(
        self,
        starts: "Sequence[float]",
        segments: "Sequence[str]",
        *,
        base: "Optional[Aligner]" = None,
    ):
        self.word_counts = tuple(len(s.split()) for s in segments)
        self.starts = _validate_segment_starts(starts, n_segments=len(self.word_counts))
        self._base = base

    @cached_property
    def base(self) -> "Aligner":
        """The per-slice aligner (the injected one, else the zero-config default)."""
        return self._base if self._base is not None else _default_aligner()

    @property
    def name(self) -> str:
        """The base aligner's name, so weave's alignment notes describe the real timings."""
        return aligner_name(self.base)

    def split(self, transcript: Optional[str]) -> "list[list[str]]":
        """``transcript``'s words, one list per segment (``ValueError`` on a count mismatch)."""
        words = (transcript or "").split()
        if len(words) != sum(self.word_counts):
            raise ValueError(
                f"the transcript has {len(words)} word(s) but the segments have "
                f"{sum(self.word_counts)}: segment_starts needs a transcript that is "
                "the segments' words, in order"
            )
        ends = [sum(self.word_counts[: i + 1]) for i in range(len(self.word_counts))]
        return [words[a:b] for a, b in zip([0, *ends[:-1]], ends)]

    def spans(
        self, duration: float, *, sample_rate: int
    ) -> "list[tuple[float, float]]":
        """Each segment's ``(start, end)`` in audio of ``duration`` seconds (``ValueError``
        if a segment with words starts at or past the end, or spans no sample)."""
        return _segment_spans(
            self.starts, self.word_counts, duration=duration, sample_rate=sample_rate
        )

    def word_timeline(
        self,
        audio: "ndarray",
        sample_rate: int,
        *,
        transcript: Optional[str] = None,
        language: Optional[str] = None,
    ) -> "list[dict]":
        """Align each segment on its own slice of ``audio``; timings in whole-file seconds."""
        if not (transcript or "").split():
            return []
        pieces = self.split(transcript)
        duration = int(audio.shape[0]) / sample_rate
        lang = {} if language is None else {"language": language}
        out: "list[dict]" = []
        for piece, (s, e) in zip(pieces, self.spans(duration, sample_rate=sample_rate)):
            if not piece:
                continue
            lo, hi = round(s * sample_rate), round(e * sample_rate)
            timed = self.base.word_timeline(
                audio[lo:hi], sample_rate, transcript=" ".join(piece), **lang
            )
            out.extend(_shifted(w, lo / sample_rate) for w in timed)
        return out
