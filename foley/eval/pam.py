"""Per-clip, reference-free audio quality from PAM, run in an ``msclap`` interpreter (#262).

PAM (Deshmukh et al., "PAM: Prompting Audio-Language Models for Audio Quality
Assessment", Interspeech 2024, arXiv:2402.00282, `soham97/PAM
<https://github.com/soham97/PAM>`_) scores one clip with no reference set: it asks
Microsoft's CLAP 2023 audio-language model which of two antonym prompts fits the clip
better, and the score is the softmax probability of the first one,
``"the sound is clear and clean."`` against ``"the sound is noisy and with artifacts."``
(:data:`PAM_PROMPTS`). So it is in ``[0, 1]``, higher is cleaner. Clips are scored in
7 s windows at 44.1 kHz (the model's own config); a clip's score is its windows' mean.

PAM is a research repository, not a package; its model is the one the ``msclap``
package ships (MIT, on PyPI, maintained by Microsoft). ``msclap`` pins ``numpy<2`` and
brings its own torch, so :class:`Pam` is an
:class:`~foley.eval.external_toolkit.ExternalToolkit`: :mod:`foley.eval.toolkit_driver`
runs its ``pam`` task in msclap's interpreter, as it runs fadtk, kadtk and Audiobox
Aesthetics::

    pam = Pam(python="~/venvs/pam/bin/python")  # or $FOLEY_PAM_PYTHON
    tone, noise = pam([tone_wav, noise_wav], sr=48000)
    tone.score      # 0.68 (a 3 s 440 Hz sine); noise.score 0.04 (white noise)

It is an eval-side scorer for any set of clips; it is not wired into ``generate`` (as
``generate(aesthetics=)`` is) yet. It raises rather than storing anything, so no
failure text of its own reaches a record.

Licences: PAM's and msclap's code are MIT; the CLAP weights
(``microsoft/msclap``, ``CLAP_weights_2023.pth``, 690 MB) are tagged MS-PL on Hugging
Face; the GPT-2 tokenizer files it fetches (3 MB) are MIT. The scores are metadata about
a clip, so they do not change its licence.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from .external_toolkit import ExternalToolkit, write_set

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

__all__ = ["PAM_PROMPTS", "PAM_PYTHON_ENV", "Pam", "PamScore"]

#: PAM's antonym prompts; the score is the probability of the first.
PAM_PROMPTS: "tuple[str, ...]" = (
    "the sound is clear and clean.",
    "the sound is noisy and with artifacts.",
)

#: The environment variable naming msclap's interpreter when ``python=`` is not given.
PAM_PYTHON_ENV = "FOLEY_PAM_PYTHON"

#: Install hint.
PAM_INSTALL = (
    "uv venv ~/venvs/pam --python 3.11 && "
    "uv pip install --python ~/venvs/pam/bin/python msclap; "
    f"then Pam(python='~/venvs/pam/bin/python') or set {PAM_PYTHON_ENV}"
)

#: 7 s windows a forward pass (PAM's ``run.py`` batches 10 files).
PAM_BATCH_SIZE = 10


@dataclass(frozen=True)
class PamScore:
    """One clip's PAM score, its per-window scores, and the model and toolkit version."""

    score: float
    segments: "tuple[float, ...]"
    model: str
    version: str
    toolkit: str = field(default="msclap")

    def to_dict(self) -> dict:
        """The score, the window scores and the stamp as one JSON-safe dict."""
        return {
            "pam": self.score,
            "segments": list(self.segments),
            "model": self.model,
            "toolkit": self.toolkit,
            "version": self.version,
        }


class Pam(ExternalToolkit):
    """Per-clip PAM scores computed by ``msclap`` in a separate interpreter.

    Args: those of :class:`~foley.eval.external_toolkit.ExternalToolkit` (``python``,
    default ``$FOLEY_PAM_PYTHON``; ``env``, e.g. ``{"HF_HOME": ...}`` to choose where
    the weights go; ``timeout``; ``runner``), plus:
        checkpoint: A local ``CLAP_weights_2023.pth`` (default: downloaded once into the
            interpreter's ``HF_HOME``).
        prompts: The prompts, the clean one first (default :data:`PAM_PROMPTS`; others
            give a PAM-style score, not PAM's).
        batch_size: Windows a forward pass.
        device: Where the model runs (``'cpu'``, ``'cuda'``, ``'mps'``).
    """

    toolkit = "msclap"
    python_env = PAM_PYTHON_ENV
    install = PAM_INSTALL
    isolation_reason = "it pins numpy<2 and brings its own torch"

    def __init__(
        self,
        *,
        checkpoint: Optional[str] = None,
        prompts: "Sequence[str]" = PAM_PROMPTS,
        batch_size: int = PAM_BATCH_SIZE,
        device: str = "cpu",
        **kwargs,
    ):
        super().__init__(**kwargs)
        if len(prompts) < 2:
            raise ValueError("PAM needs at least two prompts, the clean one first")
        if batch_size < 1:
            raise ValueError(f"batch_size must be at least 1, not {batch_size}")
        self.checkpoint, self.prompts = checkpoint, tuple(prompts)
        self.batch_size, self.device = batch_size, device

    def check_clip(self, clip: "ndarray", *, sr: int, name: str) -> None:
        """Refuse an empty clip, or one with a NaN or infinite sample.

        A short clip is scored: PAM tiles it to one 7 s window.
        """
        import numpy as np

        if not len(clip):
            raise ValueError(f"clip {name} is empty")
        if not np.isfinite(clip).all():
            raise ValueError(f"clip {name} has NaN or infinite samples")

    def __call__(self, wavs: Iterable["ndarray"], *, sr: int) -> "list[PamScore]":
        """One :class:`PamScore` per clip of ``wavs``, in order.

        Clips are ``(frames,)`` or ``(frames, channels)`` arrays (mixed to mono).

        Raises:
            FileNotFoundError: If no interpreter is given or found.
            RuntimeError: If msclap fails, or answers for another number of clips.
            ValueError: If there is no clip, or a clip has another layout, is empty or
                is not finite.
        """
        python = self.resolve_python()  # before any file is written
        with tempfile.TemporaryDirectory(prefix="foley-pam-") as tmp:
            clips, out = Path(tmp) / "clips", Path(tmp) / "out.json"
            n = write_set(wavs, sr, clips, prefix="clip", check=self.check_clip)
            if not n:
                raise ValueError("PAM needs at least one clip")
            spec = {
                "task": "pam",
                "clips": [str(p) for p in sorted(clips.glob("*.wav"))],
                "checkpoint": self.checkpoint,
                "prompts": list(self.prompts),
                "batch_size": self.batch_size,
                "device": self.device,
            }
            answer = self.run_driver(
                spec,
                python=python,
                out=out,
                cwd=Path(tmp),
                what=f"{type(self).__name__} ({self.toolkit})",
            )
        rows = answer["scores"]
        if len(rows) != n:
            raise RuntimeError(f"PAM scored {len(rows)} of {n} clips")
        model, version = str(answer.get("model")), str(answer.get("version", "unknown"))
        return [
            PamScore(
                score=float(row["score"]),
                segments=tuple(float(s) for s in row["segments"]),
                model=model,
                version=version,
            )
            for row in rows
        ]
