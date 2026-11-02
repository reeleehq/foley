"""Reference KAD from ``kadtk``, run in its own interpreter (#262).

:func:`foley.eval.fidelity.kernel_audio_distance` is the KAD math (unbiased RBF MMD²)
in pure numpy. `kadtk <https://github.com/YoonjinXD/kadtk>`_ is the reference toolkit
of the KAD paper, a fork of fadtk with the same embedding models; version 1.1 needs
Python < 3.12, ``numpy<2``, ``torch<2.6`` and ``transformers<4.47``, so it cannot share
foley's environment. :class:`KadtkFidelity` runs it through
:class:`~foley.eval.external_fidelity.ExternalFidelity` exactly as
:class:`~foley.eval.fadtk.FadtkFidelity` runs fadtk, and stamps ``toolkit='kadtk'``.

::

    kad = KadtkFidelity(python="~/venvs/kadtk/bin/python")
    result = kad(reference_wavs, generated_wavs, sr=48000)
    result.value  # kadtk's KAD: the MMD² times 100

Two conventions differ from :func:`~foley.eval.fidelity.kernel_audio_distance`, so
the numbers agree only after accounting for them: kadtk reports the MMD² **times
100**, and its default bandwidth is the median pairwise distance of the **generated**
set's frames (foley's numpy default pools both sets). kadtk's EnCodec embeddings are
pooled to one frame per second of audio, dropping a trailing partial second, so a
clip shorter than a second contributes no frame. Install: ``misc/docs/fidelity.md``.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .external_fidelity import DRIVER, ExternalFidelity

__all__ = ["DRIVER", "KADTK_MODELS", "KadtkFidelity"]

#: kadtk embedding models by kadtk's name → (loader class in ``kadtk.model_loader``,
#: its constructor args). Extend with ``KadtkFidelity(models={...})``. The default,
#: ``encodec-emb``, downloads the smallest weights (EnCodec 24 kHz, about 90 MB).
KADTK_MODELS: "Mapping[str, tuple[str, tuple]]" = {
    "encodec-emb": ("EncodecEmbModel", ("24k",)),
    "encodec-emb-48k": ("EncodecEmbModel", ("48k",)),
    "vggish": ("VGGishModel", ()),
    "panns-cnn14-32k": ("PANNsModel", ("cnn14-32k",)),
    "panns-cnn14-16k": ("PANNsModel", ("cnn14-16k",)),
    "panns-wavegram-logmel": ("PANNsModel", ("wavegram-logmel",)),
    "clap-laion-audio": ("CLAPLaionModel", ("audio",)),
    "clap-laion-music": ("CLAPLaionModel", ("music",)),
    "clap-2023": ("CLAPModel", ("2023",)),
}

#: The default kadtk model (lightest download; see :data:`KADTK_MODELS`).
DEFAULT_KADTK_MODEL = "encodec-emb"

#: The environment variable naming kadtk's interpreter when ``python=`` is not given.
KADTK_PYTHON_ENV = "FOLEY_KADTK_PYTHON"

#: Install hint. ``--managed-python``: kadtk imports ``turtle``, so the interpreter
#: needs Tk, which uv's own builds have and Homebrew's often lack. torchaudio must be
#: pinned to the torch kadtk resolves (2.5.1), or its native library fails to load.
KADTK_INSTALL = (
    "uv venv ~/venvs/kadtk --python 3.11 --managed-python && "
    "uv pip install --python ~/venvs/kadtk/bin/python kadtk torchaudio==2.5.1; "
    f"then KadtkFidelity(python='~/venvs/kadtk/bin/python') or set {KADTK_PYTHON_ENV}"
)


class KadtkFidelity(ExternalFidelity):
    """Set-level KAD computed by ``kadtk`` in a separate interpreter.

    Args: those of :class:`~foley.eval.external_fidelity.ExternalFidelity`, plus:
        bandwidth: The RBF bandwidth (default: kadtk's, the median pairwise distance
            of the generated set's embedding frames).
        device: Where kadtk computes the kernel sums (``'cpu'``, ``'cuda'``, ``'mps'``).
    ``model`` is a key of :data:`KADTK_MODELS` (default :data:`DEFAULT_KADTK_MODEL`).
    """

    toolkit = "kadtk"
    metric = "kad"
    default_models = KADTK_MODELS
    default_model = DEFAULT_KADTK_MODEL
    python_env = KADTK_PYTHON_ENV
    install = KADTK_INSTALL
    failure_hints = {
        "No module named '_tkinter'": (
            "kadtk imports turtle, which needs Tk; build the venv on a Python that has "
            f"it. Install: {KADTK_INSTALL}"
        ),
        "_aoti_torch_abi_version": (
            "torchaudio does not match torch; pin torchaudio to torch's version. "
            f"Install: {KADTK_INSTALL}"
        ),
    }

    def __init__(
        self, *, bandwidth: Optional[float] = None, device: str = "cpu", **kwargs
    ):
        super().__init__(**kwargs)
        self.bandwidth, self.device = bandwidth, device

    def frames_needed(self, dim: int) -> "tuple[int, str]":
        """Two frames: the unbiased MMD² averages over pairs of distinct frames."""
        return 2, "the unbiased MMD² averages over pairs of distinct frames"

    def options(self) -> dict:
        """kadtk's bandwidth and device."""
        return {"bandwidth": self.bandwidth, "device": self.device}
