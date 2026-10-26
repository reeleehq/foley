"""Tests for the Tier-2 fit-evaluation harness — ``foley.eval`` fit / reliability / fidelity (#10b).

Everything runs hermetically: Krippendorff's α and FAD/KAD are pure numpy validated
against known-value / synthetic fixtures; the fit harness runs the real SELECT loop over
the Ring-0 golden set with the deterministic ``StringOverlapJudge`` fake; and two guards
(a static namespace check + a runtime call-spy with a byte-identical Tier-1 nDCG re-run)
prove the retrieval ranking / nDCG@10 gate is never touched.
"""

import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.agent import StringOverlapJudge  # noqa: E402
from foley.eval import (  # noqa: E402
    ALPHA_RELIABLE,
    FidelityResult,
    FitReport,
    calibrate_judge_vs_human,
    fit_f1,
    fit_precision,
    fit_recall,
    frechet_distance,
    generation_fidelity,
    kernel_audio_distance,
    krippendorff_alpha,
    percent_agreement,
    reliability_band,
    run_fit_eval,
    stratified_sample,
)

nan = np.nan

# Krippendorff's canonical published reliability-data example (units = columns).
_CANONICAL = np.array(
    [
        [1, 2, 3, 3, 2, 1, 4, 1, 2, nan, nan, nan],
        [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, nan, nan],
        [nan, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, 3],
        [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, nan],
    ],
    dtype=float,
)


# ---------------------------------------------------------------------------
# reliability — Krippendorff's α
# ---------------------------------------------------------------------------


def test_krippendorff_canonical_values():
    """α matches Krippendorff's published values for the canonical fixture (to 3dp)."""
    assert krippendorff_alpha(_CANONICAL, level="nominal") == pytest.approx(0.743, abs=0.001)
    assert krippendorff_alpha(_CANONICAL, level="ordinal") == pytest.approx(0.815, abs=0.001)
    assert krippendorff_alpha(_CANONICAL, level="interval") == pytest.approx(0.849, abs=0.001)


def test_krippendorff_degenerate():
    """Perfect agreement → 1.0; a single-rater / empty matrix → 1.0 (no expected disagreement)."""
    assert krippendorff_alpha(np.array([[1, 2, 3, 4], [1, 2, 3, 4]], dtype=float)) == 1.0
    assert krippendorff_alpha(np.array([[1, 2, 3]], dtype=float)) == 1.0  # one rater


def test_reliability_band():
    """The α → benchmark band mapping."""
    assert reliability_band(0.9) == "reliable"
    assert reliability_band(0.7) == "tentative"
    assert reliability_band(0.5) == "revise-rubric"
    assert reliability_band(ALPHA_RELIABLE) == "reliable"


def test_percent_agreement():
    """Raw pairwise agreement is co-reported (bounded 0..1, 1.0 on perfect agreement)."""
    assert percent_agreement(np.array([[1, 2, 3], [1, 2, 3]], dtype=float)) == 1.0
    assert 0.0 <= percent_agreement(_CANONICAL) <= 1.0


def test_calibrate_judge_vs_human():
    """The judge-vs-human calibration record codifies the promotion rule (α ≥ reliable)."""
    human = [2, 1, 3, 2, 0, 1]
    good = calibrate_judge_vs_human(human, human)  # a judge that agrees perfectly
    assert good.alpha == 1.0 and good.band == "reliable" and good.promoted is True
    bad = calibrate_judge_vs_human(human, [0, 3, 0, 3, 2, 3])  # a disagreeing judge
    assert bad.alpha < ALPHA_RELIABLE and bad.promoted is False
    assert bad.n_raters == 2


# ---------------------------------------------------------------------------
# fidelity — FAD / KAD
# ---------------------------------------------------------------------------


def test_frechet_distance_properties():
    """FAD is 0 on identical distributions, symmetric, and grows with mean separation."""
    rng = np.random.default_rng(0)
    A = rng.standard_normal((300, 8))
    B = rng.standard_normal((300, 8))
    C = rng.standard_normal((300, 8)) + 3.0
    assert frechet_distance(A, A) == pytest.approx(0.0, abs=1e-6)
    assert frechet_distance(A, C) == pytest.approx(frechet_distance(C, A))
    assert frechet_distance(A, C) > frechet_distance(A, B)
    # a mean shift of 3 across 8 dims contributes ~8·9 to the FAD
    assert frechet_distance(A, C) == pytest.approx(72.0, abs=6.0)


