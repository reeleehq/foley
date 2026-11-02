"""The tasteful-weave eval (#45): the four pure metrics, the designer seam, the report."""

import json

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley import cli  # noqa: E402
from foley.base import (  # noqa: E402
    Anchor,
    Layer,
    LicenseRecord,
    Placement,
    SoundDesignTimeline,
    SoundRecord,
    TimelineItem,
)
from foley.eval import taste  # noqa: E402
from foley.licensing import NO_RECORD_REASON, intended_use_for  # noqa: E402
from foley.score import ScoreResult  # noqa: E402
from foley.weave.timeline import nudge  # noqa: E402

WT = [
    {"word": w, "start": i * 0.5, "end": (i + 1) * 0.5}
    for i, w in enumerate("The heavy door slammed. Rain fell.".split())
]


@pytest.fixture(autouse=True)
def _obs_to_memory():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


def _woven(*items):
    return SoundDesignTimeline(items=list(items), word_timeline=list(WT))


def _spot(cue, *, onset, pre_roll=0.0, clip="a"):
    return TimelineItem(
        clip_ref=clip,
        onset=cue,
        placement=Placement(anchor=Anchor.word, ref="door", onset=onset, pre_roll=pre_roll),
    )


# --- pure metrics -------------------------------------------------------------


@pytest.mark.parametrize(
    "text, n",
    [
        ("One. Two! Three?", 3),
        ("no terminal punctuation", 1),
        ("Mr. Smith arrived. Dr. Jones left.", 2),  # abbreviations
        ("Wait... the door", 1),  # an ellipsis is not a full stop
        ('He said "Go." She went.', 2),  # closing quote after the terminator
        ("Yes.No.", 2),  # no space before the next sentence
        ("See e.g. the U.S. Army. Then go.", 2),  # single-letter periods
        ("", 0),
    ],
)
def test_count_sentences(text, n):
    assert taste.count_sentences(text) == n


def test_passage_sentences_counts_at_least_one_per_segment():
    p = taste.Passage(id="p", segments=("Mr. Smith", "Wait...", "One. Two."))
    assert taste.passage_sentences(p) == 4


def test_restraint_checks_the_ceiling_per_passage():
    assert taste.restraint(1, 3)["within_ceiling"]
    assert taste.restraint(0, 3)["within_ceiling"]  # a quiet passage left quiet is fine
    assert not taste.restraint(4, 3)["within_ceiling"]  # sound soup
    assert taste.restraint(4, 3, band=(0.0, 2.0))["within_ceiling"]  # keyword override


def test_licence_rows_are_fail_closed():
    use = intended_use_for(None)  # commercial publishing
    clean = SoundRecord(id="ok", license=LicenseRecord(source="t", license_id="CC0-1.0", commercial_ok=True, rights_verified=True))
    nc = SoundRecord(id="nc", license=LicenseRecord(source="t", license_id="CC-BY-NC-4.0", commercial_ok=False, rights_verified=True))
    lib = {"ok": clean, "nc": nc}
    items = [TimelineItem(clip_ref=c) for c in ("ok", "nc", "ghost")]
    rows = {r["clip_ref"]: r for r in taste.licence_rows(items, lib, use)}
    assert rows["ok"]["clean"] and rows["ok"]["reason"] is None
    assert not rows["nc"]["clean"] and rows["nc"]["reason"]
    assert not rows["ghost"]["clean"] and rows["ghost"]["reason"] == NO_RECORD_REASON


def test_placement_on_the_trigger_word_is_ok_with_pre_roll_folded_back():
    (row,) = taste.placement_rows(_woven(_spot("on 'door'", onset=0.9, pre_roll=0.1)))
    assert row["trigger_s"] == 1.0 and row["expected_onset_s"] == pytest.approx(0.9)
    assert row["error_s"] == pytest.approx(0.0) and row["ok"]


