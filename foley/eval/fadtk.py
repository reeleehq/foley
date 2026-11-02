"""Reference FAD from Microsoft's ``fadtk``, run in its own interpreter (#48).

:func:`foley.eval.fidelity.frechet_distance` is the FAD math in pure numpy, fed by any
embedder. To report a number comparable with published ones, use the reference
toolkit, `fadtk <https://github.com/microsoft/fadtk>`_: its embedding models, its
audio loading and resampling, its statistics. fadtk 1.1 pins ``numpy<2`` and pulls
torch, torchvision and two CLAP packages, so it cannot share foley's environment.
:class:`FadtkFidelity` runs it through :class:`~foley.eval.external_fidelity.ExternalFidelity`
(temporary wav sets, :mod:`foley.eval.toolkit_driver` in fadtk's interpreter, a
:class:`~foley.eval.fidelity.FidelityResult` stamped ``toolkit='fadtk'``). Nothing
from fadtk is imported here.

::

    fad = FadtkFidelity(python="~/venvs/fadtk/bin/python")
    result = fad(reference_wavs, generated_wavs, sr=48000)
    result.value, result.stamp  # FAD, FidelityStamp(embedding='encodec-emb', toolkit='fadtk', ...)

fadtk's FAD is over embedding **frames** (every frame of every clip), not one vector
per clip as :func:`~foley.eval.fidelity.generation_fidelity` takes, so the two numbers
differ unless fed the same frames. Install and model choice: ``misc/docs/fidelity.md``.
"""

from __future__ import annotations

from typing import Mapping

from .external_fidelity import DRIVER, ExternalFidelity

__all__ = ["DRIVER", "FADTK_MODELS", "FadtkFidelity"]

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

#: The environment variable naming fadtk's interpreter when ``python=`` is not given.
FADTK_PYTHON_ENV = "FOLEY_FADTK_PYTHON"

#: Install hint, printed when the interpreter is missing or lacks fadtk.
FADTK_INSTALL = (
    "uv venv ~/venvs/fadtk --python 3.11 && "
    "uv pip install --python ~/venvs/fadtk/bin/python fadtk torchcodec; "
    f"then FadtkFidelity(python='~/venvs/fadtk/bin/python') or set {FADTK_PYTHON_ENV}"
)


class FadtkFidelity(ExternalFidelity):
    """Set-level FAD computed by ``fadtk`` in a separate interpreter.

    Args: those of :class:`~foley.eval.external_fidelity.ExternalFidelity`; ``model``
    is a key of :data:`FADTK_MODELS` (default :data:`DEFAULT_FADTK_MODEL`).
    """

    toolkit = "fadtk"
    metric = "fad"
    default_models = FADTK_MODELS
    default_model = DEFAULT_FADTK_MODEL
    python_env = FADTK_PYTHON_ENV
    install = FADTK_INSTALL

    def frames_needed(self, dim: int) -> "tuple[int, str]":
        """More frames than dimensions, or the covariance is singular and FAD meaningless."""
        return dim + 1, (
            f"more frames than the {dim}-dim embedding has dimensions, "
            "or the covariance is singular"
        )
