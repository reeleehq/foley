"""Calibrating the prompt-match threshold per checkpoint (#111)."""

import json

import pytest

np = pytest.importorskip("numpy")

from foley.eval.prompt_match import (  # noqa: E402
    calibrate_threshold,
    load_thresholds,
    save_threshold,
    threshold_for,
)
from foley.index.embedders import (  # noqa: E402
    PROVISIONAL_PROMPT_MATCH_THRESHOLD,
    ClapEmbedder,
)


def _scores(n_match=20, n_mismatch=380, seed=0):
    rng = np.random.default_rng(seed)
    return [(float(x), True) for x in rng.normal(0.30, 0.05, n_match)] + [
        (float(x), False) for x in rng.normal(0.00, 0.05, n_mismatch)
    ]


def test_the_cut_falls_between_two_separated_classes():
    c = calibrate_threshold(_scores())
    assert 0.05 < c.threshold < 0.25
    assert c.recall > 0.95 and c.match_kept > 0.95 and c.auc > 0.99
    assert (c.n_match, c.n_mismatch) == (20, 380)


def test_a_class_imbalance_does_not_flag_the_good_clips():
    """With 19x more mismatches, plain F1 would pick a cut that flags many matches."""
    overlap = [(0.10 + 0.003 * i, True) for i in range(20)] + [
        (0.10 * np.sin(i) + 0.05, False) for i in range(380)
    ]
    assert calibrate_threshold(overlap).match_kept >= 0.5


def test_both_classes_are_required():
    with pytest.raises(ValueError, match="both"):
        calibrate_threshold([(0.3, True), (0.2, True)])


def test_thresholds_round_trip_per_checkpoint(tmp_path):
    path = tmp_path / "t.json"
    assert load_thresholds(path) == {} and threshold_for("m", path=path) is None
    save_threshold("m", calibrate_threshold(_scores()), source="synthetic", path=path)
    assert threshold_for("m", path=path) == pytest.approx(
        json.loads(path.read_text())["m"]["threshold"]
    )
    assert json.loads(path.read_text())["m"]["calibrated_on"] == "synthetic"


def test_the_embedder_reads_its_checkpoints_calibration():
    default = ClapEmbedder().prompt_match_threshold
    assert default != PROVISIONAL_PROMPT_MATCH_THRESHOLD  # the shipped calibration
    assert ClapEmbedder("someone/else-clap").prompt_match_threshold == (
        PROVISIONAL_PROMPT_MATCH_THRESHOLD
    )
