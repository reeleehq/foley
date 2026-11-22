"""Tier-2 fit evaluation — "does the accepted clip actually match the intent?" (report 08 §2/§5).

The judge-based sibling of :mod:`foley.eval.retrieval`. Where Tier-1 asks *did we rank the
right sound?* (a per-PR nDCG gate), Tier-2 asks *does the clip the pipeline accepted
genuinely depict the event?* — audited over a **seeded stratified sample** of the golden
set by the authoritative fit-judge (report 08 §2). It is **nightly / pre-release and
cost-gated, never a silent per-PR gate**: :meth:`FitReport.gate` is a no-op unless the
caller passes an explicit ``min_fit_precision`` floor, and ``foley eval-fit`` is
deliberately off the CI command path.

Discipline: it **reuses** the Tier-1 golden builders (``load_golden`` /
``build_eval_library``) and the #7 SELECT tools (``search_sounds`` / ``gate_candidates``
/ ``verify_match``), but it **never** imports ``build_run`` / ``evaluate_run`` /
``to_qrels`` — the three symbols that construct or score the retrieval run — so it
structurally cannot compute or perturb the nDCG@10 gate. Metrics are pure numpy/stdlib;
the fit-judge is injected (a deterministic fake in CI, an audio-LM / LLM behind
``foley[fit]`` / ``foley[agent]`` in prod). Fit judging runs strictly AFTER the
fail-closed license gate (``verify_match`` asserts ``candidate.license_ok`` is ``True``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..base import VerifyLevel
from .embedder import HashingBowEmbedder
from .golden import DEFAULT_GOLDEN_PATH, load_golden
from .retrieval import mean_over_queries


# ---------------------------------------------------------------------------
# the pure fit metric (the correctness oracle)
# ---------------------------------------------------------------------------


def _confusion(
    matches: "Sequence[bool]", relevants: "Sequence[bool]"
) -> "tuple[int, int, int]":
    tp = sum(1 for m, r in zip(matches, relevants) if m and r)
    fp = sum(1 for m, r in zip(matches, relevants) if m and not r)
    fn = sum(1 for m, r in zip(matches, relevants) if (not m) and r)
    return tp, fp, fn


def fit_precision(matches: "Sequence[bool]", relevants: "Sequence[bool]") -> float:
    """Fraction of judge-accepted candidates that are actually gold-relevant.

    ``TP / (TP + FP)`` where a candidate is a positive iff the fit-judge said ``match``
    and gold-relevant iff its golden grade ≥ 1. This measures the JUDGE's auto-accept
    *purity* (a low value ⇒ the judge waves through wrong clips) — NOT the ranker. Pure,
    closed-form, and the decisive correctness oracle (the Ring-0 + fake-judge plumbing
    makes the end-to-end value tautological, so the metric math is tested in isolation).

    Args:
        matches: Per-candidate fit-judge ``match`` booleans.
        relevants: Per-candidate gold-relevance booleans (grade ≥ 1).

    Returns:
        The fit precision in ``[0, 1]`` (``0.0`` when nothing was accepted).
    """
    tp, fp, _ = _confusion(matches, relevants)
    return tp / (tp + fp) if (tp + fp) else 0.0


def fit_recall(matches: "Sequence[bool]", relevants: "Sequence[bool]") -> float:
    """``TP / (TP + FN)`` — of the gold-relevant candidates, how many the judge confirmed."""
    tp, _, fn = _confusion(matches, relevants)
    return tp / (tp + fn) if (tp + fn) else 0.0


def fit_f1(matches: "Sequence[bool]", relevants: "Sequence[bool]") -> float:
    """The harmonic mean of :func:`fit_precision` and :func:`fit_recall`."""
    p, r = fit_precision(matches, relevants), fit_recall(matches, relevants)
    return 2 * p * r / (p + r) if (p + r) else 0.0


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


@dataclass
class FitReport:
    """Tier-2 fit metrics over a stratified golden sample (JSON-friendly, mirrors ``RetrievalReport``).

    The fit numbers are co-emitted with the judge-vs-human ``calibration`` (an
    :class:`~foley.eval.reliability.AlphaResult` dict) so the §5 human-calibration
    guardrail is legible: a ``fit_precision`` is only trusted where α certifies the judge.
    ``fidelity`` holds stamped FAD/KAD results for release-level backend comparison. Both
    default empty on the pure-fake path (no human labels, no generated-set wavs).
    """

    per_item: dict = field(
        default_factory=dict
    )  # {query_id: {fit_precision, fit_score, ...}}
    fit_precision: float = 0.0
    fit_recall: float = 0.0
    fit_f1: float = 0.0
    fit_score: float = 0.0  # mean Verdict.confidence over audited candidates
    auto_accept_rate: float = 0.0  # confirmed / accepted
    n_accepted: int = 0
    n_confirmed: int = 0
    strata: dict = field(
        default_factory=dict
    )  # {stratum: {fit_precision, fit_score, n}}
    calibration: Optional[dict] = (
        None  # AlphaResult dict (judge-vs-human); None on the fake path
    )
    fidelity: dict = field(default_factory=dict)  # {label: FidelityResult-ish dict}
    judge_model: str = ""
    embedder_model_id: str = ""
    seed: int = 0
    k: int = 10
    schema_version: int = 1

    def gate(self, min_fit_precision: Optional[float]) -> bool:
        """The Tier-2 gate — a NO-OP returning ``True`` unless a floor is supplied.

        Structural guarantee that Tier-2 is never a silent per-PR gate: CI passes no
        floor, so this is always ``True``; only the nightly/pre-release runner sets one.
        """
        if min_fit_precision is None:
            return True
        return self.fit_precision >= min_fit_precision

    def format_regression_diff(self, baseline: dict) -> str:
        """A human diff of ``fit_precision`` vs a committed baseline (trend reporting).

        The committed fit-baseline stamp is deferred until real judges produce stable
        numbers; this ships the trend path only.
        """
        base = baseline.get("value", 0.0)
        floor = base - baseline.get("tolerance", 0.02)
        lines = [
            f"fit_precision: current={self.fit_precision:.4f} baseline={base:.4f} "
            f"floor={floor:.4f} Δ={self.fit_precision - base:+.4f}",
            "per-stratum fit_precision:",
        ]
        for stratum, s in sorted(self.strata.items()):
            lines.append(
                f"  {stratum}: {s.get('fit_precision', 0.0):.4f} (n={s.get('n', 0)})"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# stratification (the cost gate) + the SELECT-pipeline audit
# ---------------------------------------------------------------------------


def _event_from_golden(ev_dict: dict):
    """Build a :class:`~foley.base.SoundEvent` from a golden ``expected_events`` entry."""
    from ..base import Layer, Salience, SoundEvent

    return SoundEvent(
        query=ev_dict["query"],
        layer=Layer(ev_dict.get("layer", "sfx_fg")),
        diegetic=ev_dict.get("diegetic", True),
        salience=Salience(ev_dict.get("salience", "medium")),
        onset=ev_dict.get("onset_hint"),
        ucs_catid=ev_dict.get("ucs_catid"),
        audioset=list(ev_dict.get("audioset", [])),
    )


def _family(catid: "Optional[str]") -> str:
    """The UCS category of ``catid`` (variable-length CatID prefixes: ``AIRBlow`` is AIR,
    ``RAIN`` is RAIN); the CatID itself when the default table does not list it."""
    if not catid:
        return ""
    from ..index.taxonomy import default_ucs_table

    row = default_ucs_table().get(catid)
    return row.category if row is not None else catid


def _strata_key(event, strata_keys) -> tuple:
    """Derive the stratum tuple from a :class:`SoundEvent` (family × diegetic by default).

    ``family`` is the UCS category of ``ucs_catid`` read from the table (``DOORWood`` →
    ``DOORS``, ``RAIN`` → ``RAIN``), falling back to the CatID's own
    letters when the table does not know it (a custom code), then to the mix layer; ``diegetic`` splits story-world vs
    audience-only cues. No new golden package-data is shipped — strata come from the
    existing ``seed.json``.
    """
    parts = []
    for key in strata_keys:
        if key == "family":
            fam = _family(event.ucs_catid) or event.layer.value
            parts.append(fam)
        elif key == "diegetic":
            parts.append("diegetic" if event.diegetic else "non-diegetic")
        else:
            parts.append(str(getattr(event, key, "")))
    return tuple(parts)


def stratified_sample(
    units: list, *, strata_keys, sample: Optional[int], seed: int
) -> list:
    """Deterministic seeded stratified draw over ``units`` — the cost gate.

    Round-robins across strata (so an easy family cannot dominate a capped sample);
    ``sample=None`` keeps the full set. Each unit is ``(GoldenItem, event_index,
    event_dict)``.

    Args:
        units: The full ``(item, ev_idx, ev_dict)`` unit list.
        strata_keys: The stratification axes (e.g. ``('family', 'diegetic')``).
        sample: The total draw size, or ``None`` for all.
        seed: The RNG seed (reproducibility).
    """
    if sample is None or sample >= len(units):
        return list(units)
    import random
    from collections import OrderedDict

    buckets: "OrderedDict[tuple, list]" = OrderedDict()
    for u in units:
        key = _strata_key(_event_from_golden(u[2]), strata_keys)
        buckets.setdefault(key, []).append(u)
    rng = random.Random(seed)
    for b in buckets.values():
        rng.shuffle(b)
    out: list = []
    idx = {kk: 0 for kk in buckets}
    while len(out) < sample:
        progressed = False
        for kk, b in buckets.items():
            if idx[kk] < len(b):
                out.append(b[idx[kk]])
                idx[kk] += 1
                progressed = True
                if len(out) >= sample:
                    break
        if not progressed:
            break
    return out


def _accepted_candidates(units, *, embedder, level, judge, k):
    """Run the real SELECT pipeline over ``units`` and audit each license-clean candidate.

    For each golden event: ``search_sounds → gate_candidates`` (the fail-closed license
    gate) → ``verify_match`` with the authoritative fit-judge. Reuses the #7 SELECT tools
    and the Tier-1 Ring-0 library; NEVER computes a retrieval run. Returns per-candidate
    audit records ``{query_id, event, candidate_id, match, relevant, confidence}``.
    """
    from ..agent import gate_candidates, search_sounds, verify_match
    from ..licensing import intended_use_for
    from .golden import build_eval_library

    lib = build_eval_library(embedder=embedder)
    use = intended_use_for()
    records = []
    for item, ev_idx, ev_dict in units:
        event = _event_from_golden(ev_dict)
        # Grade against THIS event's own answer clips (keyed by its ucs_catid), not the
        # whole item's grade map — so a multi-event item never credits a candidate for
        # matching a sibling event. Byte-identical for single-event items.
        catid = ev_dict.get("ucs_catid")
        grades = {
            cid: int(item.grade.get(cid, 0))
            for cid in item.answer_clip_ids.get(catid, [])
        }
        candidates = search_sounds(event.query, k=k, library=lib)
        kept = gate_candidates(candidates, use)
        for c in kept:
            verdict = verify_match(event, c, level=level, judge=judge)
            c.verdict = verdict
            records.append(
                {
                    "query_id": f"{item.id}::{ev_idx}",
                    "event": event,
                    "candidate_id": c.sound.id,
                    "match": bool(verdict.match),
                    "relevant": grades.get(c.sound.id, 0) >= 1,
                    "confidence": float(verdict.confidence),
                }
            )
    return records


def run_fit_eval(
    *,
    golden=None,
    golden_path=DEFAULT_GOLDEN_PATH,
    sample: Optional[int] = None,
    strata_keys=("family", "diegetic"),
    fit_judge=None,
    embedder=None,
    level: "str | VerifyLevel" = VerifyLevel.judge,
    seed: int = 0,
    k: int = 10,
    llm: Optional[str] = None,
) -> FitReport:
    """Run the Tier-2 fit eval over a stratified golden sample → a :class:`FitReport`.

    Composes the Tier-1 golden builders + the #7 SELECT loop, applies the authoritative
    fit-judge as an independent audit, and aggregates fit-precision/recall/F1 + fit-score
    + auto-accept-rate, with a per-stratum breakdown. Report-only unless
    ``min_fit_precision`` is supplied.

    Args:
        golden: A pre-loaded golden list (default: load ``golden_path``).
        golden_path: The golden JSON (default: the bundled Ring-0 seed set).
        sample: The stratified sample cap (default: the whole set — the cost gate).
        strata_keys: The stratification axes (default ``('family', 'diegetic')``).
        fit_judge: The injected authoritative :class:`~foley.agent.protocols.Judge`
            (default: :func:`foley.agent.verify._default_fit_judge` for ``llm`` — the
            hermetic fake unless ``llm`` / ``$FOLEY_LLM`` opts in).
        embedder: The Ring-0 text/​audio embedder (default: :class:`HashingBowEmbedder`).
        level: The verify rung the fit-judge audits at — ``'listen'`` or ``'judge'``
            (default ``VerifyLevel.judge``). ``'clap'`` is rejected: it never invokes the
            fit-judge (it only re-runs the retrieval clap gate), so it cannot measure fit.
        seed: The sampling RNG seed.
        k: The retrieval shortlist depth per event.

    Returns:
        A :class:`FitReport`. Gating is the caller's job via :meth:`FitReport.gate`.

    Raises:
        ValueError: If ``level`` is ``'clap'`` (fit judging requires a listen/judge rung).
    """
    from ..agent.verify import _default_fit_judge

    level = VerifyLevel(level)
    if level == VerifyLevel.clap:
        raise ValueError(
            "fit eval requires a 'listen' or 'judge' rung, not 'clap' "
            "(the clap rung never invokes the fit-judge)"
        )
    golden = golden if golden is not None else load_golden(golden_path)
    embedder = embedder if embedder is not None else HashingBowEmbedder()
    fit_judge = fit_judge if fit_judge is not None else _default_fit_judge(level, llm)

    units = [
        (item, i, ev) for item in golden for i, ev in enumerate(item.expected_events)
    ]
    units = stratified_sample(units, strata_keys=strata_keys, sample=sample, seed=seed)
    records = _accepted_candidates(
        units, embedder=embedder, level=level, judge=fit_judge, k=k
    )

    matches = [r["match"] for r in records]
    relevants = [r["relevant"] for r in records]
    confidences = [r["confidence"] for r in records]
    n_confirmed = sum(matches)

    per_item: dict = {}
    for qid in {r["query_id"] for r in records}:
        rows = [r for r in records if r["query_id"] == qid]
        per_item[qid] = {
            "fit_precision": fit_precision(
                [r["match"] for r in rows], [r["relevant"] for r in rows]
            ),
            "fit_score": mean_over_queries([r["confidence"] for r in rows]),
            "n": len(rows),
        }

    strata: dict = {}
    for stratum in {_strata_key(r["event"], strata_keys) for r in records}:
        rows = [r for r in records if _strata_key(r["event"], strata_keys) == stratum]
        strata["|".join(stratum)] = {
            "fit_precision": fit_precision(
                [r["match"] for r in rows], [r["relevant"] for r in rows]
            ),
            "fit_score": mean_over_queries([r["confidence"] for r in rows]),
            "auto_accept_rate": mean_over_queries(
                [1.0 if r["match"] else 0.0 for r in rows]
            ),
            "n": len(rows),
        }

    return FitReport(
        per_item=per_item,
        fit_precision=fit_precision(matches, relevants),
        fit_recall=fit_recall(matches, relevants),
        fit_f1=fit_f1(matches, relevants),
        fit_score=mean_over_queries(confidences),
        auto_accept_rate=(n_confirmed / len(records) if records else 0.0),
        n_accepted=len(records),
        n_confirmed=int(n_confirmed),
        strata=strata,
        judge_model=type(fit_judge).__name__,
        embedder_model_id=getattr(embedder, "model_id", ""),
        seed=seed,
        k=k,
    )