def test_kad_properties():
    """KAD (unbiased MMD²) is ~0 on identical sets and grows with distribution shift."""
    rng = np.random.default_rng(1)
    A = rng.standard_normal((200, 6))
    B = rng.standard_normal((200, 6))
    C = rng.standard_normal((200, 6)) + 3.0
    assert kernel_audio_distance(A, A) == pytest.approx(0.0, abs=0.02)
    assert kernel_audio_distance(A, C) > kernel_audio_distance(A, B)


def test_generation_fidelity_stamped(fake_embedder):
    """generation_fidelity embeds through the injected embedder and stamps provenance (fad + kad)."""
    rng = np.random.default_rng(2)
    wavs = [rng.standard_normal(2048).astype(np.float32) for _ in range(6)]
    res = generation_fidelity(wavs, wavs, embedder=fake_embedder, metric="fad")
    assert isinstance(res, FidelityResult)
    assert res.metric == "fad" and res.value == pytest.approx(0.0, abs=1e-6)  # same set → 0
    assert res.stamp.embedding == fake_embedder.model_id
    assert res.stamp.toolkit == "foley-numpy" and res.stamp.n_ref == 6 and res.stamp.n_gen == 6
    # the KAD dispatch path (numpy KAD is shipped, not deferred) — the metric math itself
    # is validated at scale in test_kad_properties; here we only cover the dispatch (the
    # unbiased MMD² is biased away from 0 at this tiny m, so we don't assert a value).
    kad = generation_fidelity(wavs, wavs, embedder=fake_embedder, metric="kad")
    assert kad.metric == "kad" and np.isfinite(kad.value) and kad.stamp.n_ref == 6
    with pytest.raises(ValueError):
        generation_fidelity(wavs, wavs, embedder=fake_embedder, metric="bogus")


def test_fidelity_requires_two_samples():
    """FAD and KAD both raise a clear ValueError on a single-sample set (no opaque crash)."""
    one, many = np.zeros((1, 4)), np.zeros((3, 4))
    for fn in (frechet_distance, kernel_audio_distance):
        with pytest.raises(ValueError):
            fn(one, many)
        with pytest.raises(ValueError):
            fn(many, one)


# ---------------------------------------------------------------------------
# fit metric — the pure correctness oracle
# ---------------------------------------------------------------------------


def test_fit_precision_oracle():
    """fit_precision / recall / f1 are exact closed-form — FP≠FN so the three are distinct."""
    matches = [True, True, False, True, False, True]
    relevants = [True, False, False, True, True, False]  # TP=2, FP=2, FN=1
    assert fit_precision(matches, relevants) == pytest.approx(2 / 4)  # 0.5
    assert fit_recall(matches, relevants) == pytest.approx(2 / 3)  # ≠ precision
    assert fit_f1(matches, relevants) == pytest.approx(2 * 0.5 * (2 / 3) / (0.5 + 2 / 3))  # 4/7
    assert fit_precision([], []) == 0.0 and fit_recall([], []) == 0.0  # nothing accepted


# ---------------------------------------------------------------------------
# fit harness — shape, determinism, gate, stratification
# ---------------------------------------------------------------------------


def test_run_fit_eval_shape_and_strata():
    """A run yields a JSON-friendly FitReport with a per-family×diegetic breakdown."""
    import dataclasses
    import json

    r = run_fit_eval(fit_judge=StringOverlapJudge(), level="listen", k=5)
    assert isinstance(r, FitReport)
    assert r.n_accepted > 0 and r.judge_model == "StringOverlapJudge"
    assert 0.0 <= r.fit_precision <= 1.0 and 0.0 <= r.auto_accept_rate <= 1.0
    assert r.strata and all("|" in key for key in r.strata)  # 'FAMILY|diegetic' keys
    json.dumps(dataclasses.asdict(r))  # JSON-serializable


