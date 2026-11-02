"""Reference FAD from Microsoft's ``fadtk``, run in its own interpreter (#48).

:func:`foley.eval.fidelity.frechet_distance` is the FAD math in pure numpy, fed by any
embedder. To report a number comparable with published ones, use the reference
toolkit, `fadtk <https://github.com/microsoft/fadtk>`_: its embedding models, its
audio loading and resampling, its statistics. fadtk 1.1 pins ``numpy<2`` and pulls
torch, torchvision and two CLAP packages, so it cannot share foley's environment.
:class:`FadtkFidelity` runs it the way :mod:`foley.weave.cli_aligners` runs MFA and
aeneas: the two wav sets are written to a temporary directory, the interpreter of a
virtualenv holding fadtk runs :mod:`foley.eval.fadtk_driver` on them, and its JSON
answer becomes a :class:`~foley.eval.fidelity.FidelityResult` stamped
``toolkit='fadtk'``. Nothing from fadtk is imported here.

::

    fad = FadtkFidelity(python="~/venvs/fadtk/bin/python")
    result = fad(reference_wavs, generated_wavs, sr=48000)
    result.value, result.stamp  # FAD, FidelityStamp(embedding='encodec-emb', toolkit='fadtk', ...)

fadtk's FAD is over embedding **frames** (every frame of every clip), not one vector
per clip as :func:`~foley.eval.fidelity.generation_fidelity` takes, so the two numbers
differ unless fed the same frames. Install and model choice: ``misc/docs/fidelity.md``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Optional

from ..audio import save, to_mono
from ..external import Runner, resolve_program, run_program
from .fidelity import FidelityResult, FidelityStamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: fadtk embedding models by fadtk's name → (loader class in ``fadtk.model_loader``,
#: its constructor args). Extend with ``FadtkFidelity(models={...})``. The default,
#: ``encodec-emb``, downloads the smallest weights (EnCodec 24 kHz, about 90 MB).
FADTK_MODELS: "Mapping[str, tuple[str, tuple]]" = {
    "encodec-emb": ("EncodecEmbModel", ("24k",)),
    "encodec-emb-48k": ("EncodecEmbModel", ("48k",)),
    "vggish": ("VGGishModel", ()),
    "clap-laion-audio": ("CLAPLaionModel", ("audio",)),
    "clap-laion-music": ("CLAPLaionModel", ("music",)),
    "clap-2023": ("CLAPModel", ("2023",)),
}

#: The default fadtk model (lightest download; see :data:`FADTK_MODELS`).
DEFAULT_FADTK_MODEL = "encodec-emb"

#: The script run inside fadtk's interpreter.
DRIVER = Path(__file__).with_name("fadtk_driver.py")

#: The environment variable naming fadtk's interpreter when ``python=`` is not given.
FADTK_PYTHON_ENV = "FOLEY_FADTK_PYTHON"

#: Install hint, printed when the interpreter is missing or lacks fadtk.
FADTK_INSTALL = (
    "uv venv ~/venvs/fadtk --python 3.11 && "
    "uv pip install --python ~/venvs/fadtk/bin/python fadtk torchcodec; "
    f"then FadtkFidelity(python='~/venvs/fadtk/bin/python') or set {FADTK_PYTHON_ENV}"
)

#: The most channels a clip may have. A 2-D array with at most this many rows and more
#: columns than that is channel-first, and is refused (:func:`_as_frames_channels`).
MAX_CHANNELS = 8


def _as_frames_channels(wav) -> "ndarray":
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


def _resolve_fadtk_python(python: Optional[str]) -> str:
    """``python``, else ``$FOLEY_FADTK_PYTHON``, as an executable path."""
    python = python or os.environ.get(FADTK_PYTHON_ENV)
    if not python:
        raise FileNotFoundError(
            "FadtkFidelity needs fadtk's interpreter (fadtk pins numpy<2, so it cannot "
            f"live in foley's environment). Install: {FADTK_INSTALL}"
        )
    return resolve_program(python, what="FadtkFidelity", install=FADTK_INSTALL)


def _write_set(wavs: Iterable, sr: int, folder: Path, *, prefix: str) -> int:
    """Write each waveform in ``wavs`` as a mono 16-bit WAV in ``folder``; return the count."""
    folder.mkdir(parents=True)
    n = 0
    for n, wav in enumerate(wavs, start=1):
        save(
            to_mono(_as_frames_channels(wav)),
            sr,
            folder / f"{prefix}{n:05d}.wav",
            fmt="WAV",
            subtype="PCM_16",
        )
    return n


class FadtkFidelity:
    """Set-level FAD computed by ``fadtk`` in a separate interpreter.

    Args:
        python: An interpreter with ``fadtk`` installed, usually in its own venv
            (default: ``$FOLEY_FADTK_PYTHON``; neither set raises with the install).
        model: A key of ``models`` (default :data:`DEFAULT_FADTK_MODEL`).
        models: fadtk name → (loader class, args) (default :data:`FADTK_MODELS`).
        workers: fadtk's embedding worker processes (each loads the model).
        env: The program's environment (default: this process's), e.g. to set
            ``TORCH_HOME`` where the weights are cached.
        timeout: Seconds before the run is abandoned (default: none).
        runner: Runs the command (default ``subprocess.run``).
    """

    toolkit = "fadtk"

    def __init__(
        self,
        *,
        python: Optional[str] = None,
        model: str = DEFAULT_FADTK_MODEL,
        models: "Optional[Mapping[str, tuple[str, tuple]]]" = None,
        workers: int = 1,
        env: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        runner: Runner = subprocess.run,
    ):
        self.models = dict(FADTK_MODELS if models is None else models)
        if model not in self.models:
            raise ValueError(
                f"unknown fadtk model {model!r}; known: {sorted(self.models)} "
                f"(add one with models={{name: (loader_class, args)}})"
            )
        self.python, self.model, self.workers = python, model, workers
        self.env, self.timeout, self.runner = env, timeout, runner

    def __call__(
        self, ref_wavs: Iterable["ndarray"], gen_wavs: Iterable["ndarray"], *, sr: int
    ) -> FidelityResult:
        """FAD between the reference and generated wav sets, stamped ``toolkit='fadtk'``.

        Clips are ``(frames,)`` or ``(frames, channels)`` arrays (mixed to mono).

        Raises:
            FileNotFoundError: If no interpreter is given or found.
            RuntimeError: If fadtk fails (its output tail is in the message).
            ValueError: If a clip has another layout, a set is empty, or a set has
                no more embedding frames than the embedding has dimensions (its
                covariance would be singular and the FAD meaningless).
        """
        python = _resolve_fadtk_python(self.python)
        loader, args = self.models[self.model]
        with tempfile.TemporaryDirectory(prefix="foley-fadtk-") as tmp:
            ref, gen, out = (Path(tmp) / n for n in ("ref", "gen", "out.json"))
            n_ref = _write_set(ref_wavs, sr, ref, prefix="ref")
            n_gen = _write_set(gen_wavs, sr, gen, prefix="gen")
            if not (n_ref and n_gen):
                raise ValueError("FAD needs at least one clip in each set")
            spec = {
                "loader": loader,
                "args": list(args),
                "ref": str(ref),
                "gen": str(gen),
                "out": str(out),
                "workers": self.workers,
            }
            try:
                output = run_program(
                    [python, "-I", str(DRIVER), json.dumps(spec)],
                    out=out,
                    runner=self.runner,
                    env=self.env,
                    timeout=self.timeout,
                    cwd=Path(tmp),
                    what=f"FadtkFidelity (fadtk {self.model})",
                )
            except RuntimeError as err:
                if "No module named 'fadtk'" in str(err):
                    raise RuntimeError(
                        f"{err}\n{python} has no fadtk. Install: {FADTK_INSTALL}"
                    ) from err
                raise
        answer = json.loads(output)
        n_ref, n_gen, dim = (
            int(answer[k]) for k in ("n_ref_frames", "n_gen_frames", "dim")
        )
        if min(n_ref, n_gen) <= dim:
            raise ValueError(
                f"too little audio for FAD on {answer.get('model', self.model)}: "
                f"{n_ref} reference and {n_gen} generated embedding frames for a "
                f"{dim}-dim embedding (each set needs more frames than dimensions, "
                "or the covariance is singular); use more or longer clips"
            )
        return FidelityResult(
            metric="fad",
            value=float(answer["score"]),
            stamp=FidelityStamp(
                embedding=answer.get("model", self.model),
                toolkit=self.toolkit,
                version=str(answer.get("fadtk_version", "unknown")),
                n_ref=n_ref,
                n_gen=n_gen,
            ),
        )
