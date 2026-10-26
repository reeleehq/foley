"""Does a generated clip sound like what was asked for? A text-audio check, or an honest "unchecked".

Tier-0 QC (:mod:`foley.qc`) catches broken audio: clipping, silence, NaN. It cannot
catch a clean, well-levelled clip of the wrong thing, and a text-to-audio model
produces those: asked for "a flintlock musket placed into a hand", Stable Audio 3
returned a sound that had nothing to do with it, and it went through unflagged. That
is the job here: score the clip against its own prompt in a joint text-audio
embedding space (CLAP), and flag it when the score is under the embedder's threshold.

An embedder takes part only when it says its two spaces are comparable, by carrying a
``prompt_match_threshold`` (:class:`foley.index.embedders.ClapEmbedder` does). Anything
else, a test's bag-of-words fake, no embedder at all, an embedder whose model cannot
load on this host, gives ``status='unchecked'`` with the reason: never a silent pass.

The verdict is a flag, not a quarantine: the clip is kept (it was paid for) and the
candidate's notes and ``record.qc['prompt_match']`` say it does not match, so a person
or the SELECT agent listens before using it.

Zero-dependency import: ``numpy`` and the embedder's own stack load inside.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Optional

#: Where the per-checkpoint calibrated thresholds live (package data, so they ship in the
#: wheel). Written by :func:`foley.eval.prompt_match.save_threshold`.
THRESHOLDS_PATH = (
    Path(__file__).resolve().parent / "data" / "prompt_match" / "thresholds.json"
)

#: ``status`` values: the clip matches its prompt, does not, or was not checked.
MATCH, MISMATCH, UNCHECKED = "match", "mismatch", "unchecked"


def prompt_match(prompt: str, audio_bytes: bytes, *, embedder, fallback=None) -> dict:
    """Score ``audio_bytes`` against ``prompt`` with ``embedder``; never raises.

    Args:
        prompt: The text the clip was generated from.
        audio_bytes: The clip (any format ``soundfile`` decodes).
        embedder: A text-audio embedder (``embed_text`` / ``embed_audio``, L2-normalised
            vectors) carrying ``prompt_match_threshold``; anything else is ``unchecked``.
        fallback: A callable returning a second embedder (or ``None``), tried only when
            ``embedder`` was meant to check but could not run (it failed to load or
            embed: a small host without ``transformers``). Its own threshold applies and
            its model is named in the result. The default ``None`` tries nothing else.

    Returns:
        A JSON-safe dict: ``status`` (``match`` | ``mismatch`` | ``unchecked``), and
        ``score`` (cosine similarity), ``threshold`` and ``model`` when checked, or
        ``reason`` when not.

    >>> prompt_match("a door creak", b"", embedder=None)["status"]
    'unchecked'
    """
    result = _check(prompt, audio_bytes, embedder)
    if fallback is not None and _could_not_run(embedder, result):
        second = fallback()
        if second is not None:
            retry = _check(prompt, audio_bytes, second)
            if retry["status"] != UNCHECKED:
                return retry
            result = {
                **result,
                "reason": f"{result['reason']}; fallback {retry.get('model', 'embedder')}: "
                f"{retry['reason']}",
            }
    return result


def calibrated_threshold(
    model_id: str, override: Optional[float] = None, *, provisional: float
) -> float:
    """An embedder's prompt-match threshold: its override, else the calibration, else ``provisional``."""
    if override is not None:
        return override
    found = threshold_for(model_id)
    return provisional if found is None else found


def _could_not_run(embedder, result: dict) -> bool:
    """Whether ``embedder`` was meant to check (it has a threshold) yet came back unchecked."""
    return (
        result["status"] == UNCHECKED
        and getattr(embedder, "prompt_match_threshold", None) is not None
    )


def _check(prompt: str, audio_bytes: bytes, embedder) -> dict:
    """One embedder's verdict (the body of :func:`prompt_match`)."""
    threshold = getattr(embedder, "prompt_match_threshold", None)
    if embedder is None or threshold is None:
        what = "no embedder" if embedder is None else type(embedder).__name__
        return {
            "status": UNCHECKED,
            "reason": f"{what} does not compare text with audio (no prompt_match_threshold)",
        }
    model = getattr(embedder, "model_id", type(embedder).__name__)
    try:
        score = _cosine(prompt, audio_bytes, embedder)
    except Exception as exc:  # noqa: BLE001 - a check that cannot run is "unchecked"
        return {
            "status": UNCHECKED,
            "model": model,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": MATCH if score >= threshold else MISMATCH,
        "score": round(score, 4),
        "threshold": float(threshold),
        "model": model,
    }


def note_for(result: dict) -> Optional[str]:
    """The one-line candidate note for a :func:`prompt_match` result."""
    status = result.get("status")
    if status == MISMATCH:
        return (
            f"prompt match: MISMATCH, {result['model']} similarity {result['score']:.3f} "
            f"< {result['threshold']:.3f}; the clip may not be the sound asked for, "
            "listen before using it"
        )
    if status == UNCHECKED:
        return f"prompt match: unchecked ({result.get('reason')})"
    if status == MATCH:
        return f"prompt match: ok ({result['model']} similarity {result['score']:.3f})"
    return None


def _cosine(prompt: str, audio_bytes: bytes, embedder) -> float:
    import numpy as np

    from .audio import WORKING_SAMPLE_RATE, load, to_working

    wav, sr = load(audio_bytes)
    audio_vec = np.asarray(
        embedder.embed_audio(to_working(wav, sr), WORKING_SAMPLE_RATE), dtype=np.float64
    ).ravel()
    text_vec = np.asarray(embedder.embed_text(prompt), dtype=np.float64).reshape(-1)
    denom = float(np.linalg.norm(audio_vec) * np.linalg.norm(text_vec)) or 1.0
    return float(audio_vec @ text_vec) / denom


@functools.lru_cache(maxsize=8)
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
