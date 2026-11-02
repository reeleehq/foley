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
import subprocess
import sys
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

#: Install hint, printed when the interpreter is missing.
FADTK_INSTALL = (
    "uv venv ~/venvs/fadtk --python 3.11 && "
    "uv pip install --python ~/venvs/fadtk/bin/python fadtk torchcodec; "
    "then FadtkFidelity(python='~/venvs/fadtk/bin/python')"
)


def _write_set(wavs: Iterable, sr: int, folder: Path, *, prefix: str) -> int:
    """Write each waveform in ``wavs`` as a mono 16-bit WAV in ``folder``; return the count."""
    folder.mkdir(parents=True)
    n = 0
    for n, wav in enumerate(wavs, start=1):
        save(
            to_mono(wav),
            sr,
            folder / f"{prefix}{n:05d}.wav",
            fmt="WAV",
            subtype="PCM_16",
        )
    return n


class FadtkFidelity:
    """Set-level FAD computed by ``fadtk`` in a separate interpreter.

    Args:
        python: An interpreter with ``fadtk`` installed (default: this one, which works
            only if fadtk fits in foley's environment; usually point it at a venv).
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
        python: str = sys.executable,
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

        Raises:
            FileNotFoundError: If ``python`` is not an executable.
            RuntimeError: If fadtk fails (its output tail is in the message).
        """
        python = resolve_program(
            self.python, what="FadtkFidelity", install=FADTK_INSTALL
        )
        loader, args = self.models[self.model]
        with tempfile.TemporaryDirectory(prefix="foley-fadtk-") as tmp:
            ref, gen, out = (Path(tmp) / n for n in ("ref", "gen", "out.json"))
            n_ref = _write_set(ref_wavs, sr, ref, prefix="ref")
            n_gen = _write_set(gen_wavs, sr, gen, prefix="gen")
            if n_ref < 2 or n_gen < 2:
                raise ValueError("FAD needs at least 2 clips in each set")
            spec = {
                "loader": loader,
                "args": list(args),
                "ref": str(ref),
                "gen": str(gen),
                "out": str(out),
                "workers": self.workers,
            }
            answer = json.loads(
                run_program(
                    [python, "-I", str(DRIVER), json.dumps(spec)],
                    out=out,
                    runner=self.runner,
                    env=self.env,
                    timeout=self.timeout,
                    cwd=Path(tmp),
                    what=f"FadtkFidelity (fadtk {self.model})",
                )
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
