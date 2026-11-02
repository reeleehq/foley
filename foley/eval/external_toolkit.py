"""A reference toolkit run in its own interpreter: the part every adapter shares (#48, #262).

Several evaluation toolkits cannot share foley's environment: ``fadtk`` and ``kadtk``
pin ``numpy<2`` and an old torch, ``audiobox_aesthetics`` pulls a recent torch foley
does not need. Each runs the way :mod:`foley.external` runs MFA and aeneas: clips are
written as mono 16-bit WAVs to a temporary directory, the toolkit's interpreter runs
:mod:`foley.eval.toolkit_driver` on a JSON spec, and the JSON it writes back is the
answer. :class:`ExternalToolkit` is that mechanism (the interpreter and its install
hint, the failure hints, the run); what is computed over the files is the subclass's:
a set-level distance (:class:`foley.eval.external_fidelity.ExternalFidelity`) or a
per-clip score (:class:`foley.eval.aesthetics.AudioboxAesthetics`). Nothing from any
toolkit is imported here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Optional

from ..audio import save, to_mono
from ..external import Runner, resolve_program, run_program

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

    Files are named ``<prefix><n:05d>.wav`` from 1, so sorting them keeps the input
    order. ``check(clip, sr=, name=)``, if given, sees each ``(frames[, channels])``
    clip first and raises to refuse it.
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


class ExternalToolkit:
    """A toolkit run by :data:`DRIVER` in a separate interpreter.

    Subclasses set :attr:`toolkit`, :attr:`python_env`, :attr:`install`,
    :attr:`isolation_reason` (and optionally :attr:`failure_hints`), and call
    :meth:`run_driver`.

    Args:
        python: An interpreter with the toolkit installed, usually in its own venv
            (default: ``$<python_env>``; neither set raises with the install line).
        env: Variables added to this process's environment for the program, e.g.
            ``{"TORCH_HOME": ...}`` or ``{"HF_HOME": ...}`` to choose where weights go.
        timeout: Seconds before the run is abandoned (default: none).
        runner: Runs the command (default ``subprocess.run``).
    """

    toolkit: str  # the package the driver imports
    python_env: str  # the environment variable naming the toolkit's interpreter
    install: str  # the install line quoted when the interpreter is missing
    #: Why the toolkit cannot live in foley's environment (said when no interpreter).
    isolation_reason: str
    #: A substring of a failed run's output → what to do about it.
    failure_hints: "Mapping[str, str]" = {}

    def __init__(
        self,
        *,
        python: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        runner: Runner = subprocess.run,
    ):
        self.python, self.env, self.timeout, self.runner = python, env, timeout, runner

    def resolve_python(self) -> str:
        """The toolkit's interpreter as an executable path; raise with the install line if none.

        Cheap (no program runs), so a caller can fail before anything is paid for.
        """
        python = self.python or os.environ.get(self.python_env)
        if not python:
            raise FileNotFoundError(
                f"{type(self).__name__} needs {self.toolkit}'s interpreter "
                f"({self.isolation_reason}); pass python= or set ${self.python_env}. "
                f"Install: {self.install}"
            )
        return resolve_program(python, what=type(self).__name__, install=self.install)

    def local_paths(self) -> "list[str]":
        """The interpreter as given and resolved, and its venv root: paths to keep out of
        anything published (:func:`foley.obs.redact.redact_paths`). Never raises."""
        python = self.python or os.environ.get(self.python_env)
        if not python:
            return []
        given = Path(os.path.expanduser(python))
        found = shutil.which(str(given))
        paths = {python, str(given), *([found] if found else [])}
        for path in list(paths):
            real = Path(os.path.realpath(path))
            paths |= {str(real), str(Path(path).parent.parent), str(real.parent.parent)}
        return sorted(p for p in paths if os.path.isabs(p) and len(p) > 1)

    def _explain(self, err: RuntimeError, python: str) -> RuntimeError:
        hints = {
            f"No module named '{self.toolkit}'": (
                f"{python} has no {self.toolkit}. Install: {self.install}"
            ),
            **self.failure_hints,
        }
        said = [hint for needle, hint in hints.items() if needle in str(err)]
        return RuntimeError("\n".join([str(err), *said])) if said else err

    def run_driver(
        self,
        spec: dict,
        *,
        out: Path,
        cwd: Path,
        what: str,
        python: Optional[str] = None,
    ) -> dict:
        """Run :data:`DRIVER` on ``spec`` (plus ``toolkit`` and ``out``); return its JSON.

        ``python`` is the already-resolved interpreter (default: resolve it now); a
        caller resolves it first to fail before writing any file.

        Raises:
            FileNotFoundError: If no interpreter is given or found.
            RuntimeError: If the toolkit fails (its output tail, and any matching
                :attr:`failure_hints`, are in the message).
        """
        python = python or self.resolve_python()
        spec = {"toolkit": self.toolkit, "out": str(out), **spec}
        try:
            output = run_program(
                [python, "-I", str(DRIVER), json.dumps(spec)],
                out=out,
                runner=self.runner,
                env=None if self.env is None else {**os.environ, **self.env},
                timeout=self.timeout,
                cwd=cwd,
                what=what,
            )
        except RuntimeError as err:
            raise self._explain(err, python) from err
        return json.loads(output)
