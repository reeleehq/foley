"""Set-level fidelity from a reference toolkit run in its own interpreter (#48, #262).

:mod:`foley.eval.fidelity` has the FAD and KAD math in pure numpy. For numbers
comparable with published ones, the reference toolkits (``fadtk`` for FAD, ``kadtk``
for KAD) must do the embedding, the audio loading and the statistics, and both pin
``numpy<2`` and an old torch, so neither can share foley's environment.
:class:`ExternalFidelity` is the part they share, the way :mod:`foley.external` is for
MFA and aeneas: the two wav sets are written as mono 16-bit WAVs to a temporary
directory, the toolkit's interpreter runs :mod:`foley.eval.toolkit_driver` on them, and
its JSON answer becomes a :class:`~foley.eval.fidelity.FidelityResult` stamped with
the toolkit and its version. Nothing from either toolkit is imported here.

A toolkit is a subclass that sets the class attributes (its name, metric, model table,
interpreter variable, install line) and says how many embedding frames each set needs
(:meth:`ExternalFidelity.frames_needed`); see :mod:`foley.eval.fadtk` and
:mod:`foley.eval.kadtk`.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
import warnings
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Optional

from ..audio import save, to_mono
from ..external import Runner, resolve_program, run_program
from .fidelity import FidelityResult, FidelityStamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: The script run inside a toolkit's interpreter.
DRIVER = Path(__file__).with_name("toolkit_driver.py")

#: The most channels a clip may have. A 2-D array with at most this many rows and more
#: columns than that is channel-first, and is refused (:func:`as_frames_channels`).
MAX_CHANNELS = 8


def as_frames_channels(wav) -> "ndarray":
    """``wav`` as foley's ``(frames,)`` / ``(frames, channels)``; refuse other layouts.

    A channel-first ``(2, N)`` array would otherwise be read as two-sample clips.
    """
    import numpy as np

    a = np.asarray(wav, dtype=np.float32)
    if a.ndim > 2 or (a.ndim == 2 and a.shape[0] <= MAX_CHANNELS < a.shape[1]):
        raise ValueError(
            f"a clip of shape {a.shape} is not (frames,) or (frames, channels); "
            "transpose a channel-first array (wav.T)"
        )
    return a


def write_set(
    wavs: Iterable,
    sr: int,
    folder: Path,
    *,
    prefix: str,
    check: "Optional[Callable[..., None]]" = None,
) -> int:
    """Write each waveform in ``wavs`` as a mono 16-bit WAV in ``folder``; return the count.

    ``check(clip, sr=, name=)``, if given, sees each ``(frames[, channels])`` clip first
    and raises to refuse it.
    """
    folder.mkdir(parents=True)
    n = 0
    for n, wav in enumerate(wavs, start=1):
        clip, name = as_frames_channels(wav), f"{prefix}{n:05d}"
        if check is not None:
            check(clip, sr=sr, name=name)
        save(
            to_mono(clip),
            sr,
            folder / f"{name}.wav",
            fmt="WAV",
            subtype="PCM_16",
        )
    return n


class ExternalFidelity:
    """A set-level fidelity score computed by a toolkit in a separate interpreter.

    Subclasses set :attr:`toolkit`, :attr:`metric`, :attr:`default_models`,
    :attr:`default_model`, :attr:`python_env`, :attr:`install` (and optionally
    :attr:`failure_hints`), and implement :meth:`frames_needed`; :meth:`options` adds
    toolkit-specific entries to the driver's spec, and :meth:`check_clip` refuses a clip
    the toolkit cannot embed before anything runs.

    Args:
        python: An interpreter with the toolkit installed, usually in its own venv
            (default: ``$<python_env>``; neither set raises with the install line).
        model: A key of ``models`` (default :attr:`default_model`).
        models: Model name → (loader class in ``<toolkit>.model_loader``, its args)
            (default :attr:`default_models`).
        workers: The toolkit's embedding worker processes (each loads the model).
        env: Variables added to this process's environment for the program, e.g.
            ``{"TORCH_HOME": ...}`` to choose where the weights are cached.
        timeout: Seconds before the run is abandoned (default: none).
        runner: Runs the command (default ``subprocess.run``).
    """

    #: Below this many embedding frames in a set, warn that the score is mostly noise
    #: (``None``: never). The hard floor is :meth:`frames_needed`.
    warn_frames: Optional[int] = None
    toolkit: str  # the package the driver imports, and the stamp's toolkit
    metric: str  # FidelityResult.metric: 'fad' | 'kad'
    default_models: "Mapping[str, tuple[str, tuple]]"
    default_model: str
    python_env: str  # the environment variable naming the toolkit's interpreter
    install: str  # the install line quoted when the interpreter is missing
    #: A substring of a failed run's output → what to do about it.
    failure_hints: "Mapping[str, str]" = {}

    def __init__(
        self,
        *,
        python: Optional[str] = None,
        model: Optional[str] = None,
        models: "Optional[Mapping[str, tuple[str, tuple]]]" = None,
        workers: int = 1,
        env: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        runner: Runner = subprocess.run,
    ):
        self.models = dict(self.default_models if models is None else models)
        model = self.default_model if model is None else model
        if model not in self.models:
            raise ValueError(
                f"unknown {self.toolkit} model {model!r}; known: {sorted(self.models)} "
                f"(add one with models={{name: (loader_class, args)}})"
            )
        self.python, self.model, self.workers = python, model, workers
        self.env, self.timeout, self.runner = env, timeout, runner

    def frames_needed(self, dim: int) -> "tuple[int, str]":
        """The fewest embedding frames a set may have for a ``dim``-dim embedding, and why."""
        raise NotImplementedError

    def check_clip(self, clip: "ndarray", *, sr: int, name: str) -> None:
        """Raise :class:`ValueError` if the toolkit cannot embed ``clip`` (default: accept)."""

    def options(self) -> dict:
        """Toolkit-specific entries for the driver's spec (default: none)."""
        return {}

    def _resolve_python(self) -> str:
        python = self.python or os.environ.get(self.python_env)
        if not python:
            raise FileNotFoundError(
                f"{type(self).__name__} needs {self.toolkit}'s interpreter ({self.toolkit} "
                "pins numpy<2, so it cannot live in foley's environment). "
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

    def __call__(
        self, ref_wavs: Iterable["ndarray"], gen_wavs: Iterable["ndarray"], *, sr: int
    ) -> FidelityResult:
        """The metric between the reference and generated wav sets, stamped with the toolkit.

        Clips are ``(frames,)`` or ``(frames, channels)`` arrays (mixed to mono).

        Raises:
            FileNotFoundError: If no interpreter is given or found.
            RuntimeError: If the toolkit fails (its output tail is in the message).
            ValueError: If a clip has another layout, a set is empty, or a set has
                fewer embedding frames than :meth:`frames_needed` asks.

        Warns:
            UserWarning: If a set has fewer than :attr:`warn_frames` frames.
        """
        python = self._resolve_python()
        loader, args = self.models[self.model]
        name = self.metric.upper()
        with tempfile.TemporaryDirectory(prefix=f"foley-{self.toolkit}-") as tmp:
            ref, gen, out = (Path(tmp) / n for n in ("ref", "gen", "out.json"))
            n_ref = write_set(ref_wavs, sr, ref, prefix="ref", check=self.check_clip)
            n_gen = write_set(gen_wavs, sr, gen, prefix="gen", check=self.check_clip)
            if not (n_ref and n_gen):
                raise ValueError(f"{name} needs at least one clip in each set")
            spec = {
                "toolkit": self.toolkit,
                "loader": loader,
                "args": list(args),
                "ref": str(ref),
                "gen": str(gen),
                "out": str(out),
                "workers": self.workers,
                **self.options(),
            }
            try:
                output = run_program(
                    [python, "-I", str(DRIVER), json.dumps(spec)],
                    out=out,
                    runner=self.runner,
                    env=None if self.env is None else {**os.environ, **self.env},
                    timeout=self.timeout,
                    cwd=Path(tmp),
                    what=f"{type(self).__name__} ({self.toolkit} {self.model})",
                )
            except RuntimeError as err:
                raise self._explain(err, python) from err
        answer = json.loads(output)
        n_ref, n_gen, dim = (
            int(answer[k]) for k in ("n_ref_frames", "n_gen_frames", "dim")
        )
        embedding = answer.get("model", self.model)
        least, why = self.frames_needed(dim)
        if min(n_ref, n_gen) < least:
            raise ValueError(
                f"too little audio for {name} on {embedding}: {n_ref} reference and "
                f"{n_gen} generated embedding frames; each set needs at least {least} "
                f"({why}); use more or longer clips"
            )
        if self.warn_frames is not None and min(n_ref, n_gen) < self.warn_frames:
            warnings.warn(
                f"{name} on {n_ref} reference and {n_gen} generated embedding frames: "
                f"below {self.warn_frames} frames a set, the score is mostly noise",
                stacklevel=2,
            )
        return FidelityResult(
            metric=self.metric,
            value=float(answer["score"]),
            stamp=FidelityStamp(
                embedding=embedding,
                toolkit=self.toolkit,
                version=str(answer.get("version", "unknown")),
                n_ref=n_ref,
                n_gen=n_gen,
            ),
            params=dict(answer.get("params") or {}),
        )
