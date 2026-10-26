"""Embedders — the joint text<->audio space that powers retrieval.

The default is **LAION-CLAP** ``laion/larger_clap_general`` (512-d, Apache-2.0):
one space serves both text->audio search and audio<->audio similarity, it is
trained on general/environmental sound (not just music/speech), and its license
is clean for a widely-installed façade (report 04 §1.2, §6.3). It lives behind
the :class:`~foley.index.protocols.Embedder` protocol so MS-CLAP, PANNs, or GLAP
can be dropped in by keyword injection; every record stores the
``embedding_model``/``embedding_dim`` it was indexed under so mixed-model
libraries stay coherent.

``torch``/``transformers`` are lazy-imported (the ``foley[clap]`` extra), so
importing this module — and constructing a :class:`ClapEmbedder` — costs only the
stdlib; the ~1.7 GB checkpoint loads on the first ``embed_*`` call.
"""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: The default CLAP checkpoint (LAION, Apache-2.0, general/environmental sound).
DEFAULT_CLAP_MODEL_ID: str = "laion/larger_clap_general"

#: Sample rate CLAP expects at its audio input (report 04 §1.2).
CLAP_SAMPLE_RATE: int = 48_000

#: Embedding width for the default checkpoint (verified: ``projection_dim=512``).
DEFAULT_CLAP_DIM: int = 512


#: The prompt-match threshold of a checkpoint with no calibration on record. LAION-CLAP
#: puts matching text-audio pairs around 0.3-0.5 and unrelated ones near 0-0.15; this is
#: a guess between them, not a measurement.
PROVISIONAL_PROMPT_MATCH_THRESHOLD: float = 0.2


