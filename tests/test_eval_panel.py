"""Human-panel infrastructure (#49): Bradley-Terry, blind tasks, responses, MUSHRA screening, the α feed."""

import json
import math

import pytest

np = pytest.importorskip("numpy")

from foley.eval import bradley_terry as bt  # noqa: E402
from foley.eval import panel  # noqa: E402
from foley.eval.panel_page import render_panel_html  # noqa: E402

# ---------------------------------------------------------------------------
# Bradley-Terry
# ---------------------------------------------------------------------------


def test_two_items_recover_the_win_odds_exactly():
    fitted = bt.fit([("a", "b")] * 3 + [("b", "a")], prior=0)
    assert math.exp(fitted.scores[0] - fitted.scores[1]) == pytest.approx(3.0)
    assert fitted.ranking() == ["a", "b"] and fitted.converged
    assert fitted.p_win("a", "b") == pytest.approx(0.75)
    assert sum(fitted.scores) == pytest.approx(0.0)


def test_three_items_rank_by_strength_and_the_prior_keeps_a_winless_item_finite():
    games = [("a", "b")] * 8 + [("b", "c")] * 8 + [("a", "c")] * 8  # c never wins
    plain = bt.fit(games)
    assert plain.ranking() == ["a", "b", "c"]
    assert all(math.isfinite(s) for s in plain.scores)


def test_bootstrap_intervals_are_seeded_and_bracket_the_estimate():
    games = (
        [("a", "b")] * 30 + [("b", "a")] * 10 + [("b", "c")] * 20 + [("c", "b")] * 20
    )
    one = bt.fit(games, bootstrap=200, seed=3)
    two = bt.fit(games, bootstrap=200, seed=3)
    assert one.ci == two.ci
    for score, (lo, hi) in zip(one.scores, one.ci):
        assert lo <= score <= hi


def test_bradley_terry_rejects_a_self_comparison_and_a_single_item():
    with pytest.raises(ValueError, match="different items"):
        bt.fit([("a", "a")])
    with pytest.raises(ValueError, match="two distinct"):
        bt.fit([])


# ---------------------------------------------------------------------------
# tasks stay blind
# ---------------------------------------------------------------------------


def _all_tasks():
    g, gk = panel.grade_tasks(
        [("u1", "a door creak", "a.wav", "sa3"), ("u2", "rain", "b.wav", "eleven")]
    )
    p, pk = panel.pairwise_tasks(
        [("u1", "a door creak", ("a.wav", "sa3"), ("b.wav", "eleven"))] * 6, seed=1
    )
    m, mk = panel.mushra_tasks(
        [("u1", "a door creak", "ref.wav", [("a.wav", "sa3"), ("b.wav", "eleven")], "anchor.wav")] * 5, seed=1
    )  # fmt: skip
    return g + p + m, {**gk, **pk, **mk}


@pytest.fixture
def clips(tmp_path):
    """Real clip files named after their systems, as a careless user would."""
    root = tmp_path / "renders"
    root.mkdir()
    for name in ("sa3_door", "eleven_door", "reference", "anchor_lowpass"):
        (root / f"{name}.wav").write_bytes(name.encode())
    return root


def test_saved_tasks_carry_no_system_names_even_when_the_clips_do(tmp_path, clips):
    tasks, key = panel.mushra_tasks(
        [("u1", "a door creak", str(clips / "reference.wav"),
          [(str(clips / "sa3_door.wav"), "sa3"), (str(clips / "eleven_door.wav"), "eleven")],
          str(clips / "anchor_lowpass.wav"))] * 3, seed=1,
    )  # fmt: skip
    tasks_path, key_path, blind = panel.save_tasks(tasks, key, tmp_path / "panel")
    text = tasks_path.read_text()
    for leak in ("sa3", "eleven", "anchor", "lowpass", "hidden_reference", "renders"):
        assert leak not in text
    assert panel.load_tasks(tasks_path) == blind
    assert panel.load_key(key_path) == key
    for t in blind:  # every clip was copied under its opaque id
        for s in t.stimuli:
            assert (tmp_path / "panel" / s.clip).is_file() and s.id in s.clip
    # the hidden reference does not share a path with the visible one
    assert all(t.reference not in {s.clip for s in t.stimuli} for t in blind)
    page = render_panel_html(blind)
    assert "sa3" not in page and "eleven" not in page and "lowpass" not in page


def test_a_clip_that_is_not_a_local_file_is_refused(tmp_path):
    tasks, key = panel.grade_tasks([("u1", "p", "https://x/y.wav", "s")])
    with pytest.raises(FileNotFoundError, match="local file"):
        panel.save_tasks(tasks, key, tmp_path)


