"""Cost: what a call will cost before it is made, and a cumulative cap on a run (#57).

Three pieces, each small:

* **Pricing as data.** Each source declares ``SOURCE_CONFIG['pricing']`` — the falaw
  convention (``unit``, ``amount_usd``, plus the ``source`` and ``seen`` date the price
  was read from). :func:`estimate_call` turns it into dollars for one call, and returns
  ``None`` — never ``0.0`` — when the cost cannot be known (no pricing, or a
  per-second price with no duration and no maximum).
* **A run-scoped budget.** :func:`spend_scope` makes a
  :class:`~foley.agent.policy.Budget` the active one for a ``find`` / ``score`` /
  ``generate`` run; :func:`authorize` is called before every paid call and refuses the
  first one that would take the run past ``max_usd`` (default :func:`default_max_usd`:
  :data:`DEFAULT_MAX_USD`, $1 — maintainer decision on #57 — or, when the caller chose
  a paid LLM for the SELECT rungs, :data:`DEFAULT_MAX_USD_BY_LLM`, #88), or whose cost
  is unknown unless the budget approves unknown costs.
* **Two errors.** :class:`BudgetExceeded` and its subclass :class:`CostApprovalRequired`.

Stdlib-only.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

__all__ = [
    "DEFAULT_MAX_USD",
    "APPROVE_UNKNOWN_COST_ENV",
    "BudgetExceeded",
    "CostApprovalRequired",
    "estimate_call",
    "spend_scope",
    "scoped_iter",
    "active_budget",
    "check",
    "authorize",
    "settle",
    "release",
    "DEFAULT_MAX_USD_BY_LLM",
    "default_max_usd",
    "charge",
]

#: The default cumulative cap for one run (a ``find`` / ``score`` / ``generate`` call).
DEFAULT_MAX_USD: float = 1.0

#: The default cap of a :func:`foley.find` run whose LLM rungs the caller chose to pay
#: for (``llm=`` or ``$FOLEY_LLM``), keyed by provider. With the defaults (6 events,
#: ``k=10``, ``verify='listen'``) Claude's upper bound is about $2.52, so the $1 cap
#: would refuse every such run before its first call; $3 lets it run and still caps
#: it. A run usually spends far less than its bound (#88). ``Budget(max_usd=...)``
#: overrides it.
DEFAULT_MAX_USD_BY_LLM: "dict[str, float]" = {"anthropic": 3.0}


def default_max_usd(llm: Optional[str] = None) -> float:
    """The cap of a run given no budget: higher when the caller chose a paid LLM.

    The provider is the one named by ``llm`` or, failing that, ``$FOLEY_LLM`` (the
    free default never resolves to a paid one); see :data:`DEFAULT_MAX_USD_BY_LLM`.

    >>> default_max_usd("fake")
    1.0
    >>> default_max_usd("anthropic")
    3.0
    """
    import os

    from .agent.llm import LLM_ENV_VAR

    chosen = llm or os.environ.get(LLM_ENV_VAR) or None
    return DEFAULT_MAX_USD_BY_LLM.get(chosen, DEFAULT_MAX_USD)


#: Set to 1 to approve calls whose cost is unknown, for every run that does not say.
APPROVE_UNKNOWN_COST_ENV = "FOLEY_APPROVE_UNKNOWN_COST"

#: The budgets in force, outermost first (see :func:`spend_scope`).
_ACTIVE_BUDGET: "ContextVar[tuple]" = ContextVar("foley_budget", default=())


class BudgetExceeded(RuntimeError):
    """Raised before a paid call that would take the run past its ``max_usd`` cap."""


class CostApprovalRequired(BudgetExceeded):
    """Raised before a call whose cost is unknown, when the budget has not approved that."""


def estimate_call(config: dict, **affordances) -> Optional[float]:
    """The USD cost of one call to the source ``config`` declares, or ``None`` if unknown.

    ``config['pricing']`` units:

    * ``'free'`` (local inference, a free API tier) → ``0.0``;
    * ``'per_call'`` → ``amount_usd``;
    * ``'per_second'`` with ``seconds_from='video'`` → ``amount_usd`` × the video's
      length (``video_duration_s``, measured by the dispatch), else ``None`` (an
      unread length is an unknown cost, which needs approval);
    * ``'per_second'`` with a video (``video_duration_s``) → × the requested
      ``duration_s`` capped at the video's length, else × the video's length;
    * ``'per_second'`` → ``amount_usd`` × the requested ``duration_s``; when none is
      requested, × the ``native_defaults['duration_default_s']`` the adapter sends in
      its place, else × ``native_defaults['duration_max_s']`` (the duration is left to
      the backend: an upper bound), else ``None``.

    Args:
        config: A ``SOURCE_CONFIG``.
        **affordances: The canonical affordances of the call (``duration_s``, …).
    """
    pricing = config.get("pricing")
    if not pricing:
        return None
    unit = pricing.get("unit")
    amount = pricing.get("amount_usd")
    if unit == "free":
        return 0.0
    if amount is None:
        return None
    if unit == "per_call":
        return float(amount)
    if unit == "per_second":
        video_s = affordances.get("video_duration_s")
        if pricing.get("seconds_from") == "video":  # billed by the video's length
            # An unread length (a URL) is an unknown cost: it needs approval.
            return None if video_s is None else float(amount) * float(video_s)
        seconds = affordances.get("duration_s")
        if seconds is None and video_s is not None:  # V2A: the sound covers the video
            seconds = video_s
        if seconds is not None and video_s is not None:  # never longer than the video,
            floor = (config.get("native_defaults") or {}).get("duration_min_s") or 0.0
            seconds = max(
                min(float(seconds), float(video_s)), float(floor)
            )  # nor short
        if seconds is None:
            # What the adapter sends when no duration is asked (its declared default),
            # else the backend's maximum: an upper bound, never zero.
            nd = config.get("native_defaults") or {}
            seconds = nd.get("duration_default_s") or nd.get("duration_max_s")
        return None if seconds is None else float(amount) * float(seconds)
    return None


def actual_call_cost(
    config: dict, *, duration_s: Optional[float] = None
) -> Optional[float]:
    """What a call just made costs at the declared price, for the duration actually sent.

    The same pricing rule as :func:`estimate_call`, so the estimate and the actual
    cannot disagree on it; ``None`` (unknown) when a per-second source was left to
    choose its own length.

    >>> cfg = {"pricing": {"unit": "per_second", "amount_usd": 0.002}}
    >>> actual_call_cost(cfg, duration_s=3.0)
    0.006
    >>> actual_call_cost(cfg) is None
    True
    """
    if duration_s is None and (config.get("pricing") or {}).get("unit") == "per_second":
        return None
    # A source billed by its video's length bills the seconds it actually produced.
    return estimate_call(config, duration_s=duration_s, video_duration_s=duration_s)


def _stack() -> tuple:
    return _ACTIVE_BUDGET.get() or ()


def active_budget():
    """The innermost :class:`~foley.agent.policy.Budget` of the current run, or ``None``."""
    stack = _stack()
    return stack[-1] if stack else None


@contextmanager
def spend_scope(budget=None):
    """Put ``budget`` in force for the block; every enclosing budget stays in force too.

    Budgets stack: a paid call must fit **every** budget in force (so an explicit,
    stricter ``budget`` inside a ``find`` / ``score`` run still applies) and is charged
    to each of them once. With no ``budget``: inside a run, nothing changes; outside
    one, a fresh default :class:`~foley.agent.policy.Budget` is used ($1).

    Yields:
        The innermost budget in force.
    """
    stack = _stack()
    if budget is None and stack:
        yield stack[-1]
        return
    if budget is None:
        from .agent.policy import Budget

        budget = Budget()
    if any(b is budget for b in stack):
        yield budget
        return
    token = _ACTIVE_BUDGET.set((*stack, budget))
    try:
        yield budget
    finally:
        _ACTIVE_BUDGET.reset(token)


def scoped_iter(iterator_factory, budget=None):
    """Iterate ``iterator_factory()`` with ``budget`` in force only while it runs.

    A generator that holds a :func:`spend_scope` across ``yield`` would leave its
    budget active in the caller's context between items (so the caller's own calls, or
    another interleaved stream, would charge it). This re-enters the scope for each
    step and leaves it before handing the item out; closing the stream closes the
    inner iterator inside the scope too.
    """
    stack = _stack()
    if budget is None:
        if stack:
            budget = stack[-1]
        else:
            from .agent.policy import Budget

            budget = Budget()
    iterator = None
    try:
        while True:
            with spend_scope(budget):
                if iterator is None:
                    iterator = iter(iterator_factory())
                try:
                    item = next(iterator)
                except StopIteration:
                    return
            yield item
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            with spend_scope(budget):
                close()


def _budgets() -> tuple:
    stack = _stack()
    if stack:
        return stack
    from .agent.policy import Budget

    return (Budget(),)  # no run in force: this single call is the run


def check(estimate_usd: Optional[float], *, what: str) -> None:
    """Raise unless every budget in force can afford ``estimate_usd`` (reserves nothing).

    For a whole-run upper bound (``find``'s pre-flight).
    """
    for budget in _budgets():
        budget.check(estimate_usd, what=what)


def authorize(estimate_usd: Optional[float], *, what: str) -> None:
    """Admit a paid call: every budget in force must afford it, and each reserves it.

    The reservation is atomic per budget, so concurrent calls cannot all pass before
    any is counted. Call :func:`settle` afterwards with the actual cost when known; a
    call that fails after being sent keeps its reservation (it may have been billed);
    one refused before sending is released with :func:`release`.

    Raises:
        CostApprovalRequired: If ``estimate_usd`` is ``None`` and a budget in force has
            not approved unknown costs (``Budget.approve_unknown_cost`` /
            ``$FOLEY_APPROVE_UNKNOWN_COST``).
        BudgetExceeded: If a budget's spend plus ``estimate_usd`` exceeds its ``max_usd``.
    """
    budgets = _budgets()
    for budget in budgets:
        budget.check(estimate_usd, what=what)
    reserved = []
    try:
        for budget in budgets:
            budget.reserve(estimate_usd, what=what)  # another thread may have got in
            reserved.append(budget)
    except BudgetExceeded:
        for budget in reserved:  # never leave a half-reservation behind
            budget.settle(estimate_usd, 0.0)
        raise


def settle(reserved_usd: Optional[float], actual_usd: Optional[float]) -> None:
    """Replace each budget's reservation with the actual cost (``None``: keep it)."""
    for budget in _stack():
        budget.settle(reserved_usd, actual_usd)


def release(reserved_usd: Optional[float]) -> None:
    """Undo a reservation for a call that was never sent."""
    settle(reserved_usd, 0.0)


def charge(usd: Optional[float]) -> None:
    """Record ``usd`` against every budget in force (a no-op outside any run)."""
    for budget in _stack():
        budget.charge(usd)
