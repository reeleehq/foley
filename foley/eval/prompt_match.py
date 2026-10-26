"""Calibrate the prompt-match threshold of a text-audio embedder on a labelled set (#111).

:func:`foley.prompt_match.prompt_match` flags a generated clip whose CLAP similarity to
its own prompt is under a threshold. That threshold depends on the checkpoint, so it is
measured, not guessed: given prompts and the clips generated for them, every prompt is
scored against every clip. A clip generated for its prompt is a *match*; the same clip
scored against another prompt is a *mismatch* (the failure the check exists for: a clean
clip of the wrong thing). :func:`calibrate_threshold` picks the cut that best separates
the two and reports precision and recall of the **mismatch** call; :func:`save_threshold`
records it per checkpoint in ``foley/data/prompt_match/thresholds.json``, which
:class:`foley.index.embedders.ClapEmbedder` reads.

The labels are only as good as the clips: a "match" is a clip generated for the prompt,
not one a person listened to, so a generation that missed its prompt counts as a match
and pulls the threshold down. Put by-ear labels in the manifest (``"match": false`` on a
clip) to correct that. Pure numpy/stdlib apart from the embedder passed in.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence

#: Where the per-checkpoint thresholds live (package data, so they ship in the wheel).
THRESHOLDS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "prompt_match" / "thresholds.json"
)


@dataclass(frozen=True)
class Calibration:
    """A measured threshold and what it achieves on the labelled set."""

    threshold: float
    precision: float  # of the clips called mismatch, the share that are
    recall: float  # of the true mismatches, the share called
    f1: float
    match_kept: float  # of the matches, the share not flagged (1 - false-alarm rate)
    auc: float  # chance that a random match outscores a random mismatch
    n_match: int
    n_mismatch: int
    match_mean: float
    mismatch_mean: float

    def to_dict(self) -> dict:
        return {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in asdict(self).items()
        }


def score_pairs(
    embedder, items: "Sequence[tuple[str, bytes, bool]]"
) -> "list[tuple[float, bool]]":
    """Every prompt against every clip: ``[(cosine, is_match), ...]``.

    ``items`` is ``[(prompt, clip_bytes, clip_matches_prompt), ...]``. Pair ``(i, i)`` is a
    match when its flag is true (a clip a listener rejected counts as a mismatch); pair ``(i, j)`` with ``i != j`` is a mismatch (clip ``j``
    was made for another prompt). Embeddings are computed once per prompt and per clip.
    """
    import numpy as np

    from ..audio import WORKING_SAMPLE_RATE, load, to_working

    texts = np.vstack(
        [np.asarray(embedder.embed_text(p)).reshape(-1) for p, _, _ in items]
    )
    audio = []
    for _, blob, _ in items:
        wav, sr = load(blob)
        audio.append(
            np.asarray(
                embedder.embed_audio(to_working(wav, sr), WORKING_SAMPLE_RATE)
            ).ravel()
        )
    audio = np.vstack(audio)
    texts = texts / np.linalg.norm(texts, axis=1, keepdims=True)
    audio = audio / np.linalg.norm(audio, axis=1, keepdims=True)
    sims = texts @ audio.T
    return [
        (float(sims[i, j]), bool(items[i][2]) if i == j else False)
        for i in range(len(items))
        for j in range(len(items))
    ]


def calibrate_threshold(scores: "Sequence[tuple[float, bool]]") -> Calibration:
    """The threshold under which a clip is called a mismatch, maximising balanced accuracy.

    Balanced accuracy (the mean of the share of mismatches caught and the share of matches
    kept) because the set has far more mismatch pairs (n² - n) than matches (n): plain F1
    would be won by a threshold that flags most good clips. A false alarm costs a listen,
    a miss costs a wrong sound in the film; this weighs them equally, and :class:`Calibration`
    reports precision and recall so the trade can be re-struck.

    Args:
        scores: ``[(similarity, is_match), ...]`` from :func:`score_pairs`.

    Raises:
        ValueError: If either class is empty.
    """
    import numpy as np

    s = np.array([x for x, _ in scores], dtype=float)
    match = np.array([m for _, m in scores], dtype=bool)
    if match.all() or not match.any():
        raise ValueError("calibration needs both matches and mismatches")
    neg_scores, pos_scores = s[~match], s[match]
    candidates = np.unique(s)

    def balanced(t: float) -> float:
        """Mean of the mismatches caught and the matches kept at threshold ``t``."""
        return float(((neg_scores < t).mean() + (pos_scores >= t).mean()) / 2)

    # ties go to the higher threshold: it catches more wrong clips
    t = max(candidates, key=lambda c: (round(balanced(c), 12), c))
    lower = candidates[candidates < t]
    if (
        lower.size
    ):  # midpoint to the next lower observed score: the cut is not on a sample
        t = (t + lower[-1]) / 2
    t = float(t)
    called = s < t
    tp, fp = int((called & ~match).sum()), int((called & match).sum())
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = float((neg_scores < t).mean())
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    auc = float(
        (pos_scores[:, None] > neg_scores[None, :]).mean()
        + 0.5 * (pos_scores[:, None] == neg_scores[None, :]).mean()
    )
    return Calibration(
        threshold=t, precision=precision, recall=recall, f1=f1,
        match_kept=float((pos_scores >= t).mean()), auc=auc,
        n_match=int(match.sum()), n_mismatch=int((~match).sum()),
        match_mean=float(pos_scores.mean()), mismatch_mean=float(neg_scores.mean()),
    )  # fmt: skip


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    """``{model_id: calibration dict}``; empty when nothing has been calibrated."""
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}


def threshold_for(model_id: str, *, path: Path = THRESHOLDS_PATH) -> Optional[float]:
    """The calibrated threshold of checkpoint ``model_id``, or ``None``."""
    entry = load_thresholds(path).get(model_id)
    return None if entry is None else float(entry["threshold"])


def save_threshold(
    model_id: str,
    calibration: Calibration,
    *,
    source: str,
    path: Path = THRESHOLDS_PATH,
) -> None:
    """Record ``calibration`` for ``model_id`` (``source``: what set it was measured on)."""
    data = load_thresholds(path)
    data[model_id] = {**calibration.to_dict(), "calibrated_on": source}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
