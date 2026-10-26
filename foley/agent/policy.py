"""The SELECT policy: the fail-closed rights gate + the single generate-vs-retrieve branch.

Two load-bearing invariants live here as two **physically separate pure functions**, so
neither can bypass the other:

* :func:`gate_candidates` — the ONLY rights-rejection point. Runs the fail-closed
  :func:`foley.licensing.keep_sound` gate over the candidate set **before** any
  verification/ranking (invariant #3), sets ``Candidate.license_ok``, and drops every
  non-``True`` candidate.
* :func:`decide` — the ONLY generate-vs-retrieve branch. A **pure** function of an
  already-gated+verified set; it never calls ``keep``/``search``/``generate`` (the
  :mod:`foley.agent.tools` loop owns all side effects).

:class:`Budget` bounds the refine→re-retrieve and generate loops so a hard event can't
run away. This module is stdlib-only (imports only :mod:`foley.base` /
:mod:`foley.licensing`) and does no I/O and no obs — the loop emits the audit Steps.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..base import Candidate, IntendedUse, SoundEvent
from ..cost import (
    APPROVE_UNKNOWN_COST_ENV,
    DEFAULT_MAX_USD,
    BudgetExceeded,
    CostApprovalRequired,
)
from ..licensing import keep_sound


def gate_candidates(
    candidates: "list[Candidate]", intended_use: IntendedUse
) -> "list[Candidate]":
    """Fail-closed license gate — run BEFORE verification/ranking (invariant #3).

    For each candidate: apply :func:`~foley.licensing.keep_sound` (any exception ⇒
    ``False``, fail-closed), record the result on ``candidate.license_ok``, and keep
    ONLY where it is ``True`` — a ``None`` (never gated) or ``False`` is dropped. This is
    the single rights-rejection point; :func:`~foley.agent.verify.verify_match` asserts
    its survivors are license-clean.

    Args:
        candidates: The retrieved shortlist (``license_ok`` typically ``None``).
        intended_use: The caller's declared rights intent.

    Returns:
        The license-clean sublist (each with ``license_ok is True``), order preserved.
    """
    kept: "list[Candidate]" = []
    for c in candidates:
        try:
            ok = keep_sound(c.sound, intended_use)
        except Exception:  # noqa: BLE001 - fail closed on ANY gate error
            ok = False
        c.license_ok = ok
        if ok is True:
            kept.append(c)
    return kept


class DecideAction(str, Enum):
    """What :func:`decide` chose for one event (the single branch's outcomes)."""

    USE = "use"  # a verified, confident, license-clean clip → accept it
    REFINE = "refine"  # low confidence + budget left → re-query and re-retrieve
    GENERATE = (
        "generate"  # non-diegetic, or diegetic gap after refine → generate a clip
    )
    DROP = "drop"  # budget exhausted / no path → silence (a valid Foley choice)


@dataclass
class Decision:
    """The tiny result of :func:`decide`; ``reason`` feeds the refine hint + the audit Step."""

    action: DecideAction
    candidate: Optional[Candidate] = None
    reason: str = ""


def _known(usd) -> bool:
    """A cost that can be summed: not ``None`` and finite (a NaN would poison the run)."""
    return usd is not None and math.isfinite(float(usd))


@dataclass
class Budget:
    """Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).

    Two kinds of bound:

    * **Per event** — ``max_refine_loops`` / ``max_generations``: the loop calls
      :meth:`refine_ok` / :meth:`gen_ok` to test, then :meth:`spend_refine` /
      :meth:`spend_gen` to charge; :meth:`reset` zeroes them at each event.
    * **Per run, cumulative** — ``max_usd`` (default $1): every paid call (generation,
      paid LLM rung) is checked with :meth:`authorize` before it is made and recorded with :meth:`charge`
      after. :meth:`reset` never clears it, so the cap holds across the whole
      ``find`` / ``score`` run. A call whose cost is unknown (estimate ``None``) is
      refused unless ``approve_unknown_cost`` (or ``$FOLEY_APPROVE_UNKNOWN_COST=1``).
    """

    max_refine_loops: int = 1
    max_generations: int = 1
    allow_generate: bool = True
    max_usd: float = DEFAULT_MAX_USD
    approve_unknown_cost: "Optional[bool]" = None  # None -> $FOLEY_APPROVE_UNKNOWN_COST
    _refines: int = 0
    _gens: int = 0
    _spent_usd: float = 0.0
    _unknown_calls: int = 0
    _lock: object = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def spent_usd(self) -> float:
        """Dollars charged so far this run (calls of unknown cost count as 0 here)."""
        return self._spent_usd

    def _approves_unknown(self) -> bool:
        if self.approve_unknown_cost is not None:
            return bool(self.approve_unknown_cost)
        import os

        return os.environ.get(APPROVE_UNKNOWN_COST_ENV, "").lower() in (
            "1",
            "true",
            "yes",
        )

    def check(self, estimate_usd: "Optional[float]", *, what: str) -> None:
        """Raise if this run cannot afford ``estimate_usd`` (nothing is reserved)."""
        with self._lock:
            self._check(estimate_usd, what=what)

    def reserve(self, estimate_usd: "Optional[float]", *, what: str) -> None:
        """Check, then count ``estimate_usd`` as spent at once (atomic under a lock).

        Reserving before the call is what keeps concurrent calls on one budget (MCP
        tools run in a threadpool) from all passing the check before any is charged.
        :meth:`settle` later replaces the reservation with the actual cost, if known.
        """
        with self._lock:
            self._check(estimate_usd, what=what)
            self._add(estimate_usd)

    def settle(
        self, reserved_usd: "Optional[float]", actual_usd: "Optional[float]"
    ) -> None:
        """Replace a reservation with the actual cost (``None`` actual: keep the reservation)."""
        if not _known(actual_usd) or not _known(reserved_usd):
            return
        with self._lock:
            self._spent_usd += float(actual_usd) - float(reserved_usd)

    def authorize(self, estimate_usd: "Optional[float]", *, what: str) -> None:
        """Alias of :meth:`check` (kept for callers that only test affordability)."""
        self.check(estimate_usd, what=what)

    def _check(self, estimate_usd: "Optional[float]", *, what: str) -> None:
        """Refuse a paid call before it is made if this run cannot afford it.

        Raises:
            CostApprovalRequired: If the cost is unknown and not approved.
            BudgetExceeded: If spend + ``estimate_usd`` would exceed ``max_usd``.
        """
        if not _known(
            estimate_usd
        ):  # None, or a NaN/inf estimate: unknown, never summed
            if not self._approves_unknown():
                raise CostApprovalRequired(
                    f"{what}: its cost is unknown, so it needs approval. Pass "
                    "budget=Budget(approve_unknown_cost=True) or set "
                    f"${APPROVE_UNKNOWN_COST_ENV}=1."
                )
            return
        if self._spent_usd + estimate_usd > self.max_usd + 1e-12:
            raise BudgetExceeded(
                f"{what} would cost ~${estimate_usd:.4f}, taking this run to "
                f"${self._spent_usd + estimate_usd:.4f}, over its ${self.max_usd:.2f} cap "
                "(Budget.max_usd). Nothing was called."
            )

    def charge(self, usd: "Optional[float]") -> None:
        """Record a call's cost (``None`` = unknown: counted, not summed)."""
        with self._lock:
            self._add(usd)

    def _add(self, usd: "Optional[float]") -> None:
        if not _known(usd):
            self._unknown_calls += 1
        else:
            self._spent_usd += float(usd)

    def refine_ok(self) -> bool:
        """Whether another refine→re-retrieve pass is within budget."""
        return self._refines < self.max_refine_loops

    def gen_ok(self) -> bool:
        """Whether a generation fallback is allowed and within budget."""
        return self.allow_generate and self._gens < self.max_generations

    def spend_refine(self) -> None:
        """Charge one refine loop."""
        self._refines += 1

    def spend_gen(self) -> None:
        """Charge one generation."""
        self._gens += 1

    def reset(self) -> None:
        """Zero the spend counters so the caps apply *per event*, not per passage.

        The ``find`` loop calls this at the top of each event so one hard event's
        refine/generate spend never starves later events (the documented per-event
        semantics).
        """
        self._refines = 0
        self._gens = 0


def decide(
    event: SoundEvent,
    kept: "list[Candidate]",
    verified: "list[Candidate]",
    *,
    tau_retrieve: float,
    budget: Budget,
    loop: int,
) -> Decision:
    """The single generate-vs-retrieve branch — a PURE function (report 05 §4).

    Chooses among :class:`DecideAction` from the already-gated (``kept``) and
    already-verified (``verified``) sets. It performs no I/O and never calls
    ``keep``/``search``/``generate`` — the :mod:`foley.agent.tools` loop acts on the
    returned :class:`Decision`.

    Policy (report 05 §4):
      * a verified clip clearing ``tau_retrieve`` → ``USE`` (the best one);
      * verified-but-low-confidence with refine budget → ``REFINE`` (feed the reason back);
      * a non-diegetic cue, or a diegetic gap with no verified match, with generate budget
        → ``GENERATE``;
      * otherwise → ``DROP`` (silence), unless a lower-confidence verified clip exists and
        generation is off, in which case fall back to that best-effort pick.

    Args:
        event: The event being resolved.
        kept: The license-clean candidates (each ``license_ok is True``).
        verified: The subset of ``kept`` whose verdict matched.
        tau_retrieve: The confidence threshold for auto-accepting a retrieved clip.
        budget: The per-event cost budget.
        loop: The current refine-loop index (for the audit reason).

    Returns:
        A :class:`Decision`.
    """
    assert all(c.license_ok is True and c.verdict is not None for c in kept), (
        "decide() precondition: every kept candidate must be gated (license_ok) + verified"
    )
    # Non-diegetic mood cues route to generation/music, not the SFX index (report 05 §4).
    if not event.diegetic and budget.gen_ok():
        return Decision(DecideAction.GENERATE, None, reason="non-diegetic mood cue")
    if verified:
        best = max(verified, key=lambda c: c.verdict.confidence if c.verdict else 0.0)
        if best.verdict is not None and best.verdict.confidence >= tau_retrieve:
            return Decision(
                DecideAction.USE,
                best,
                reason=f"confident match ({best.verdict.confidence:.2f})",
            )
    # No confident retrieval — refine first (bounded), then generate, then best-effort/drop.
    if budget.refine_ok():
        why = "low-confidence match" if verified else "no verified match"
        return Decision(
            DecideAction.REFINE, None, reason=f"{why}; refine pass {loop + 1}"
        )
    if budget.gen_ok():
        return Decision(DecideAction.GENERATE, None, reason="diegetic gap after refine")
    if verified:  # generation exhausted/off but a lower-confidence verified clip exists
        best = max(verified, key=lambda c: c.verdict.confidence if c.verdict else 0.0)
        return Decision(
            DecideAction.USE,
            best,
            reason="best-effort verified pick (budget exhausted)",
        )
    return Decision(
        DecideAction.DROP, None, reason="no match; refine/generate budget exhausted"
    )