def test_pre_roll_on_the_first_word_is_clamped_like_the_render():
    item = TimelineItem(
        clip_ref="a",
        onset="on 'The'",
        placement=Placement(anchor=Anchor.word, ref="The", onset=0.0, pre_roll=0.3),
    )
    (row,) = taste.placement_rows(_woven(item))
    assert row["expected_onset_s"] == 0.0 and row["error_s"] == 0.0 and row["ok"]


def test_a_nudged_spot_is_measured_against_its_original_cue():
    tl = _woven(_spot("on 'door'", onset=1.0))
    (row,) = taste.placement_rows(nudge(tl, "a", 0.6))  # pins the anchor to absolute
    assert row["trigger_s"] == 1.0 and row["error_s"] == pytest.approx(0.6)
    assert not row["ok"]
    (row,) = taste.placement_rows(nudge(tl, "a", 0.6), tolerance_s=1.0)
    assert row["ok"]


def test_a_spot_with_no_trigger_is_not_ok_but_a_bed_with_no_cue_is():
    stray = TimelineItem(clip_ref="s", onset="on 'xylophone'", placement=Placement(onset=0.0))
    nocue = TimelineItem(clip_ref="n", onset=None, placement=Placement(onset=0.0))
    bed = TimelineItem(
        clip_ref="b",
        layer=Layer.ambience,
        loop=True,
        placement=Placement(anchor=Anchor.sentence, onset=0.0),
    )
    rows = {r["clip_ref"]: r for r in taste.placement_rows(_woven(stray, nocue, bed))}
    assert rows["s"]["trigger_s"] is None and not rows["s"]["ok"]  # cue word not spoken
    assert rows["n"]["trigger_s"] is None and not rows["n"]["ok"]
    assert rows["b"]["ok"] and rows["b"]["trigger_s"] == 0.0


def test_disabled_items_are_not_measured():
    item = _spot("on 'door'", onset=5.0)
    item.enabled = False
    assert taste.placement_rows(_woven(item)) == []


def test_loudness_row_is_none_unwoven():
    assert taste.loudness_row(None) is None


@pytest.mark.parametrize(
    "alignment, aligned", [(None, False), ("fake", False), ("whisperx", True), ("cached", True)]
)
def test_aligned_only_for_a_real_alignment(alignment, aligned):
    assert taste.PassageTaste(passage_id="p", alignment=alignment).aligned is aligned


# --- the harness ---------------------------------------------------------------


def test_default_run_is_offline_json_safe_and_restrained():
    report = taste.run_taste_eval()
    d = report.to_dict()
    json.dumps(d, allow_nan=False)  # JSON-safe: no NaN / inf
    s = d["summary"]
    assert s["n_passages"] == len(taste.load_passages()) and s["n_failed"] == 0
    assert s["n_sounds"] >= 1
    assert s["licence_clean_share"] == 1.0 and s["licence_target_met"]
    # unedited cues pass placement by construction: assert only that each sound is measured
    rows = [r for p in report.passages for r in p.placement]
    assert len(rows) == s["n_sounds"] and all(r["error_s"] is not None for r in rows)
    assert s["placement_caveat"] == taste.PLACEMENT_CAVEAT
    assert s["within_ceiling_share"] == 1.0
    assert s["aligned_share"] == 0.0  # plan-only: estimated word timings
    assert {p.alignment for p in report.passages} == {"fake"}
    assert s["n_woven"] == 0 and s["loudness_ok_share"] is None
    assert d["designer"] == "foley.score"
    assert d["thresholds"]["placement_tolerance_s"] == taste.PLACEMENT_TOLERANCE_S
    md = report.to_markdown()
    assert "restraint" in md and "licence cleanliness" in md and "storm_window" in md
    assert "by construction" in md


