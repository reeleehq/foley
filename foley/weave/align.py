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

``_default_aligner`` auto-upgrades to WhisperX when ``foley[align]`` is installed,
else falls back to the fake — the progressive-disclosure rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

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

    Args:
        model_size: faster-whisper model name (``tiny``/``base``/``small``/…).
        device: ``'cpu'`` or ``'cuda'``.
        batch_size: Transcription batch size.
    """

    def __init__(
        self, *, model_size: str = "small", device: str = "cpu", batch_size: int = 16
    ):
        self.model_size = model_size
        self.device = device
        self.batch_size = batch_size

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
    """``fake`` / ``whisperx`` for the built-ins, else the class name (run manifest)."""
    if isinstance(aligner, FakeAligner):
        return "fake"
    if isinstance(aligner, WhisperXAligner):
        return "whisperx"
    return type(aligner).__name__


def _default_aligner() -> "Aligner":
    """The zero-config aligner: :class:`WhisperXAligner` when installed, else the fake."""
    return WhisperXAligner() if _whisperx_available() else FakeAligner()
