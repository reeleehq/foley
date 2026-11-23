"""reeleehq/foley#316: one spend tolerance; layers checked before any paid call."""

import pytest


def test_landing_on_the_cap_through_float_addition_is_no_overshoot():
    from foley.agent.policy import Budget

    b = Budget(max_usd=0.3)
    for _ in range(3):
        b.reserve(0.1, what="call")
        b.settle(0.1, 0.1)
    assert b.overshoot_usd == 0.0


def test_a_layer_typo_raises_before_the_decompose_call(monkeypatch):
    import foley
    from foley.agent import tools

    calls = []
    real = tools.decompose_context

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(tools, "decompose_context", counting)
    with pytest.raises(ValueError, match="not a mix layer"):
        foley.find("The heavy oak door creaked.", layers={"ambiance"})
    with pytest.raises(ValueError, match="not a mix layer"):
        foley.score("The heavy oak door creaked.", layers={"ambiance"}, allow_generate=False)
    assert not calls


def test_a_single_layer_name_is_one_layer():
    from foley.base import Layer, checked_layers

    assert checked_layers("ambience") == {Layer.ambience}
