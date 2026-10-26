"""Bradley-Terry ranking from pairwise preferences (2AFC human panels; #49).

A 2AFC panel ("which of these two clips fits the prompt better?") gives win counts between
pairs of systems (a backend, a judge, a prompt style). Bradley-Terry turns them into one
strength per item: ``P(i beats j) = s_i / (s_i + s_j)``. Strengths are reported on the log
scale, centred on 0, so a difference of ``d`` means odds ``e**d`` that the higher one wins.

With comparisons that fall into disconnected groups the strengths of different groups are not
comparable (``connected`` is ``False``), whatever the prior. Bootstrap intervals resample single
judgements, ignoring that one rater's judgements are correlated; treat them as optimistic.

Fitted by the MM (minorise-maximise) iteration of Hunter (2004). A small ``prior`` of virtual
games (one half-win each way against every other item) keeps the estimate finite when an item
never wins or never loses, which a small panel often produces; set ``prior=0`` for the plain
maximum-likelihood fit (it can diverge on such data). Pure numpy, deterministic; bootstrap
intervals take an explicit ``seed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

#: Virtual half-wins each way between every pair of items (the Bayesian regulariser).
DEFAULT_PRIOR = 0.5
DEFAULT_MAX_ITER = 1000
DEFAULT_TOL = 1e-10
DEFAULT_BOOTSTRAP = 1000
DEFAULT_CI = 0.95


@dataclass(frozen=True)
class BradleyTerry:
    """Fitted strengths: ``items[i]`` has log-strength ``scores[i]`` (mean 0)."""

    items: "tuple[str, ...]"
    scores: "tuple[float, ...]"
    n_comparisons: int
    converged: bool
    connected: bool  # False: the comparison graph has islands, so scores across them are not comparable
    ci: "Optional[tuple[tuple[float, float], ...]]" = None  # per item, if bootstrapped

    def ranking(self) -> "list[str]":
        """Items from strongest to weakest."""
        order = sorted(range(len(self.items)), key=lambda i: -self.scores[i])
        return [self.items[i] for i in order]

    def p_win(self, a: str, b: str) -> float:
        """The fitted probability that ``a`` beats ``b``."""
        import math

        d = self.scores[self.items.index(a)] - self.scores[self.items.index(b)]
        return 1.0 / (1.0 + math.exp(-d))


def win_matrix(
    comparisons: "Sequence[tuple[str, str]]",
) -> "tuple[tuple[str, ...], list[list[float]]]":
    """``(items, wins)`` from ``(winner, loser)`` pairs; ``wins[i][j]`` = times i beat j."""
    items = tuple(sorted({x for pair in comparisons for x in pair}))
    index = {name: i for i, name in enumerate(items)}
    wins = [[0.0] * len(items) for _ in items]
    for winner, loser in comparisons:
        if winner == loser:
            raise ValueError(
                f"a comparison needs two different items, got {winner!r} twice"
            )
        wins[index[winner]][index[loser]] += 1.0
    return items, wins


def fit(
    comparisons: "Sequence[tuple[str, str]]",
    *,
    prior: float = DEFAULT_PRIOR,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
    bootstrap: int = 0,
    ci: float = DEFAULT_CI,
    seed: int = 0,
) -> BradleyTerry:
    """Fit Bradley-Terry strengths to ``(winner, loser)`` comparisons.

    Args:
        comparisons: One ``(winner, loser)`` pair per judgement (ties are left out).
        prior: Virtual half-wins each way between every pair (see the module docstring).
        max_iter: MM iteration cap.
        tol: Stop when the largest log-strength change is under this.
        bootstrap: If positive, resample the judgements this many times (seeded) and add
            percentile intervals at level ``ci`` to the result.
        ci: The interval level.
        seed: The bootstrap RNG seed.

    Raises:
        ValueError: With fewer than two distinct items, or a comparison of an item with itself.
    """
    import numpy as np

    items, wins = win_matrix(comparisons)
    if len(items) < 2:
        raise ValueError("Bradley-Terry needs at least two distinct items")
    scores, converged = _fit_wins(np.array(wins), prior, max_iter, tol)
    if not np.isfinite(scores).all():
        raise ValueError(
            "an item never wins (or never loses), so its strength is not finite; use prior > 0"
        )
    bounds = None
    if bootstrap > 0:
        rng = np.random.default_rng(seed)
        index = {name: i for i, name in enumerate(items)}
        pairs = np.array([(index[w], index[l]) for w, l in comparisons])
        draws = []
        for _ in range(bootstrap):
            pick = pairs[rng.integers(0, len(pairs), len(pairs))]
            w = np.zeros((len(items), len(items)))
            np.add.at(w, (pick[:, 0], pick[:, 1]), 1.0)
            draws.append(_fit_wins(w, prior, max_iter, tol)[0])
        lo, hi = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
        low, high = np.percentile(draws, [lo, hi], axis=0)
        bounds = tuple((float(a), float(b)) for a, b in zip(low, high))
    return BradleyTerry(
        items=items,
        scores=tuple(float(s) for s in scores),
        n_comparisons=len(comparisons),
        converged=converged,
        connected=_connected(wins),
        ci=bounds,
    )


def _connected(wins) -> bool:
    """Whether every item is linked to every other through some comparison."""
    n = len(wins)
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        for j in range(n):
            if j not in seen and (wins[i][j] or wins[j][i]):
                seen.add(j)
                stack.append(j)
    return len(seen) == n


def _fit_wins(wins, prior: float, max_iter: int, tol: float):
    """MM fit of a ``wins`` matrix; ``(centred log-strengths, converged)``."""
    import numpy as np

    n = wins.shape[0]
    w = wins + prior * (1.0 - np.eye(n))  # virtual games against every other item
    games = w + w.T  # games played between i and j (prior included)
    total_wins = w.sum(axis=1)
    p = np.ones(n)
    converged = False
    for _ in range(max_iter):
        if not np.isfinite(p).all() or (p <= 0).any():
            break  # a winless item at prior 0: no finite fit (the caller raises)
        denom = (games / (p[:, None] + p[None, :])).sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            new = total_wins / denom
            new = new / np.exp(np.mean(np.log(new)))  # fix the scale: geometric mean 1
            done = np.max(np.abs(np.log(new) - np.log(p))) < tol
        p = new
        if done:
            converged = True
            break
    with np.errstate(divide="ignore", invalid="ignore"):
        log_p = np.log(p)
    return log_p - log_p.mean(), converged
