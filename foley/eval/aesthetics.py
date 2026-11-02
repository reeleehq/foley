"""Per-clip generation quality from Meta's Audiobox Aesthetics, run in its own interpreter (#262).

`Audiobox Aesthetics <https://github.com/facebookresearch/audiobox-aesthetics>`_
(Tjandra et al. 2025, arXiv:2502.05139) predicts four scores, each on about 1 to 10,
for one clip of speech, music or sound: **CE** content enjoyment, **CU** content
usefulness, **PC** production complexity, **PQ** production quality
(:data:`AES_AXES`). It is a WavLM encoder with four regression heads, so it scores a
clip on its own, with no reference set and no prompt: a per-sample signal, where FAD
and KAD (:mod:`foley.eval.fadtk`, :mod:`foley.eval.kadtk`) are set-level.

The package pulls a recent torch and torchaudio foley does not depend on, so
:class:`AudioboxAesthetics` runs it through the same mechanism as fadtk and kadtk
(:class:`~foley.eval.external_toolkit.ExternalToolkit`: temporary mono WAVs,
:mod:`foley.eval.toolkit_driver` in the toolkit's interpreter, JSON back)::

    aes = AudioboxAesthetics(python="~/venvs/aes/bin/python")  # or $FOLEY_AES_PYTHON
    [score] = aes([wav], sr=48000)
    score.axes  # {'CE': 2.48, 'CU': 5.79, 'PC': 1.74, 'PQ': 6.03}

:func:`aesthetics_verdict` turns a score into the JSON-safe dict ``foley.generate``
records as ``qc['aesthetics']`` when asked (``generate(..., aesthetics=True)``). It is
a record, not a gate: with no :attr:`AudioboxAesthetics.floors` its status is
``'scored'``; with floors, ``'low'`` flags the clip in the notes, and it is still
stored. The model is not a fault detector: digital silence scored PQ 7.0, above a
clean tone (6.0) and white noise (4.8), so Tier-0 QC (:mod:`foley.qc`) stays the gate
for broken audio, and no floor is calibrated for SFX yet.

Licences: the code is CC-BY-4.0, with parts from microsoft/unilm under MIT. Meta's
README states no separate licence for the weights; the Hugging Face repo that holds
them (``facebook/audiobox-aesthetics``, about 415 MB) is tagged ``cc-by-4.0``.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Optional

from .external_toolkit import ExternalToolkit, write_set

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

__all__ = [
    "AES_AXES",
    "AES_PYTHON_ENV",
    "AestheticsScore",
    "AudioboxAesthetics",
    "aesthetics_verdict",
    "note_for",
    "resolve_aesthetics",
]

#: The four axes, in the toolkit's order, → what each one rates.
AES_AXES: "Mapping[str, str]" = {
    "CE": "content enjoyment",
    "CU": "content usefulness",
    "PC": "production complexity",
    "PQ": "production quality",
}

#: The environment variable naming the toolkit's interpreter when ``python=`` is not given.
AES_PYTHON_ENV = "FOLEY_AES_PYTHON"

#: Install hint. ``requests``: the package imports it without declaring it, and
#: ``huggingface_hub`` 1.0 and later no longer bring it in.
AES_INSTALL = (
    "uv venv ~/venvs/aes --python 3.11 && "
    "uv pip install --python ~/venvs/aes/bin/python audiobox_aesthetics requests; "
    f"then AudioboxAesthetics(python='~/venvs/aes/bin/python') or set {AES_PYTHON_ENV}"
)

#: The rate the model resamples every clip to.
AES_MODEL_SAMPLE_RATE = 16_000

#: The audio one WavLM encoder frame sees: its conv front end
#: ``[(512,10,5)] + [(512,3,2)]*4 + [(512,2,2)]*2`` has a 400-sample receptive field.
AES_RECEPTIVE_FIELD_SAMPLES = 400

#: The shortest clip scored: one encoder frame (25 ms). The toolkit pads every clip
#: to a 10 s window, so a shorter one still gets numbers, but they describe padding.
AES_MIN_SECONDS = AES_RECEPTIVE_FIELD_SAMPLES / AES_MODEL_SAMPLE_RATE

#: Clips per forward pass (the toolkit's own ``main_predict`` default).
AES_BATCH_SIZE = 10

#: :func:`aesthetics_verdict` statuses: scored with no floors, at or above every floor,
#: below one, or not scored (with the reason).
SCORED, OK, LOW, UNCHECKED = "scored", "ok", "low", "unchecked"


@dataclass(frozen=True)
class AestheticsScore:
    """One clip's Audiobox Aesthetics scores, stamped with the model and toolkit version."""

    axes: "Mapping[str, float]"
    model: str
    version: str
    toolkit: str = field(default="audiobox_aesthetics")

    def to_dict(self) -> dict:
        """The axes and the stamp as one flat JSON-safe dict."""
        return {
            **self.axes,
            "model": self.model,
            "toolkit": self.toolkit,
            "version": self.version,
        }


def _check_floors(floors: "Optional[Mapping[str, float]]") -> dict:
    floors = dict(floors or {})
    unknown = sorted(set(floors) - set(AES_AXES))
    if unknown:
        raise ValueError(f"unknown aesthetics axes {unknown}; known: {list(AES_AXES)}")
    return {axis: float(value) for axis, value in floors.items()}