def test_sides_and_order_are_shuffled_but_reproducible():
    one, _ = panel.pairwise_tasks(
        [("u", "p", ("a.wav", "A"), ("b.wav", "B"))] * 40, seed=5
    )
    two, _ = panel.pairwise_tasks(
        [("u", "p", ("a.wav", "A"), ("b.wav", "B"))] * 40, seed=5
    )
    assert one == two
    first_clips = {t.stimuli[0].clip for t in one}
    assert first_clips == {"a.wav", "b.wav"}  # both sides occur on the left


def test_the_page_script_block_cannot_be_closed_or_commented_out_by_a_prompt():
    tasks, _ = panel.grade_tasks(
        [("u", "</script><script>x()</script> <!--", "a.wav", "s")]
    )
    page = render_panel_html(tasks, title="Door <test>")
    body = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    assert "</script" not in body and "<!--" not in body
    assert "Door &lt;test&gt;" in page


# ---------------------------------------------------------------------------
# responses and analysis
# ---------------------------------------------------------------------------


def test_answers_are_validated_per_kind():
    tasks, _ = _all_tasks()
    g, p, m = tasks[0], tasks[2], tasks[-1]
    panel.check_answer(g, 3)
    for bad in (4, -1, "3", True, None):
        with pytest.raises(ValueError):
            panel.check_answer(g, bad)
    panel.check_answer(p, None)  # a tie
    panel.check_answer(p, p.stimuli[0].id)
    with pytest.raises(ValueError):
        panel.check_answer(p, "elsewhere")
    panel.check_answer(m, {s.id: 50 for s in m.stimuli})
    with pytest.raises(ValueError):
        panel.check_answer(m, {m.stimuli[0].id: 50})  # not every stimulus
    with pytest.raises(ValueError):
        panel.check_answer(m, {s.id: 101 for s in m.stimuli})
    with pytest.raises(ValueError):
        panel.check_answer(m, {s.id: True for s in m.stimuli})  # a bool is not a score
    with pytest.raises(ValueError):
        panel.check_answer(
            p, [p.stimuli[0].id]
        )  # unhashable: ValueError, not TypeError


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_responses_load_validated_and_the_last_answer_wins(tmp_path):
    tasks, _ = _all_tasks()
    rows = [
        {"rater": "ann", "task": "g0000", "answer": 1},
        {"rater": "ann", "task": "g0000", "answer": 3},
    ]
    assert panel.load_responses(_write(tmp_path / "r.jsonl", rows), tasks) == [rows[1]]
    with pytest.raises(ValueError, match="unknown task"):
        panel.load_responses(
            _write(tmp_path / "r2.jsonl", [{"rater": "a", "task": "zz", "answer": 1}]),
            tasks,
        )
    for bad_line in (
        "[1, 2]",
        '{"rater": 5, "task": "g0000", "answer": 1}',
        '{"rater": "a", "task": "g0000"}',
    ):
        (tmp_path / "r4.jsonl").write_text(bad_line + "\n")
        with pytest.raises(ValueError):
            panel.load_responses(tmp_path / "r4.jsonl", tasks)
    with pytest.raises(ValueError, match="bad answer"):
        panel.load_responses(
            _write(
                tmp_path / "r3.jsonl", [{"rater": "a", "task": "g0000", "answer": 9}]
            ),
            tasks,
        )


def test_2afc_answers_become_system_comparisons_for_bradley_terry():
    tasks, key = _all_tasks()
    pair_tasks = [t for t in tasks if t.kind == panel.PAIRWISE]
    responses = []
    for t in pair_tasks:  # the rater always picks the "sa3" clip, except one tie
        sa3 = next(s.id for s in t.stimuli if key[s.id]["system"] == "sa3")
        responses.append({"rater": "ann", "task": t.id, "answer": sa3})
    responses[0]["answer"] = None
    comps = panel.pairwise_comparisons(tasks, key, responses)
    assert comps == [("sa3", "eleven")] * 5
    assert bt.fit(comps).ranking() == ["sa3", "eleven"]


def _mushra_responses(tasks, key, rater, *, reference_score, scores):
    out = []
    for t in (t for t in tasks if t.kind == panel.MUSHRA):
        answer = {}
        for s in t.stimuli:
            k = key[s.id]
            answer[s.id] = (
                reference_score
                if k["role"] == "reference"
                else scores.get(k["system"], 10)
            )
        out.append({"rater": rater, "task": t.id, "answer": answer})
    return out


def test_mushra_screening_drops_a_rater_who_misses_the_hidden_reference():
    tasks, key = _all_tasks()
    good = _mushra_responses(
        tasks, key, "good", reference_score=98, scores={"sa3": 80, "eleven": 60}
    )
    bad = _mushra_responses(
        tasks, key, "bad", reference_score=40, scores={"sa3": 10, "eleven": 90}
    )
    accepted, rejected = panel.screen_mushra(tasks, key, good + bad)
    assert accepted == ["good"] and rejected == {"bad": 1.0}
    scores = panel.mushra_scores(tasks, key, good + bad)
    assert (
        scores["sa3"][0] == 80 and scores["eleven"][0] == 60
    )  # the rejected rater is out
    assert scores["hidden_reference"][0] == 98 and scores["anchor"][0] == 10
    assert panel.mushra_scores(tasks, key, good + bad, raters=["bad"])["sa3"][0] == 10


