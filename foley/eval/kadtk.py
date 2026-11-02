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
    result.value   # kadtk's KAD: the unbiased MMD² times 100, so it can be negative
    result.params  # {'bandwidth': ..., 'scale': 100}

Two conventions differ from :func:`~foley.eval.fidelity.kernel_audio_distance`, so
the numbers agree only after accounting for them: kadtk reports the MMD² **times
100**, and its default bandwidth is torch's (lower) median of the pairwise distances
between the **generated** set's frames (foley's numpy default pools both sets). The
bandwidth used is returned in ``result.params``; pass it as ``bandwidth=`` to score a
second generator against the same reference on the same kernel. kadtk's EnCodec
embeddings are pooled to one frame per second of audio, and kadtk crashes on a clip
shorter than that, so such clips are refused here (:data:`KADTK_CLIP_RULES`).
Install: ``misc/docs/fidelity.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, NamedTuple, Optional

from .external_fidelity import DRIVER, ExternalFidelity
from .fadtk import FADTK_MODELS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

__all__ = ["DRIVER", "KADTK_MODELS", "KADTK_CLIP_RULES", "ClipRule", "KadtkFidelity"]

#: kadtk embedding models by kadtk's name → (loader class in ``kadtk.model_loader``,
#: its constructor args): fadtk's, plus the PANNs models. Extend with
#: ``KadtkFidelity(models={...})``. The default, ``encodec-emb``, downloads the
#: smallest weights (EnCodec 24 kHz, about 90 MB).
KADTK_MODELS: "Mapping[str, tuple[str, tuple]]" = {
    **FADTK_MODELS,
    "panns-cnn14-32k": ("PANNsModel", ("cnn14-32k",)),
    "panns-cnn14-16k": ("PANNsModel", ("cnn14-16k",)),
    "panns-wavegram-logmel": ("PANNsModel", ("wavegram-logmel",)),
}

#: The default kadtk model (lightest download; see :data:`KADTK_MODELS`).
DEFAULT_KADTK_MODEL = "encodec-emb"

#: The environment variable naming kadtk's interpreter when ``python=`` is not given.
KADTK_PYTHON_ENV = "FOLEY_KADTK_PYTHON"

#: Below this many embedding frames in a set, :class:`KadtkFidelity` warns: two sets
#: of the same noise gave KAD -1.49 at 8 frames and -0.37 at 50 (encodec-emb).
KADTK_WARN_FRAMES = 100

#: The audio kadtk pools into one embedding frame (``postprocess_resoultion``).
KADTK_POOLING_SECONDS = 1.0


class ClipRule(NamedTuple):
    """What a clip must be for kadtk to embed it with a given model.

    ``min_seconds``: the shortest clip. ``whole_seconds``: the length must be a whole
    number of pooling windows (kadtk embeds EnCodec 48 kHz per 1 s segment and pools
    each, so a partial last segment crashes it like a short clip).
    """

    min_seconds: float = 0.0
    whole_seconds: bool = False


#: kadtk model → :class:`ClipRule`; a model not listed accepts any clip.
KADTK_CLIP_RULES: "Mapping[str, ClipRule]" = {
    "encodec-emb": ClipRule(min_seconds=KADTK_POOLING_SECONDS),
    "encodec-emb-48k": ClipRule(min_seconds=KADTK_POOLING_SECONDS, whole_seconds=True),
}

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
            of the generated set's embedding frames; the one used is in ``params``).
        device: Where kadtk computes the kernel sums (``'cpu'``, ``'cuda'``, ``'mps'``).
        warn_frames: Warn below this many frames a set (default
            :data:`KADTK_WARN_FRAMES`; ``None`` never warns).
        clip_rule: What each clip must be (default: the model's in
            :data:`KADTK_CLIP_RULES`, else any clip).
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
        "maximum size for tensor at dimension": (
            f"kadtk pools this model's embedding per {KADTK_POOLING_SECONDS:g} s and "
            "crashes on a clip (or, for encodec-emb-48k, a last segment) shorter than "
            "that; use longer clips, or give the model a clip_rule"
        ),
    }

    def __init__(
        self,
        *,
        bandwidth: Optional[float] = None,
        device: str = "cpu",
        warn_frames: Optional[int] = KADTK_WARN_FRAMES,
        clip_rule: Optional[ClipRule] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.bandwidth, self.device, self.warn_frames = bandwidth, device, warn_frames
        self.clip_rule = (
            KADTK_CLIP_RULES.get(self.model, ClipRule()) if clip_rule is None else clip_rule
        )

    def frames_needed(self, dim: int) -> "tuple[int, str]":
        """Two frames: the unbiased MMD² averages over pairs of distinct frames."""
        return 2, "the unbiased MMD² averages over pairs of distinct frames"

    def check_clip(self, clip: "ndarray", *, sr: int, name: str) -> None:
        """Refuse a clip :attr:`clip_rule` says kadtk would crash on, before it runs."""
        rule, frames = self.clip_rule, len(clip)
        if frames < rule.min_seconds * sr:
            raise ValueError(
                f"clip {name} is {frames / sr:.3f} s; kadtk {self.model} needs at least "
                f"{rule.min_seconds:g} s a clip (it pools {KADTK_POOLING_SECONDS:g} s "
                "of audio into each embedding frame and crashes on less)"
            )
        if rule.whole_seconds and frames % round(KADTK_POOLING_SECONDS * sr):
            raise ValueError(
                f"clip {name} is {frames / sr:.3f} s; kadtk {self.model} embeds whole "
                f"{KADTK_POOLING_SECONDS:g} s segments and crashes on a partial last one"
            )

    def options(self) -> dict:
        """kadtk's bandwidth and device."""
        return {"bandwidth": self.bandwidth, "device": self.device}