def test_a_passage_with_audio_is_woven_and_hits_the_master_target():
    pytest.importorskip("scipy")
    sr = 48_000
    rng = np.random.default_rng(0)
    narration = (0.1 * rng.standard_normal(sr * 8)).astype("float32")
    passage = taste.Passage(
        id="door", segments=("He left.", "The heavy door slammed shut."), audio=narration
    )
    report = taste.run_taste_eval([passage])
    (p,) = report.passages
    # the default designer pins the fake aligner, so the timings are estimates
    assert p.error is None and p.alignment == "fake" and not p.aligned
    assert p.loudness["target_lufs"] == -16.0
    assert p.loudness["ok"] and abs(p.loudness["delta_lu"]) <= taste.LOUDNESS_TOLERANCE_LU
    assert report.summary()["n_woven"] == 1
    json.dumps(report.to_dict(), allow_nan=False)


def test_a_plugged_designer_is_measured_and_its_failures_are_reported():
    nc = SoundRecord(id="nc", license=LicenseRecord(source="t", license_id="CC-BY-NC-4.0", commercial_ok=False, rights_verified=True))
    library = {"nc": nc}

    def sloppy(passage):
        if passage.id == "boom":
            raise RuntimeError("agent gave up")
        items = [TimelineItem(clip_ref="nc", onset="on 'door'") for _ in range(4)]
        return ScoreResult(timeline=SoundDesignTimeline(items=items), events=[])

    passages = [
        {"id": "door", "segments": ["The door slammed."]},
        {"id": "boom", "segments": ["Nothing."]},
    ]
    report = taste.run_taste_eval(
        passages,
        designer=sloppy,
        library=library,
        thresholds=taste.TasteThresholds(licence_clean_target=0.5),
    )
    door, boom = report.passages
    assert boom.error == "RuntimeError: agent gave up"
    assert not door.restraint["within_ceiling"]  # four sounds on one sentence
    assert door.licence_clean_share == 0.0
    s = report.summary()
    assert s["n_failed"] == 1 and not s["licence_target_met"]
    assert report.designer == "sloppy" and report.thresholds.licence_clean_target == 0.5
    assert report.to_dict()["thresholds"]["licence_clean_target"] == 0.5
    assert "over ceiling" in report.to_markdown() and "agent gave up" in report.to_markdown()


def test_load_passages_resolves_audio_relative_to_the_file(tmp_path):
    (tmp_path / "set.json").write_text(
        json.dumps([{"id": "x", "segments": ["A."], "audio": "x.wav"}]), encoding="utf-8"
    )
    (p,) = taste.load_passages(tmp_path / "set.json")
    assert p.audio == str(tmp_path / "x.wav") and p.text == "A."


def test_a_metric_bug_is_not_hidden_as_a_passage_error(monkeypatch):
    def broken(*a, **k):
        raise ZeroDivisionError("metric bug")

    monkeypatch.setattr(taste, "placement_rows", broken)
    with pytest.raises(ZeroDivisionError):
        taste.run_taste_eval([{"id": "d", "segments": ["The door slammed."]}])


def test_a_malformed_passage_set_is_refused_up_front_naming_each_bad_passage():
    calls = []
    with pytest.raises(ValueError, match=r"#1 \(b\): unknown keys \['mood'\].*#2 \(\?\)"):
        taste.run_taste_eval(
            [
                {"id": "a", "segments": ["A."]},
                {"id": "b", "segments": ["B."], "mood": "calm"},
                {"segments": ["C."]},
            ],
            designer=calls.append,
            library={},
        )
    assert calls == []  # nothing ran


def test_cli_eval_taste_json(capsys):
    assert cli.main(["eval-taste", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["n_passages"] >= 1


def test_cli_eval_taste_fails_only_when_every_passage_errored(tmp_path, monkeypatch):
    path = tmp_path / "set.json"
    path.write_text(json.dumps([{"id": "x", "segments": ["A."]}]), encoding="utf-8")

    def boom(**kwargs):
        def design(passage):
            raise RuntimeError("down")

        return design

    monkeypatch.setattr(taste, "score_designer", boom)
    assert cli.main(["eval-taste", "--passages", str(path)]) == 1
