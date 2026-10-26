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
        [("a door creak", ("a.wav", "sa3"), ("b.wav", "eleven"))] * 6, seed=1
    )
    m, mk = panel.mushra_tasks(
        [("a door creak", "ref.wav", [("a.wav", "sa3"), ("b.wav", "eleven")], "anchor.wav")] * 5, seed=1
    )  # fmt: skip
    return g + p + m, {**gk, **pk, **mk}


def test_tasks_carry_no_system_names_and_the_key_holds_them(tmp_path):
    tasks, key = _all_tasks()
    tasks_path, key_path = panel.save_tasks(tasks, key, tmp_path)
    blind = tasks_path.read_text()
    assert (
        "sa3" not in blind and "eleven" not in blind and "hidden_reference" not in blind
    )
    assert panel.load_tasks(tasks_path) == tasks
    assert panel.load_key(key_path) == key
    assert {v["system"] for v in key.values()} >= {
        "sa3",
        "eleven",
        "hidden_reference",
        "anchor",
    }


def test_sides_and_order_are_shuffled_but_reproducible():
    one, _ = panel.pairwise_tasks([("p", ("a.wav", "A"), ("b.wav", "B"))] * 40, seed=5)
    two, _ = panel.pairwise_tasks([("p", ("a.wav", "A"), ("b.wav", "B"))] * 40, seed=5)
    assert one == two
    first_clips = {t.stimuli[0].clip for t in one}
    assert first_clips == {"a.wav", "b.wav"}  # both sides occur on the left


def test_the_listening_page_embeds_blind_tasks_only():
    tasks, _ = _all_tasks()
    page = render_panel_html(tasks, title="Door <test>")
    assert "sa3" not in page and "eleven" not in page and "hidden_reference" not in page
    assert "Door &lt;test&gt;" in page and '"m0000"' in page
    assert "</script><" not in page.split("<script>", 1)[1].rsplit("</script>", 1)[0]


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
    assert units["u3"] == {"ann": 3, "bo": 3}
    agree = panel.calibrate_against_judge(
        units, {f"u{i}": g for i, g in enumerate(human)}
    )
    assert agree["human_alpha"].alpha == pytest.approx(1.0)
    assert (
        agree["judge_vs_human"].alpha == pytest.approx(1.0)
        and agree["judge_vs_human"].promoted
    )
    random_judge = {
        f"u{i}": g for i, g in enumerate([3, 0, 1, 2, 0, 3, 2, 1, 0, 1, 3, 2])
    }
    off = panel.calibrate_against_judge(units, random_judge)
    assert off["judge_vs_human"].alpha < 0.667 and not off["judge_vs_human"].promoted
    assert off["n_units"] == 12 and off["raters"] == ["ann", "bo"]


def test_mushra_systems_are_rating_units_the_reference_is_not():
    tasks, key = _all_tasks()
    rows = _mushra_responses(
        tasks, key, "ann", reference_score=95, scores={"sa3": 90, "eleven": 30}
    )
    units = panel.rating_units(tasks, key, rows)
    assert units["a door creak|sa3"] == {"ann": 3} and units["a door creak|eleven"] == {
        "ann": 1
    }
    assert not any("hidden" in u or "anchor" in u for u in units)


def test_a_single_rater_has_no_human_alpha_and_too_few_units_no_judge_alpha():
    out = panel.calibrate_against_judge({"u": {"ann": 2}}, {"u": 2})
    assert out["human_alpha"] is None and out["judge_vs_human"] is None
