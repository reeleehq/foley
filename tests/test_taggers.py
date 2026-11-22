"""Tests for the ingest taggers (``foley.index.taggers``).

The lightweight checks (default UCS label set, custom labels, the PANNs
missing-dependency guard) always run. The real CLAP zero-shot tagging check is
opt-in via ``FOLEY_RUN_CLAP=1`` (needs ``foley[clap]`` + the cached weights),
mirroring the embedder tests.
"""

import importlib.util
import os

import pytest


def _clap_opt_in() -> bool:
    if os.environ.get("FOLEY_RUN_CLAP") != "1":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


requires_clap = pytest.mark.skipif(
    not _clap_opt_in(), reason="opt-in: set FOLEY_RUN_CLAP=1 (needs foley[clap])"
)


# ---------------------------------------------------------------------------
# ClapZeroShotTagger — label vocabulary (no model load)
# ---------------------------------------------------------------------------


def test_zeroshot_default_labels_are_natural_ucs_phrases():
    from foley.index.taggers import ClapZeroShotTagger

    labels = ClapZeroShotTagger().labels
    assert labels  # non-empty
    # natural "category subcategory" phrases, not bare abstract words
    assert "rain" in labels and "doors wood" in labels  # RAIN/GENERAL: bare
    assert "air misc" not in labels and not any(l.startswith("archived") for l in labels)
    assert all(label == label.lower() for label in labels)
    assert len(labels) == len(set(labels))  # deduped


def test_zeroshot_custom_labels_override_default():
    from foley.index.taggers import ClapZeroShotTagger

    tagger = ClapZeroShotTagger(labels=["rain", "thunder"])
    assert tagger.labels == ["rain", "thunder"]


# ---------------------------------------------------------------------------
# PannsTagger — missing-dependency guard
# ---------------------------------------------------------------------------


def test_panns_tagger_raises_importerror_without_extra():
    from foley.index.taggers import PannsTagger

    if importlib.util.find_spec("panns_inference") is not None:
        pytest.skip("panns-inference installed; the missing-dep path can't be tested")
    np = pytest.importorskip("numpy")
    with pytest.raises(ImportError, match="foley\\[tag\\]"):
        PannsTagger().tag(np.zeros(1000, dtype=np.float32), 48_000)


# ---------------------------------------------------------------------------
# real CLAP zero-shot tagging (opt-in)
# ---------------------------------------------------------------------------


@requires_clap
def test_zeroshot_ranks_a_tone_and_tag_vector_reuse_matches():
    import numpy as np

    from foley.index.embedders import default_embedder
    from foley.index.taggers import ClapZeroShotTagger

    emb = default_embedder()
    labels = ["a musical tone", "rain", "thunder", "a dog barking"]
    tagger = ClapZeroShotTagger(embedder=emb, labels=labels)

    sr = 44100
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr).astype(np.float32)
    tags = tagger.tag(tone, sr, top_k=4)
    assert tags[0][0] == "a musical tone"  # nearest label to a pure tone

    # tag_vector on the precomputed embedding matches tag() exactly (the reuse seam)
    vec = emb.embed_audio(tone, sr)
    assert [lbl for lbl, _ in tagger.tag_vector(vec, top_k=4)] == [
        lbl for lbl, _ in tags
    ]
