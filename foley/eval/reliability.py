"""Inter-rater reliability — Krippendorff's α + the judge-vs-human calibration guardrail.

Whatever judges foley's fit — humans or an LLM/audio-LM — you must **quantify agreement
before trusting the scores** (report 08 §2.3). This module is the numbers side of that
guardrail: one pure-numpy Krippendorff's α (the most general reliability coefficient —
any number of raters, ordinal/graded labels, missing-data tolerant), reused for BOTH
human inter-rater reliability on the gold grades AND judge-vs-human calibration (the
model judge is just one more rater row). A model judge is only promoted to unattended
use once it reaches human-level agreement on a calibration slice.

Pure numpy / stdlib, deterministic — ``numpy`` is imported function-locally so importing
this module keeps ``import foley`` dol-only (the same discipline as
:mod:`foley.eval.retrieval`). No ``scipy``, no external reliability toolkit (a PyPI
``krippendorff`` oracle cross-check lives behind an opt-in test only).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Krippendorff's benchmark bands for a reliability coefficient (report 08 §2.3).
ALPHA_RELIABLE: float = 0.8
ALPHA_TENTATIVE: float = 0.667


def reliability_band(alpha: float) -> str:
    """Map an α (or κ) to Krippendorff's benchmark band.

    Args:
        alpha: A reliability coefficient in ``(-∞, 1]``.

    Returns:
        ``'reliable'`` (α ≥ 0.8), ``'tentative'`` (0.667 ≤ α < 0.8), else
        ``'revise-rubric'``.
    """
    if alpha >= ALPHA_RELIABLE:
        return "reliable"
    if alpha >= ALPHA_TENTATIVE:
        return "tentative"
    return "revise-rubric"


def _coincidence_matrix(reliability_data, *, value_domain=None):
    """Build the coincidence matrix ``o`` + the sorted value list (report 08 §2.3).

    ``o[c, k]`` sums, over every unit with ≥ 2 present ratings, the count of ordered
    value-pairs ``(c, k)`` from *distinct* raters, each weighted by ``1/(m_u − 1)`` so
    every unit contributes equally regardless of how many raters rated it. Units with
    fewer than 2 ratings are dropped (no imputation).

    Args:
        reliability_data: A 2-D array-like ``(raters × units)``; ``nan`` = missing.
        value_domain: Optional explicit sorted value set (else the observed values).

    Returns:
        ``(o, values)`` — the ``V×V`` coincidence matrix and the sorted value vector.
    """
    import numpy as np

    data = np.asarray(reliability_data, dtype=float)
    if value_domain is None:
        values = np.unique(data[~np.isnan(data)])
    else:
        values = np.asarray(sorted(value_domain), dtype=float)
    index = {float(v): i for i, v in enumerate(values)}
    V = len(values)
    o = np.zeros((V, V), dtype=float)
    for u in range(data.shape[1]):
        present = data[:, u]
        present = present[~np.isnan(present)]
        m_u = len(present)
        if m_u < 2:
            continue
        w = 1.0 / (m_u - 1)
        for a in present:
            ia = index[float(a)]
            for b in present:
                ib = index[float(b)]
                o[ia, ib] += w
        # subtract the self-pairings (a value paired with itself, same rating): the loop
        # above counted m_u ordered self-pairs per unit; only the m_u·(m_u−1) distinct-rater
        # pairs are coincidences, so remove the diagonal over-count.
        for a in present:
            ia = index[float(a)]
            o[ia, ia] -= w
    return o, values


def _delta_squared(values, marginals, *, level: str):
    """The difference-metric matrix ``δ²[c, k]`` for the chosen measurement level.

    Ordinal (the default for foley's 0–3 grades) uses the cumulative-marginal form so
    the distance between adjacent grades depends on how the ratings are distributed;
    nominal is 0/1; interval is the squared numeric difference.
    """
    import numpy as np

    vals = np.asarray(values, dtype=float)
    n = np.asarray(marginals, dtype=float)
    V = len(vals)
    if level == "nominal":
        return 1.0 - np.eye(V)
    if level == "interval":
        diff = vals[:, None] - vals[None, :]
        return diff**2
    if level != "ordinal":
        raise ValueError(f"unknown level {level!r} (nominal|ordinal|interval)")
    d = np.zeros((V, V), dtype=float)
    for c in range(V):
        for k in range(V):
            lo, hi = (c, k) if c <= k else (k, c)
            s = n[lo : hi + 1].sum() - (n[c] + n[k]) / 2.0
            d[c, k] = s**2
    return d


def krippendorff_alpha(
    reliability_data, *, level: str = "ordinal", value_domain=None
) -> float:
    """Krippendorff's α over ``(raters × units)`` ratings (``nan`` = missing).

    ``α = 1 − D_o/D_e`` — 1 is perfect agreement, ~0 is chance, negative is systematic
    disagreement. Ordinal is the default (foley's 0–3 grades); missing ratings are
    tolerated (units with < 2 ratings are dropped, no imputation). Pure numpy.

    Args:
        reliability_data: A 2-D array-like ``(raters × units)``; ``nan`` = missing.
        level: ``'ordinal'`` (default) | ``'nominal'`` | ``'interval'``.
        value_domain: Optional explicit value set (for a label unobserved by some rater).

    Returns:
        α as a bare ``float`` (``1.0`` when there is no expected disagreement, ``D_e = 0``).
    """
    o, values = _coincidence_matrix(reliability_data, value_domain=value_domain)
    n_c = o.sum(axis=1)
    n = o.sum()
    if n < 2 or len(values) < 2:
        return 1.0
    d = _delta_squared(values, n_c, level=level)
    d_o = (o * d).sum() / n
    import numpy as np

    d_e = (np.outer(n_c, n_c) * d).sum() / (n * (n - 1.0))
    if d_e == 0:
        return 1.0
    return float(1.0 - d_o / d_e)


def percent_agreement(reliability_data) -> float:
    """Raw pairwise percent agreement, reported ALONGSIDE α (report 08 §2.3).

    On foley's skewed 'most candidates irrelevant' label distribution a chance-corrected
    α can look pessimistic, so the uncorrected agreement is co-reported for context.

    Args:
        reliability_data: A 2-D array-like ``(raters × units)``; ``nan`` = missing.

    Returns:
        The fraction of same-unit rater pairs that agree (``0.0`` if no pairs).
    """
    import numpy as np

    data = np.asarray(reliability_data, dtype=float)
    agree = 0.0
    total = 0.0
    for u in range(data.shape[1]):
        present = data[:, u]
        present = present[~np.isnan(present)]
        m = len(present)
        if m < 2:
            continue
        for i in range(m):
            for j in range(m):
                if i != j:
                    total += 1.0
                    if present[i] == present[j]:
                        agree += 1.0
    return agree / total if total else 0.0


@dataclass
class AlphaResult:
    """A judge-vs-human calibration record (surfaced as ``FitReport.calibration``).

    Codifies the promotion rule in one legible object: a model judge is ``promoted`` to
    unattended use only once its agreement with the human raters reaches the
    :data:`ALPHA_RELIABLE` band.
    """

    alpha: float
    level: str
    n_units: int
    n_raters: int
    percent_agreement: float
    band: str
    promoted: bool


def calibrate_judge_vs_human(
    human_grades, judge_grades, *, level: str = "ordinal"
) -> AlphaResult:
    """Compute judge-vs-human agreement and the promotion verdict (report 08 §2.3).

    Stacks the human rating row(s) and the model-judge row into one reliability matrix
    and returns an :class:`AlphaResult`; ``promoted`` is ``True`` iff α reaches the
    reliable band — the model judge may then be trusted unattended on that slice.

    Args:
        human_grades: A 1-D per-unit human grade sequence, or a 2-D ``(humans × units)``
            matrix (``nan`` = missing).
        judge_grades: The model judge's 1-D per-unit grades (``nan`` = missing).
        level: The measurement level (default ``'ordinal'``).

    Returns:
        An :class:`AlphaResult`.
    """
    import numpy as np

    human = np.asarray(human_grades, dtype=float)
    if human.ndim == 1:
        human = human[None, :]
    judge = np.asarray(judge_grades, dtype=float)[None, :]
    return alpha_result(np.vstack([human, judge]), level=level)


def alpha_result(reliability_data, *, level: str = "ordinal") -> AlphaResult:
    """An :class:`AlphaResult` for any ``(raters × units)`` matrix (``nan`` = missing).

    The one place α, its band and the promotion rule are put together: used for the
    judge-vs-human matrix here and for human-only agreement in :mod:`foley.eval.panel`.
    """
    import numpy as np

    data = np.asarray(reliability_data, dtype=float)
    alpha = krippendorff_alpha(data, level=level)
    n_rated = int(np.sum(np.sum(~np.isnan(data), axis=0) >= 2))
    return AlphaResult(
        alpha=alpha,
        level=level,
        n_units=n_rated,
        n_raters=data.shape[0],
        percent_agreement=percent_agreement(data),
        band=reliability_band(alpha),
        promoted=alpha >= ALPHA_RELIABLE,
    )
