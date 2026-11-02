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
brings its own torch, so :class:`Pam` runs :mod:`foley.eval.pam_driver` in its own
interpreter, the way :mod:`foley.eval.kadtk` runs kadtk::

    pam = Pam(python="~/venvs/pam/bin/python")  # or $FOLEY_PAM_PYTHON
    tone, noise = pam([tone_wav, noise_wav], sr=48000)
    tone.score      # 0.68 (a 3 s 440 Hz sine); noise.score 0.04 (white noise)

It is an eval-side scorer for any set of clips; it is not wired into ``generate``.

Licences: PAM's and msclap's code are MIT; the CLAP weights
(``microsoft/msclap``, ``CLAP_weights_2023.pth``, 690 MB) are tagged MS-PL on Hugging
Face; the GPT-2 tokenizer files it fetches (3 MB) are MIT. The scores are metadata about
a clip, so they do not change its licence.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Sequence

from ..external import Runner, resolve_program, run_program
from .external_fidelity import write_set

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

__all__ = ["PAM_PROMPTS", "PAM_PYTHON_ENV", "Pam", "PamScore"]

#: The script run inside the msclap interpreter.
DRIVER = Path(__file__).with_name("pam_driver.py")

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


class Pam:
    """Per-clip PAM scores computed by ``msclap`` in a separate interpreter.

    Args:
        python: An interpreter with ``msclap`` installed, in its own venv (default:
            ``$FOLEY_PAM_PYTHON``; neither set raises with the install line).
        checkpoint: A local ``CLAP_weights_2023.pth`` (default: downloaded once into the
            interpreter's ``HF_HOME``; pass ``env={"HF_HOME": ...}`` to choose where).
        prompts: The prompts, the clean one first (default :data:`PAM_PROMPTS`; others
            give a PAM-style score, not PAM's).
        batch_size: Windows a forward pass.
        device: Where the model runs (``'cpu'``, ``'cuda'``, ``'mps'``).
        env: Variables added to this process's environment for the program.
        timeout: Seconds before the run is abandoned (default: none).
        runner: Runs the command (default ``subprocess.run``).
    """

    toolkit = "msclap"
    python_env = PAM_PYTHON_ENV
    install = PAM_INSTALL
    #: Why msclap cannot live in foley's environment (said when no interpreter).
    isolation_reason = "it pins numpy<2 and brings its own torch"
    #: A substring of a failed run's output → what to do about it.
    failure_hints: "Mapping[str, str]" = {}

    def __init__(
        self,
        *,
        python: Optional[str] = None,
        checkpoint: Optional[str] = None,
        prompts: "Sequence[str]" = PAM_PROMPTS,
        batch_size: int = PAM_BATCH_SIZE,
        device: str = "cpu",
        env: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        runner: Runner = subprocess.run,
    ):
        if len(prompts) < 2:
            raise ValueError("PAM needs at least two prompts, the clean one first")
        self.python, self.checkpoint, self.prompts = python, checkpoint, tuple(prompts)
        self.batch_size, self.device = batch_size, device
        self.env, self.timeout, self.runner = env, timeout, runner

    def _resolve_python(self) -> str:
        python = self.python or os.environ.get(self.python_env)
        if not python:
            raise FileNotFoundError(
                f"{type(self).__name__} needs {self.toolkit}'s interpreter "
                f"({self.isolation_reason}); pass python= or set ${self.python_env}. "
                f"Install: {self.install}"
            )
        return resolve_program(python, what=type(self).__name__, install=self.install)

    def _explain(self, err: RuntimeError, python: str) -> RuntimeError:
        hints = {
            f"No module named '{self.toolkit}'": (
                f"{python} has no {self.toolkit}. Install: {self.install}"
            ),
            **self.failure_hints,
        }
        said = [hint for needle, hint in hints.items() if needle in str(err)]
        return RuntimeError("\n".join([str(err), *said])) if said else err

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
        python = self._resolve_python()  # before any file is written
        with tempfile.TemporaryDirectory(prefix="foley-pam-") as tmp:
            clips, out = Path(tmp) / "clips", Path(tmp) / "out.json"
            n = write_set(wavs, sr, clips, prefix="clip", check=self.check_clip)
            if not n:
                raise ValueError("PAM needs at least one clip")
            spec = {
                "clips": [str(p) for p in sorted(clips.glob("*.wav"))],
                "out": str(out),
                "checkpoint": self.checkpoint,
                "prompts": list(self.prompts),
                "batch_size": self.batch_size,
                "device": self.device,
            }
            try:
                output = run_program(
                    [python, "-I", str(DRIVER), json.dumps(spec)],
                    out=out,
                    runner=self.runner,
                    env=None if self.env is None else {**os.environ, **self.env},
                    timeout=self.timeout,
                    cwd=Path(tmp),
                    what=f"{type(self).__name__} ({self.toolkit})",
                )
            except RuntimeError as err:
                raise self._explain(err, python) from err
        answer = json.loads(output)
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
