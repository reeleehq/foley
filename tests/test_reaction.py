"""Audience-reaction timing: reactions follow the event, repeats are smaller, a hush ducks."""

import pytest

from foley.weave.reaction import hush_plan, reaction_cue, reaction_plan


@pytest.mark.parametrize("kind", ["cheer", "laugh", "applause", "whistle", "gasp"])
def test_reaction_never_on_the_event(kind):
    c = reaction_cue(kind, 2.0)
    assert c.onset > 2.0 and c.onset < c.peak_t < c.end


def test_repeat_is_smaller_and_plan_orders_by_time():
    plan = reaction_plan([("cheer", 6.0), ("cheer", 1.0)])
    assert [c.event_t for c in plan] == [1.0, 6.0]
    assert plan[1].peak < plan[0].peak


def test_latency_override_and_unknown_kind():
    assert reaction_cue("laugh", 1.0, latency=0.1).onset == pytest.approx(1.1)
    with pytest.raises(KeyError):
        reaction_cue("boo", 1.0)


def test_hush_ducks_applause_after_it_peaks():
    a = reaction_cue("applause", 8.0)
    t, ducked = hush_plan(a)
    assert t > a.peak_t and ducked.end > t
