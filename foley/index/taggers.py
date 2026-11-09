"""Taggers — auto-fill a sound's semantic labels on ingest (report 03).

Two default taggers behind the :class:`~foley.index.protocols.Tagger` protocol:

    * :class:`ClapZeroShotTagger` — foley's default. Scores a clip against a
      custom/UCS label set by CLAP cosine (report 03 Part 2), **reusing the same
      embedder the Index already loads** — so ingest never loads CLAP twice and
      it needs no dependency beyond ``foley[clap]``.
    * :class:`PannsTagger` — PANNs CNN14 supervised tagging over the 527 AudioSet
      classes (report 03 Part 1); ``foley[tag]``. The checkpoint auto-downloads
      (~327 MB) on first use.

Captioners (EnCLAP / Qwen2-Audio, ``foley[caption]``) plug in behind the
:class:`~foley.index.protocols.Captioner` protocol as adapters; none ships as a
default yet (no clean, permissively-licensed, pip-installable checkpoint), so the
ingest caption stage is off unless a captioner is injected.

Heavy deps (``torch``/``transformers``/``panns_inference``) are lazy-imported, so
importing this module costs only the stdlib.
"""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: Prompt template for zero-shot CLAP tagging (report 03 Part 2).
ZEROSHOT_PROMPT: str = "this is a sound of {label}"

#: PANNs CNN14 expects 32 kHz mono audio.
PANNS_SAMPLE_RATE: int = 32_000


# ---------------------------------------------------------------------------
# ClapZeroShotTagger — the default (reuses the CLAP embedder, no extra dep)
# ---------------------------------------------------------------------------


class ClapZeroShotTagger:
    """Zero-shot tagger: score a clip against a label set via CLAP cosine.

    Reuses a :class:`~foley.index.embedders.ClapEmbedder` (the same model the
    Index uses), so the audio is embedded in the same joint space as the label
    prompts and no extra weights load. The default label set is the UCS
    subcategory names (foley's own vocabulary), so tags land in-taxonomy.
    """

    def __init__(
        self,
        *,
        embedder=None,
        labels: Optional[Sequence[str]] = None,
        prompt: str = ZEROSHOT_PROMPT,
        threshold: float = 0.0,
    ):
        """Create the tagger.

        Args:
            embedder: A CLAP embedder (default: the process-wide default).
            labels: The label vocabulary to score against (default: UCS
                subcategory names from the taxonomy table).
            prompt: Template turning a label into a text prompt.
            threshold: Minimum cosine score to keep a tag.
        """
        self._embedder = embedder
        self._labels = list(labels) if labels is not None else None
        self.prompt = prompt
        self.threshold = threshold

    @cached_property
    def embedder(self):
        """The CLAP embedder (injected or the process-wide default)."""
        if self._embedder is not None:
            return self._embedder
        from .embedders import default_embedder

        return default_embedder()

    @cached_property
    def labels(self) -> "list[str]":
        """The label vocabulary (default: natural UCS ``category subcategory`` phrases).

        Natural multi-word phrases (``"weather rain"``, ``"glass break"``) are far
        better CLAP prompts — and better BM25 tags / taxonomy-resolver input — than
        bare abstract subcategory words (``"Break"``, ``"Buzz"``); a generic
        subcategory (``GENERAL``, ``MISC``) gives the bare category, and the
        ``ARCHIVED`` bookkeeping rows give none, which are a known
        zero-shot artifact (anomalously close to everything). Absolute tag-quality
        calibration (thresholds, label curation) is an eval-harness concern (#10).
        """
        if self._labels is not None:
            return self._labels
        from .taxonomy import NON_SOUND_CATEGORIES, default_ucs_table

        seen: list[str] = []
        for row in default_ucs_table():
            if row.category in NON_SOUND_CATEGORIES:
                continue
            cat = (row.category or "").strip().lower()
            sub = (row.subcategory or "").strip().lower()
            label = cat if (not sub or row.is_generic) else f"{cat} {sub}"
            label = label.strip()
            if label and label not in seen:
                seen.append(label)
        return seen

    @cached_property
    def _label_matrix(self) -> "ndarray":
        prompts = [self.prompt.format(label=label) for label in self.labels]
        return self.embedder.embed_text(prompts)  # (n_labels, dim), L2-normalized

    def tag_vector(
        self, audio_vec: "ndarray", *, top_k: int = 10
    ) -> "list[tuple[str, float]]":
        """Score a **precomputed** (L2-normalized) audio vector against the labels.

        The efficiency seam (report 03 Part 2): the Index already embeds every
        sound with this model, so on ingest the retrieval vector is reused here —
        no second CLAP forward pass.
        """
        import numpy as np

        if not self.labels:
            return []
        scores = self._label_matrix @ np.asarray(audio_vec)  # cosine (normalized)
        order = np.argsort(-scores)[: max(top_k, 0)]
        return [
            (self.labels[i], float(scores[i]))
            for i in order
            if scores[i] >= self.threshold
        ]

    def tag(
        self, wav: "ndarray", sr: int, *, taxonomy: str = "custom", top_k: int = 10
    ) -> "list[tuple[str, float]]":
        """Return the top-``k`` ``(label, cosine)`` tags for the clip, best first."""
        return self.tag_vector(self.embedder.embed_audio(wav, sr), top_k=top_k)