def test_run_fit_eval_reproducible():
    """Same seed + fake judge → identical fit numbers (determinism)."""
    a = run_fit_eval(fit_judge=StringOverlapJudge(), level="listen", seed=0, k=5)
    b = run_fit_eval(fit_judge=StringOverlapJudge(), level="listen", seed=0, k=5)
    assert (a.fit_precision, a.n_accepted, a.fit_score) == (b.fit_precision, b.n_accepted, b.fit_score)


def test_fit_report_gate_is_the_sole_gate():
    """gate() is the ONLY gate: run_fit_eval/evaluate_fit take no floor; gate(None) is a no-op."""
    r = run_fit_eval(fit_judge=StringOverlapJudge(), level="listen", k=5)
    assert r.gate(None) is True and r.gate(0.0) is True
    assert r.gate(1.1) is False  # an impossible floor fails
    # the dead floor param is gone from both entry points (gating stays the caller's job)
    with pytest.raises(TypeError):
        run_fit_eval(fit_judge=StringOverlapJudge(), min_fit_precision=0.9)
    with pytest.raises(TypeError):
        foley.evaluate_fit(min_fit_precision=0.9)


def test_run_fit_eval_rejects_clap_rung():
    """'clap' is rejected — it never invokes the fit-judge, so it cannot measure fit."""
    with pytest.raises(ValueError, match="clap"):
        run_fit_eval(fit_judge=StringOverlapJudge(), level="clap")


def test_stratified_sample_deterministic():
    """The stratified draw is seeded-deterministic, capped, and round-robins across strata."""
    units = [(f"i{s}", 0, {"query": "q", "ucs_catid": f"{fam}Gnrl", "diegetic": True})
             for fam in ("DOOR", "RAIN", "WIND") for s in range(4)]
    strata_keys = ("family", "diegetic")
    d1 = stratified_sample(units, strata_keys=strata_keys, sample=6, seed=0)
    d2 = stratified_sample(units, strata_keys=strata_keys, sample=6, seed=0)
    assert d1 == d2 and len(d1) == 6
    # round-robin ⇒ each of the 3 families appears twice in a 6-of-12 draw
    fams = [u[2]["ucs_catid"][:4] for u in d1]
    assert all(fams.count(f) == 2 for f in ("DOOR", "RAIN", "WIND"))
    assert stratified_sample(units, strata_keys=strata_keys, sample=None, seed=0) == units  # None = all


# ---------------------------------------------------------------------------
# the no-ranking-side-effect guards (Tier-2 never perturbs the nDCG@10 gate)
# ---------------------------------------------------------------------------


def test_fit_never_binds_ranking_symbols():
    """Static guard: foley.eval.fit's namespace never binds a nDCG-run constructor OR runner."""
    import foley.eval.fit as fitmod

    ns = set(vars(fitmod))
    assert not ({"build_run", "evaluate_run", "to_qrels", "run_ring0_retrieval_eval"} & ns)


def test_fit_eval_does_not_touch_retrieval_ranking(monkeypatch):
    """Runtime guard: the run-constructors are never resolved, and nDCG is byte-identical."""
    # Spy where the symbols are actually RESOLVED (golden.py's from-imports), not the
    # module they're defined in — a real regression would call them via golden's bindings.
    from foley.eval import golden

    calls = {"n": 0}

    def _spy_build(*a, **k):
        calls["n"] += 1
        raise AssertionError("fit eval must not construct a retrieval run")

    before = foley.evaluate(k=10).mean["ndcg@10"]
    monkeypatch.setattr(golden, "build_run", _spy_build)
    monkeypatch.setattr(golden, "evaluate_run", _spy_build)
    run_fit_eval(fit_judge=StringOverlapJudge(), level="listen", k=10)
    assert calls["n"] == 0  # never resolved
    monkeypatch.undo()
    after = foley.evaluate(k=10).mean["ndcg@10"]
    assert before == after


# ---------------------------------------------------------------------------
# import purity
# ---------------------------------------------------------------------------


def test_eval_import_purity():
    """`import foley` + `import foley.eval` pull no LLM/ML/scipy dependency (dol-only)."""
    code = (
        "import sys, foley, foley.eval, foley.agent;"
        "heavy={'anthropic','torch','transformers','lancedb','opentelemetry','scipy'};"
        "bad=heavy & set(sys.modules);"
        "assert not bad, bad"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