class ClapEmbedder:
    """LAION-CLAP text<->audio embedder (the default retrieval engine).

    Returns **L2-normalized** ``float32`` embeddings so a plain inner product is
    cosine similarity. ``embed_text`` always returns a 2-D ``(n, dim)`` array;
    ``embed_audio`` returns a 1-D ``(dim,)`` array for one clip.

    Attributes:
        model_id: The HF checkpoint id.
        dim: The embedding dimensionality.
        open_source: Whether the checkpoint is an open-source model (the LAION
            releases are). Read by the ingest AI-use gate for sounds whose rights
            holder allows only open-source models (#69).
    """

    @property
    def prompt_match_threshold(self) -> float:
        """Cosine similarity under which a generated clip is flagged as not matching its prompt.

        Calibrated per checkpoint on a labelled set (:mod:`foley.eval.prompt_match`,
        ``foley/data/prompt_match/thresholds.json``); a checkpoint nobody has calibrated
        gets :data:`PROVISIONAL_PROMPT_MATCH_THRESHOLD`.
        """
        from ..prompt_match import threshold_for

        if self._prompt_match_threshold is not None:
            return self._prompt_match_threshold
        found = threshold_for(self.model_id)
        return PROVISIONAL_PROMPT_MATCH_THRESHOLD if found is None else found

    def __init__(
        self,
        model_id: str = DEFAULT_CLAP_MODEL_ID,
        *,
        device=None,
        prompt_match_threshold: Optional[float] = None,
    ):
        """Create the embedder (model weights load lazily on first use).

        Args:
            model_id: A CLAP checkpoint on the HF Hub.
            device: Optional torch device string; defaults to CUDA when available,
                else CPU.
            prompt_match_threshold: Override the calibrated prompt-match threshold.
        """
        self.model_id = model_id
        self._prompt_match_threshold = prompt_match_threshold
        self.open_source = model_id.startswith("laion/")
        self._device = device
        # Known for the default checkpoint; resolved lazily (from the lightweight
        # config, not the weights) for others so ``dim`` is never a bad sentinel.
        self._dim = DEFAULT_CLAP_DIM if model_id == DEFAULT_CLAP_MODEL_ID else None

    @property
    def dim(self) -> int:
        """The embedding dimensionality (512 for the default; resolved for others).

        For a non-default checkpoint this fetches only the model's ``config.json``
        (via ``AutoConfig``) — never the ~1.7 GB weights — so building an index
        for it does not force a model download. Falls back to the loaded model's
        config if the standalone config lacks ``projection_dim``.
        """
        if self._dim is None:
            self._dim = self._resolve_dim()
        return self._dim

    def _resolve_dim(self) -> int:
        from ..runtime import EgressBlocked

        try:
            from transformers import AutoConfig

            from ..runtime import load_pretrained

            cfg = load_pretrained(AutoConfig.from_pretrained, self.model_id)
            proj = getattr(cfg, "projection_dim", None)
            if proj:
                return int(proj)
        except EgressBlocked:
            raise  # offline and not cached: say so, do not fall back to a download
        except Exception:
            pass
        return int(getattr(self._model.config, "projection_dim", DEFAULT_CLAP_DIM))

    @cached_property
    def device(self) -> str:
        """The resolved torch device string (``'cuda'``/``'cpu'``)."""
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise ImportError(
                "ClapEmbedder needs the 'foley[clap]' extra (transformers, torch)."
            ) from exc
        if self._device is not None:
            return self._device
        return "cuda" if torch.cuda.is_available() else "cpu"

    @cached_property
    def _model(self):
        from transformers import ClapModel

        from ..runtime import load_pretrained

        model = load_pretrained(ClapModel.from_pretrained, self.model_id)
        model = model.to(self.device).eval()
        # Trust the loaded config for the dim (keeps non-default checkpoints
        # coherent) — the ``dim`` property caches it via ``_resolve_dim``.
        proj = getattr(model.config, "projection_dim", None)
        if proj:
            self._dim = int(proj)
        return model

    @cached_property
    def _processor(self):
        from transformers import ClapProcessor

        from ..runtime import load_pretrained

        return load_pretrained(ClapProcessor.from_pretrained, self.model_id)

    @staticmethod
    def _l2(features) -> "ndarray":
        import numpy as np
        import torch

        normed = torch.nn.functional.normalize(features, p=2, dim=-1)
        return normed.detach().cpu().numpy().astype(np.float32)

    def embed_text(self, text: Union[str, list[str]]) -> "ndarray":
        """Embed one or more query strings -> ``(n_texts, dim)`` L2-normalized."""
        import torch

        if isinstance(text, str):
            text = [text]
        inputs = self._processor(text=text, return_tensors="pt", padding=True).to(
            self.device
        )
        with torch.no_grad():
            feats = self._model.get_text_features(**inputs)
        return self._l2(feats)

    def _process_audio(self, wav, sr: int):
        # transformers 4.57.1 accepts both ``audio=`` (new) and ``audios=``
        # (deprecated, removed in 4.59); older versions accept only ``audios=``.
        try:
            return self._processor(audio=wav, sampling_rate=sr, return_tensors="pt")
        except TypeError:
            return self._processor(audios=wav, sampling_rate=sr, return_tensors="pt")

    def embed_audio(self, wav: "ndarray", sr: int) -> "ndarray":
        """Embed one audio clip -> ``(dim,)`` L2-normalized.

        The clip is down-mixed to mono and resampled to 48 kHz (what CLAP expects)
        via :mod:`foley.audio` before embedding.

        Args:
            wav: A working-array clip (``float32``; mono or multichannel).
            sr: The clip's sample rate in Hz.
        """
        import torch

        from ..audio import to_working

        wav48 = to_working(wav, sr, mono=True, target_sr=CLAP_SAMPLE_RATE)
        inputs = self._process_audio(wav48, CLAP_SAMPLE_RATE).to(self.device)
        with torch.no_grad():
            feats = self._model.get_audio_features(**inputs)
        return self._l2(feats)[0]


@lru_cache(maxsize=1)
def default_embedder() -> ClapEmbedder:
    """Return a process-wide default :class:`ClapEmbedder` (loaded once, reused).

    Cached so repeated ``foley.search()`` calls share a single loaded model.
    """
    return ClapEmbedder()