# ---------------------------------------------------------------------------
# PannsTagger — supervised AudioSet tagging (foley[tag])
# ---------------------------------------------------------------------------


#: Where panns-inference keeps (and, when missing, ``wget``-downloads) its files.
PANNS_DATA_DIR = "~/panns_data"
PANNS_FILES = ("Cnn14_mAP=0.431.pth", "class_labels_indices.csv")
#: panns-inference treats a smaller checkpoint as incomplete and fetches it again.
PANNS_CHECKPOINT_MIN_BYTES = 300_000_000


def _require_panns_files() -> None:
    """Under :func:`foley.offline`, refuse before panns-inference can ``wget`` its files.

    Importing ``panns_inference`` downloads its label CSV when missing, and
    ``AudioTagging(checkpoint_path=None)`` downloads the checkpoint, so this check runs
    before either.
    """
    from ..runtime import require_local_files

    paths = [f"{PANNS_DATA_DIR}/{name}" for name in PANNS_FILES]
    require_local_files(
        paths,
        what="the PANNs tagger",
        # panns-inference re-downloads a checkpoint under 300 MB (a truncated wget)
        min_bytes={paths[0]: PANNS_CHECKPOINT_MIN_BYTES},
        how_to_fetch="run `foley.index.PannsTagger().tag(...)` once online "
        f"(panns-inference saves them to {PANNS_DATA_DIR}).",
    )


class PannsTagger:
    """PANNs CNN14 supervised tagger over the 527 AudioSet classes (``foley[tag]``).

    The checkpoint auto-downloads to ``~/panns_data`` (~327 MB) on the first
    :meth:`tag`. PANNs expects 32 kHz mono; the clip is resampled via
    :func:`foley.audio.to_working`.
    """

    def __init__(self, *, device: str = "cpu", threshold: float = 0.1):
        """Create the tagger (model loads lazily on first :meth:`tag`)."""
        self._device = device
        self.threshold = threshold

    @cached_property
    def _model(self):
        _require_panns_files()
        try:
            from panns_inference import AudioTagging
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise ImportError(
                "PannsTagger needs the 'foley[tag]' extra (panns-inference)."
            ) from exc
        return AudioTagging(checkpoint_path=None, device=self._device)

    @cached_property
    def _labels(self):
        _require_panns_files()
        from panns_inference import labels

        return labels

    def tag(
        self, wav: "ndarray", sr: int, *, taxonomy: str = "audioset", top_k: int = 10
    ) -> "list[tuple[str, float]]":
        """Return the top-``k`` ``(AudioSet label, score)`` tags, best first."""
        import numpy as np

        from ..audio import to_working

        clip = to_working(wav, sr, mono=True, target_sr=PANNS_SAMPLE_RATE)[None, :]
        clipwise, _embedding = self._model.inference(clip)  # (1, 527), (1, 2048)
        scores = clipwise[0]
        order = np.argsort(-scores)[: max(top_k, 0)]
        return [
            (str(self._labels[i]), float(scores[i]))
            for i in order
            if scores[i] >= self.threshold
        ]


# ---------------------------------------------------------------------------
# Default factories (process-wide singletons, mirroring default_embedder)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def default_tagger() -> PannsTagger:
    """The default supervised tagger (PANNs CNN14; ``foley[tag]``)."""
    return PannsTagger()


@lru_cache(maxsize=None)
def default_zeroshot_tagger(embedder=None) -> ClapZeroShotTagger:
    """The default zero-shot tagger (CLAP vs UCS subcategories; ``foley[clap]``).

    Cached **per embedder** so the tagger is bound to the SAME embedder that
    produced the audio vector it scores — otherwise (report seam) the cosine would
    cross two unrelated embedding spaces. ``embedder=None`` uses the process-wide
    default embedder.
    """
    return ClapZeroShotTagger(embedder=embedder)
