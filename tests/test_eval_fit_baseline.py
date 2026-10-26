"""The committed Tier-2 fit baseline and its gate (#49), hermetic: fake judge, no network."""

import json
from dataclasses import replace

import pytest

from foley.eval.baseline import (
    DEFAULT_FIT_BASELINE_PATH,
    check_fit_baseline,
    is_stale,
    load_baseline,
    write_fit_baseline,
)
from foley.eval.fit import run_fit_eval
from foley.eval.golden import DEFAULT_GOLDEN_PATH, RING0_CORPUS_PATH


@pytest.fixture(scope="module")
def report():
    return run_fit_eval()


def test_the_committed_fit_baseline_gates_the_hermetic_run(report):
    baseline = load_baseline(DEFAULT_FIT_BASELINE_PATH)
    ok, message = check_fit_baseline(report, baseline)
    assert ok, message
    assert baseline["metric"] == "fit_precision"
    assert baseline["run"]["judge"] == "StringOverlapJudge"


def test_the_committed_fit_baseline_is_not_stale():
    baseline = load_baseline(DEFAULT_FIT_BASELINE_PATH)
    assert not is_stale(
        baseline, seed_path=DEFAULT_GOLDEN_PATH, manifest_path=RING0_CORPUS_PATH
    )


def test_the_fit_gate_has_teeth(report):
    baseline = load_baseline(DEFAULT_FIT_BASELINE_PATH)
    worse = replace(
        report, fit_precision=baseline["value"] - baseline["tolerance"] - 0.01
    )
    ok, message = check_fit_baseline(worse, baseline)
    assert not ok and "floor=" in message
    edge = replace(report, fit_precision=baseline["value"] - baseline["tolerance"])
    assert check_fit_baseline(edge, baseline)[0]


@pytest.mark.parametrize(
    "change",
    [
        {"judge_model": "AnthropicJudge"},
        {"seed": 7},
        {"k": 5},
        {"embedder_model_id": "other"},
    ],
)
def test_a_run_under_other_settings_is_not_comparable_and_fails(report, change):
    baseline = load_baseline(DEFAULT_FIT_BASELINE_PATH)
    ok, message = check_fit_baseline(replace(report, **change), baseline)
    assert not ok and "not comparable" in message


def test_level_and_sample_are_part_of_the_run(report):
    baseline = load_baseline(DEFAULT_FIT_BASELINE_PATH)
    assert not check_fit_baseline(report, baseline, level="listen")[0]
    assert not check_fit_baseline(report, baseline, sample=50)[0]


def test_writing_a_baseline_records_the_run_and_the_fixture_stamps(report, tmp_path):
    path = tmp_path / "fit.json"
    written = write_fit_baseline(
        report, path=path, seed_path=DEFAULT_GOLDEN_PATH, manifest_path=RING0_CORPUS_PATH,
        updated_at="2026-10-26", n_items=156,
    )  # fmt: skip
    assert json.loads(path.read_text()) == written
    assert written["value"] == pytest.approx(report.fit_precision, abs=1e-6)
    assert not is_stale(
        written, seed_path=DEFAULT_GOLDEN_PATH, manifest_path=RING0_CORPUS_PATH
    )
    assert check_fit_baseline(report, written)[0]


def test_fit_report_gate_stays_a_noop_without_a_floor(report):
    assert report.gate(None) is True  # Tier-2 is still never a silent per-PR floor


def test_the_cli_gates_and_restamps(tmp_path, monkeypatch, capsys):
    from foley import cli

    assert cli.main(["eval-fit", "--baseline"]) == 0
    assert "PASS" in capsys.readouterr().out
    other = tmp_path / "fit.json"
    monkeypatch.setattr("foley.eval.baseline.DEFAULT_FIT_BASELINE_PATH", other)
    assert cli.main(["eval-fit", "--update-baseline"]) == 0
    assert json.loads(other.read_text())["metric"] == "fit_precision"


def test_a_changed_golden_set_fails_the_gate_instead_of_warning(report, tmp_path):
    baseline = load_baseline(DEFAULT_FIT_BASELINE_PATH)
    edited = tmp_path / "seed.json"
    edited.write_text(DEFAULT_GOLDEN_PATH.read_text() + " ")
    ok, message = check_fit_baseline(
        report, baseline, seed_path=edited, manifest_path=RING0_CORPUS_PATH
    )
    assert not ok and "stale" in message
    assert check_fit_baseline(
        report, baseline, seed_path=DEFAULT_GOLDEN_PATH, manifest_path=RING0_CORPUS_PATH
    )[0]