class AudioboxAesthetics(ExternalToolkit):
    """Per-clip Audiobox Aesthetics scores computed in a separate interpreter.

    Args: those of :class:`~foley.eval.external_toolkit.ExternalToolkit` (``python``,
    ``env``, ``timeout``, ``runner``), plus:
        checkpoint: A local ``checkpoint.pt`` (default: the Hugging Face weights,
            downloaded once into the toolkit's ``HF_HOME``; pass
            ``env={"HF_HOME": ...}`` to choose where).
        batch_size: Clips a forward pass.
        min_seconds: The shortest clip scored (default :data:`AES_MIN_SECONDS`).
        floors: Axis → the lowest acceptable score, read by
            :func:`aesthetics_verdict` (default none: the verdict only records).
    """

    toolkit = "audiobox_aesthetics"
    python_env = AES_PYTHON_ENV
    install = AES_INSTALL
    isolation_reason = (
        "it brings its own torch and torchaudio, which foley does not depend on"
    )
    failure_hints = {
        "No module named 'requests'": (
            "audiobox_aesthetics imports requests without declaring it. "
            f"Install: {AES_INSTALL}"
        ),
    }

    def __init__(
        self,
        *,
        checkpoint: Optional[str] = None,
        batch_size: int = AES_BATCH_SIZE,
        min_seconds: float = AES_MIN_SECONDS,
        floors: "Optional[Mapping[str, float]]" = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.checkpoint, self.batch_size = checkpoint, batch_size
        self.min_seconds, self.floors = min_seconds, _check_floors(floors)

    def check_clip(self, clip: "ndarray", *, sr: int, name: str) -> None:
        """Refuse a clip shorter than :attr:`min_seconds`, or with a NaN or infinite sample."""
        import numpy as np

        if len(clip) < self.min_seconds * sr:
            raise ValueError(
                f"clip {name} is {len(clip) / sr:.4f} s; Audiobox Aesthetics needs at "
                f"least {self.min_seconds:g} s (one encoder frame) to score it"
            )
        if not np.isfinite(clip).all():
            raise ValueError(f"clip {name} has NaN or infinite samples")

    def __call__(
        self, wavs: Iterable["ndarray"], *, sr: int
    ) -> "list[AestheticsScore]":
        """One :class:`AestheticsScore` per clip of ``wavs``, in order.

        Clips are ``(frames,)`` or ``(frames, channels)`` arrays (mixed to mono).

        Raises:
            FileNotFoundError: If no interpreter is given or found.
            RuntimeError: If the toolkit fails, or answers for another number of clips.
            ValueError: If there is no clip, or a clip has another layout, is shorter
                than :attr:`min_seconds` or is not finite.
        """
        python = self._resolve_python()  # before any file is written
        with tempfile.TemporaryDirectory(prefix=f"foley-{self.toolkit}-") as tmp:
            clips, out = Path(tmp) / "clips", Path(tmp) / "out.json"
            n = write_set(wavs, sr, clips, prefix="clip", check=self.check_clip)
            if not n:
                raise ValueError("Audiobox Aesthetics needs at least one clip")
            spec = {
                "task": "aesthetics",
                "clips": [str(p) for p in sorted(clips.glob("*.wav"))],
                "checkpoint": self.checkpoint,
                "batch_size": self.batch_size,
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
            raise RuntimeError(f"{self.toolkit} scored {len(rows)} of {n} clips")
        model, version = str(answer.get("model")), str(answer.get("version", "unknown"))
        return [
            AestheticsScore(
                axes={axis: float(row[axis]) for axis in AES_AXES},
                model=model,
                version=version,
            )
            for row in rows
        ]


def resolve_aesthetics(aesthetics):
    """``generate(aesthetics=)`` as a scorer: ``None``/``False`` none, ``True`` the default
    :class:`AudioboxAesthetics`, a scorer (``(wavs, *, sr) -> [AestheticsScore]``) as is."""
    if aesthetics is None or aesthetics is False:
        return None
    if aesthetics is True:
        return AudioboxAesthetics()
    if not callable(aesthetics):
        raise TypeError(
            f"aesthetics= takes True, False, None or a scorer, not {type(aesthetics).__name__}"
        )
    return aesthetics


def aesthetics_verdict(audio_bytes: bytes, *, scorer) -> dict:
    """Score ``audio_bytes`` with ``scorer`` and compare with its ``floors``; never raises.

    Returns:
        A JSON-safe dict: ``status`` (``scored`` | ``ok`` | ``low`` | ``unchecked``),
        and the four axes, ``model``, ``toolkit`` and ``version`` when scored, plus
        ``floors`` and the axes ``below`` them when the scorer has floors; or
        ``reason`` when not scored (no interpreter, a clip too short, a toolkit crash).

    >>> aesthetics_verdict(b"", scorer=lambda wavs, *, sr: [])["status"]
    'unchecked'
    """
    from ..audio import load

    try:
        floors = _check_floors(getattr(scorer, "floors", None))
        wav, sr = load(audio_bytes)
        [score] = scorer([wav], sr=sr)
    except Exception as exc:  # noqa: BLE001 - a score that cannot be had is "unchecked"
        return {"status": UNCHECKED, "reason": f"{type(exc).__name__}: {exc}"}
    below = [a for a, f in floors.items() if not score.axes[a] >= f]  # NaN is below
    result = {"status": (LOW if below else OK) if floors else SCORED, **score.to_dict()}
    if floors:
        result["floors"] = floors
    if below:
        result["below"] = below
    return result


def note_for(result: dict) -> Optional[str]:
    """The one-line candidate note for an :func:`aesthetics_verdict` result."""
    status = result.get("status")
    if status == UNCHECKED:
        return f"aesthetics: unchecked ({result.get('reason')})"
    if status not in (SCORED, OK, LOW):
        return None
    axes = " ".join(f"{a} {result[a]:.2f}" for a in AES_AXES)
    if status == LOW:
        low = ", ".join(f"{a} < {result['floors'][a]:g}" for a in result["below"])
        return f"aesthetics: LOW ({low}; {axes}); listen before using it"
    return f"aesthetics: {status} ({axes})"
