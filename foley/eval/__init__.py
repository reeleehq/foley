"""Tier-1 retrieval evaluation — metrics, a frozen golden set, and the nDCG gate.

This subpackage answers "did we retrieve the right sound?" with TREC-style
ranking metrics (``nDCG@10`` / ``Recall@k`` / ``mAP@10`` / ``MRR@10``) over a
frozen golden set, and ships the **PR gate**: a pytest check that blocks a change
whose ``nDCG@10`` regresses by more than ``0.02`` on the Ring-0 golden set. Every
part is pure numpy/stdlib and deterministic — no ``ranx``/``numba``, no CLAP, no
downloads — so the gate runs on every index/embedder/prompt PR in foley's CI.

Tier-2 fit-judging (#10b) — "does this clip match the intent?" — lives alongside
in :mod:`~foley.eval.fit` (the judge-based fit harness), :mod:`~foley.eval.reliability`
(Krippendorff's α + judge-vs-human calibration), and :mod:`~foley.eval.fidelity`
(set-level FAD/KAD generation fidelity). Tier-2 is nightly/pre-release + cost-gated —
NOT a per-PR gate — and never touches the retrieval ranking. All numpy imports are
function-local so ``import foley`` stays dol-only.
"""

from __future__ import annotations

from .baseline import (
    DEFAULT_FIT_BASELINE_PATH,
    check_fit_baseline,
    write_fit_baseline,
    DEFAULT_TOLERANCE,
    is_stale,
    load_baseline,
    write_baseline,
)
from . import bradley_terry, panel
from .panel_page import render_panel_html
from .fidelity import (
    FidelityResult,
    FidelityStamp,
    frechet_distance,
    generation_fidelity,
    kernel_audio_distance,
)
from .fit import (
    FitReport,
    fit_f1,
    fit_precision,
    fit_recall,
    run_fit_eval,
    stratified_sample,
)
from .reliability import (
    ALPHA_RELIABLE,
    ALPHA_TENTATIVE,
    AlphaResult,
    calibrate_judge_vs_human,
    krippendorff_alpha,
    percent_agreement,
    reliability_band,
)
from .embedder import HashingBowEmbedder
from .golden import (
    GoldenItem,
    build_eval_library,
    load_golden,
    run_ring0_retrieval_eval,
    to_qrels,
)
from .retrieval import (
    RetrievalReport,
    average_precision_at_k,
    build_run,
    evaluate_run,
    mean_over_queries,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    # metrics
    "ndcg_at_k",
    "recall_at_k",
    "precision_at_k",
    "average_precision_at_k",
    "mrr_at_k",
    "mean_over_queries",
    "build_run",
    "evaluate_run",
    "RetrievalReport",
    # golden set + harness
    "GoldenItem",
    "load_golden",
    "to_qrels",
    "build_eval_library",
    "run_ring0_retrieval_eval",
    # embedder + baseline
    "HashingBowEmbedder",
    "load_baseline",
    "write_baseline",
    "is_stale",
    "DEFAULT_TOLERANCE",
    "DEFAULT_FIT_BASELINE_PATH",
    "write_fit_baseline",
    "check_fit_baseline",
    # --- Tier-2 (#10b): fit harness ---
    "FitReport",
    "run_fit_eval",
    "fit_precision",
    "fit_recall",
    "fit_f1",
    "stratified_sample",
    # --- Tier-2 (#10b): inter-rater reliability ---
    "krippendorff_alpha",
    "percent_agreement",
    "reliability_band",
    "calibrate_judge_vs_human",
    "AlphaResult",
    "ALPHA_RELIABLE",
    "ALPHA_TENTATIVE",
    # --- Tier-2 (#49): the human panel behind the calibration ---
    "bradley_terry",
    "panel",
    "render_panel_html",
    # --- Tier-2 (#10b): generation fidelity ---
    "frechet_distance",
    "kernel_audio_distance",
    "generation_fidelity",
    "FidelityStamp",
    "FidelityResult",
]