def test_mushra_scores_bin_to_the_zero_to_three_grades():
    assert [panel.mushra_to_grade(s) for s in (0, 24.9, 25, 59, 60, 84, 85, 100)] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
    ]


def test_the_panel_feeds_the_judge_vs_human_alpha():
    tasks, key = panel.grade_tasks(
        [(f"u{i}", f"p{i}", f"{i}.wav", "sa3") for i in range(12)]
    )
    human = [0, 1, 2, 3, 3, 2, 1, 0, 3, 2, 1, 0]
    rows = [
        {"rater": r, "task": t.id, "answer": g}
        for r in ("ann", "bo")
        for t, g in zip(tasks, human)
    ]
    units = panel.rating_units(tasks, key, rows)
    assert units["u3|sa3"] == {"ann": 3, "bo": 3}
    agree = panel.calibrate_against_judge(
        units, {f"u{i}|sa3": g for i, g in enumerate(human)}, min_raters=2, min_units=10
    )
    assert agree["human_alpha"].alpha == pytest.approx(1.0)
    assert (
        agree["judge_vs_human"].alpha == pytest.approx(1.0)
        and agree["judge_vs_human"].promoted
    )
    random_judge = {
        f"u{i}|sa3": g for i, g in enumerate([3, 0, 1, 2, 0, 3, 2, 1, 0, 1, 3, 2])
    }
    off = panel.calibrate_against_judge(units, random_judge, min_raters=2, min_units=10)
    assert off["judge_vs_human"].alpha < 0.667 and not off["judge_vs_human"].promoted
    assert off["n_units"] == 12 and off["raters"] == ["ann", "bo"]


def test_mushra_systems_are_rating_units_the_reference_is_not():
    tasks, key = _all_tasks()
    rows = _mushra_responses(
        tasks, key, "ann", reference_score=95, scores={"sa3": 90, "eleven": 30}
    )
    units = panel.rating_units(tasks, key, rows)
    assert units["u1|sa3"] == {"ann": 3} and units["u1|eleven"] == {"ann": 1}
    assert not any("hidden" in u or "anchor" in u for u in units)


def test_a_single_rater_has_no_human_alpha_and_too_few_units_no_judge_alpha():
    out = panel.calibrate_against_judge(
        {"u": {"ann": 2}}, {"u": 2}, min_raters=1, min_units=1
    )
    assert out["human_alpha"] is None and out["judge_vs_human"] is None


def test_two_systems_graded_on_one_unit_do_not_overwrite_each_other():
    tasks, key = panel.grade_tasks(
        [("u1", "p", "a.wav", "sa3"), ("u1", "p", "b.wav", "eleven")]
    )
    rows = [
        {"rater": "ann", "task": tasks[0].id, "answer": 3},
        {"rater": "ann", "task": tasks[1].id, "answer": 0},
    ]
    assert panel.rating_units(tasks, key, rows) == {
        "u1|sa3": {"ann": 3},
        "u1|eleven": {"ann": 0},
    }


def test_a_judge_is_not_promoted_on_too_few_raters_units_or_no_variation():
    grades = [0, 1, 2, 3, 3, 2, 1, 0]
    tasks, key = panel.grade_tasks([(f"u{i}", "p", f"{i}.wav", "s") for i in range(8)])
    rows = [{"rater": "ann", "task": t.id, "answer": g} for t, g in zip(tasks, grades)]
    units = panel.rating_units(tasks, key, rows)
    judge = {f"u{i}|s": g for i, g in enumerate(grades)}
    thin = panel.calibrate_against_judge(units, judge)  # defaults: 3 raters, 50 units
    assert (
        thin["judge_vs_human"].alpha == pytest.approx(1.0)
        and not thin["judge_vs_human"].promoted
    )
    assert any("raters" in r for r in thin["insufficient"]) and any(
        "units" in r for r in thin["insufficient"]
    )
    flat_units = {u: {"ann": 2, "bo": 2, "cy": 2} for u in judge}
    flat = panel.calibrate_against_judge(flat_units, {u: 2 for u in judge}, min_units=1)
    assert (
        "the grades do not vary" in flat["insufficient"]
        and not flat["judge_vs_human"].promoted
    )


def test_bradley_terry_reports_islands_and_refuses_a_winless_item_without_a_prior():
    islands = bt.fit([("a", "b"), ("b", "a"), ("c", "d"), ("d", "c")])
    assert not islands.connected
    assert bt.fit([("a", "b"), ("b", "c")]).connected
    with pytest.raises(ValueError, match="prior"):
        bt.fit([("a", "b")] * 3, prior=0)
