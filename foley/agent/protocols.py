"""The structural DI seams of the SELECT stage — ``Decomposer`` / ``Judge`` / ``Refiner``.

Three ``@runtime_checkable`` :class:`typing.Protocol`\\ s (PEP 544), each a
behaviour-free, open-closed contract that every implementation (the deterministic
fake *and* the Anthropic-backed real impl) satisfies. They are dependency-injected
into :func:`foley.agent.find` by keyword (``decomposer=`` / ``judge=`` / ``refiner=``),
defaulting to a hermetic fake when ``anthropic`` (the ``foley[agent]`` extra) is absent.

Stdlib-only: the ``base`` shapes are imported under ``TYPE_CHECKING`` only (mirroring
:mod:`foley.index.protocols`), so importing this module pulls no heavy dependency and
keeps ``import foley`` dol-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..base import Candidate, SoundEvent, Verdict, VerifyLevel


@runtime_checkable
class Decomposer(Protocol):
    """Narrative context → a sparse, salience-ranked, diegetic-tagged event list.

    Turns a story/commentary passage into ``<= max_events`` :class:`SoundEvent`\\ s,
    enforcing the salience/density budget and the anachronism (``era_place``) guard.
    The default is the deterministic :class:`~foley.agent.decompose.KeywordDecomposer`;
    :class:`~foley.agent.decompose.AnthropicDecomposer` is the LLM-backed impl.
    """

    def decompose(
        self, context: str, *, max_events: int = 6, seconds: Optional[float] = None
    ) -> "list[SoundEvent]":
        """Decompose ``context`` into at most ``max_events`` sound events."""
        ...


@runtime_checkable
class Judge(Protocol):
    """One rung of the verify ladder: does this candidate match this event? (report 10 §4.2).

    ``level`` selects the rung — ``clap`` (cheap score gate),
    ``listen`` (audio-LM), ``judge`` (LLM arbitration + scene consistency). The
    returned :class:`Verdict` carries ``level`` == the rung that produced it. Only the
    ``judge`` rung's real impl calls the LLM.
    """

    def judge(
        self,
        event: "SoundEvent",
        candidate: "Candidate",
        *,
        level: "VerifyLevel" = ...,
    ) -> "Verdict":
        """Judge whether ``candidate`` matches ``event`` at verify rung ``level``."""
        ...


@runtime_checkable
class Refiner(Protocol):
    """One event query → 2–4 paraphrases/expansions (query-expansion for retrieval).

    ``hint`` carries the verify-failure reason so the re-retrieval loop can steer the
    next paraphrases. v1 feeds the list into a multi-query RRF search (embedding-fusion
    is a later drop-in behind this same seam). The default is the deterministic
    :class:`~foley.agent.refine.KeywordRefiner`.
    """

    def refine(
        self, query: str, *, n: int = 3, hint: Optional[str] = None
    ) -> "list[str]":
        """Return ``n`` paraphrases of ``query``, steered by ``hint`` when given."""
        ...
