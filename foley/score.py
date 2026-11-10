"""``score()`` — the one-call AI-first entry: narration text → a tasteful, woven sound design.

The stable high-level contract downstream packages (``braidio``, ``nw``) and AI agents call:
hand it narration text (a string, or a list of segments) and — optionally — the narration
audio, and it runs the full SELECT→WEAVE arc with tasteful restraint, returning an **editable
timeline**, a per-segment **rationale**, and (when audio is given) a **mastered mix** + SDH
captions + credits. It composes the existing façade (``find`` → ``plan`` → ``weave``) under one
observability run scope; every knob is an optional keyword with a smart default.

The "taste" is inherited from the SELECT policy, not re-invented here: the salience/density
budget keeps it sparse (not every sentence gets a sound), the **fail-closed license gate**
runs before verification, and the verify ladder (clap → listen → judge) guards fit — so a
one-call ``foley.score(segments, audio=...)`` yields a restrained, license-clean result.

**What the spend cap means** (``max_usd=`` / ``budget=Budget(max_usd=...)``, #281): no
call of known cost is made that would take the run past the cap. Before each segment, its
worst case (:func:`foley.agent.tools.find_upper_bound`) is checked against what is left:

* if it does not fit, the segment runs **retrieval-only** (no generation fallback);
* if even that does not fit (paid LLM rungs), the segment is **skipped** — unless nothing
  has been spent yet, in which case ``score`` raises before spending anything, as
  ``find`` does.

Each degraded segment is named in :attr:`ScoreResult.notes`. A call of *unknown* cost
runs only when approved (``approve_unknown_cost``) and is counted, not summed:
:attr:`ScoreResult.spent_usd` is then a lower bound, which
:attr:`ScoreResult.unknown_cost_calls` says (#280).

Stdlib-only at import (numpy/torch/whisperx stay lazy inside ``find``/``weave``), so importing
this keeps ``import foley`` dol-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Sequence, Union

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .base import MasterProfile, SoundDesignTimeline
    from .weave import WeaveResult


@dataclass
class ScoredEvent:
    """One chosen sound placed for a narration event (a JSON-friendly rationale row)."""

    segment: int
    query: str
    sound_id: str
    origin: Optional[str]
    confidence: Optional[float]
    reason: str

    def to_dict(self) -> dict:
        """Plain-dict form (for the MCP projection / a caller's log)."""
        return {
            "segment": self.segment,
            "query": self.query,
            "sound_id": self.sound_id,
            "origin": self.origin,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class ScoreResult:
    """The output of :func:`score` — the editable plan + per-event rationale (+ mix when woven)."""

    timeline: "SoundDesignTimeline"
    events: "list[ScoredEvent]"
    weave: "Optional[WeaveResult]" = None
    #: What the run spent on calls of known cost, in USD (a lower bound when
    #: :attr:`unknown_cost_calls` is not zero).
    spent_usd: float = 0.0
    #: Calls this run made whose cost is unknown (approved, counted, not in ``spent_usd``).
    unknown_cost_calls: int = 0
    #: Segments the spend cap degraded: run retrieval-only, or skipped (#281).
    notes: "list[str]" = field(default_factory=list)

    @property
    def has_unknown_costs(self) -> bool:
        """Whether :attr:`spent_usd` leaves out calls of unknown cost (never read as free)."""
        return self.unknown_cost_calls > 0

    @property
    def n_sounds(self) -> int:
        """How many sounds were placed (the restraint check — fewer than one-per-sentence)."""
        return len(self.events)

    @property
    def rationale(self) -> str:
        """A short, agent/human-readable summary of what was chosen and why."""
        header = f"Scored {self.n_sounds} sound(s) across the narration:"
        rows = [
            f"  [seg {e.segment}] {e.query!r} → {e.sound_id} "
            f"({e.origin}, conf={e.confidence:.2f}): {e.reason}"
            if e.confidence is not None
            else f"  [seg {e.segment}] {e.query!r} → {e.sound_id} ({e.origin})"
            for e in self.events
        ]
        return "\n".join([header, *rows])


def score(
    segments,
    *,
    audio=None,
    transcript: Optional[str] = None,
    segment_starts: "Optional[Sequence[float]]" = None,
    library=None,
    intended_use=None,
    commercial_ok: Optional[bool] = None,
    max_events: int = 6,
    verify: str = "listen",
    backend: "Union[str, tuple]" = "auto",
    allow_generate: bool = True,
    master: "Union[str, MasterProfile]" = "podcast",
    weave: Optional[bool] = None,
    llm: Optional[str] = None,
    budget=None,
    max_usd: Optional[float] = None,
    **weave_kwargs,
) -> ScoreResult:
    """Choose sounds for narration text and (optionally) weave them into the narration audio.

    Progressive disclosure — the AI-first headline::

        foley.score("She pushed open the heavy oak door; rain hammered outside.")  # plan only
        foley.score(segments, audio="narration.wav")  # + mastered mix, captions, credits

    For each segment it runs the SELECT loop (``decompose → search → verify → decide``) with
    the fail-closed license gate and tasteful restraint, folds the chosen sounds into ONE
    editable :class:`~foley.base.SoundDesignTimeline`, and — when ``audio`` is given (or
    ``weave=True``) — aligns + weaves into a mastered mix. Returns a :class:`ScoreResult`.

    Args:
        segments: The narration text — a single string, or a list of segment strings.
        audio: The narration voice audio (path / bytes / ndarray / a library ref). When
            given, the result is woven into a mastered mix (set ``weave=False`` to skip).
        transcript: The full narration transcript for alignment (default: the segments joined).
        segment_starts: Each segment's start in ``audio``, in seconds (one per segment,
            non-decreasing), e.g. when the narration is one file per beat, concatenated.
            Word timings are then aligned per segment over its own span (the last runs to
            the audio's end), through a :class:`~foley.weave.SegmentedAligner` wrapping
            ``aligner=`` (default: WhisperX if installed, else the fake). Without it, the
            aligner aligns the whole file. Only used when weaving (a warning says so
            otherwise).
        library: The :class:`foley.index.SoundLibrary` (default: the process-wide default).
        intended_use: The rights intent (default:
            :data:`foley.licensing.DEFAULT_INTENDED_USE` — commercial publishing, the
            same default as :func:`foley.find` and every MCP tool).
        commercial_ok: Shorthand override of the default intent's ``commercial``;
            ``False`` explicitly admits non-commercial material.
        max_events: The sparse density cap **per segment** (restraint).
        verify: The max verify rung — ``'clap'`` | ``'listen'`` | ``'judge'``.
        backend: The generation fallback's backend (a name, or a tuple of names as your
            own order), forwarded to :func:`foley.find` (``'auto'`` walks the
            generation order).
        allow_generate: ``False`` makes the run retrieval-only: no generation fallback
            (so no generation spend and no local model process); an event nothing in the
            library fits stays silent. Same name as
            :attr:`~foley.agent.policy.Budget.allow_generate`: ``False`` overrides a
            ``budget`` that allows generation; ``True`` (default) leaves the budget's
            own setting in force.
        master: The delivery :data:`~foley.base.MASTER_PROFILES` target (``'podcast'``
            default) or a :class:`~foley.base.MasterProfile`. foley always masters the
            woven mix (the true-peak limiter is what keeps the summed voice + beds +
            spots from clipping): pass your delivery target here rather than
            re-levelling ``result.weave.audio``.
        weave: Force weaving on/off; default auto (``True`` iff ``audio`` is given).
        llm: Which LLM the SELECT rungs use (``'fake'`` | ``'local'`` | ``'anthropic'``;
            ``None`` reads ``$FOLEY_LLM``, else the free default) — see :func:`foley.find`.
        budget: The run's :class:`~foley.agent.policy.Budget` — one spend cap
            (``max_usd``) across every segment's paid calls (#57). Default: $1, or $3
            when ``llm`` (or ``$FOLEY_LLM``) is ``'anthropic'``
            (:func:`foley.cost.default_max_usd`, #88). What a host can rely on the cap
            to mean is in this module's docstring.
        max_usd: Shorthand for ``budget=Budget(max_usd=max_usd)`` (#283); passing both
            is a ``TypeError``.
        **weave_kwargs: Forwarded to :func:`foley.weave` (e.g. ``language``, ``aligner``,
            ``sign_cert``, ``watermark``). Checked against ``weave``'s signature before
            anything runs, so a typo costs nothing.

    Returns:
        A :class:`ScoreResult` (``timeline`` + ``events`` rationale; ``weave`` when woven).

    Raises:
        TypeError: If a ``weave_kwargs`` key is not a :func:`foley.weave` option (raised
            before any find, verify or generation call), or if both ``budget`` and
            ``max_usd`` are given.
        BudgetExceeded: If the first segment cannot afford even a retrieval-only run
            (nothing has been spent).
        ValueError: If ``master`` is an unknown profile name, or ``segment_starts`` does
            not fit the segments, the transcript or (for a path, bytes or an array) the
            audio's duration, all raised just as early. For a library ref or a file-like
            ``audio``, a start past its end is only caught once ``weave`` decodes it.
    """
    from . import find, obs, plan
    from . import weave as _weave
    from .index import default_library
    from .base import resolve_master
    from .licensing import intended_use_for

    # fail fast: a typo raises before any find/verify/generation spend
    _check_weave_kwargs(weave_kwargs)
    budget = _budget_from(budget, max_usd)
    master = resolve_master(master)
    segs = [segments] if isinstance(segments, str) else list(segments)
    use = intended_use_for(intended_use, commercial_ok=commercial_ok)
    full_transcript = transcript or " ".join(segs)
    do_weave = (audio is not None) if weave is None else bool(weave)
    if segment_starts is not None:
        from .weave import SegmentedAligner

        seg_aligner = SegmentedAligner(
            segment_starts, segs, base=weave_kwargs.get("aligner")
        )
        seg_aligner.split(full_transcript)  # fail fast on a transcript that won't split
        if not do_weave:
            import warnings

            warnings.warn(
                "segment_starts is unused: nothing is woven (pass audio=, and not "
                "weave=False, for word timings)",
                stacklevel=2,
            )
        else:
            sr = _weave_option(weave_kwargs, "sr")
            duration = _narration_duration(audio, library=library, sr=sr)
            if duration is not None:  # a start past the audio's end, before SELECT
                seg_aligner.spans(duration, sample_rate=sr)
        weave_kwargs = {**weave_kwargs, "aligner": seg_aligner}

    find_kw = {
        "max_events": max_events,
        "verify": verify,
        "backend": backend,
        "intended_use": use,
        "llm": llm,
    }
    if budget is not None:
        find_kw["budget"] = budget  # its loop counts and its cap, for every segment
    if library is not None:
        find_kw["library"] = library

    all_candidates = []
    events: "list[ScoredEvent]" = []
    from .agent.policy import Budget
    from .cost import active_budget, default_max_usd, spend_scope

    if budget is None and active_budget() is None:
        # One cap for the whole score run, sized to the LLM the caller chose (#88).
        budget = Budget(max_usd=default_max_usd(llm))
    # find's loop budget turns the fallback off (its pre-flight then counts no
    # generation); the run's spend is still capped by the scope below.
    loop_budget = find_kw.get("budget") or budget or active_budget()
    retrieval_only_kw = {**find_kw, "budget": loop_budget.without_generation()}
    # What each segment may run, fullest first (#281: degrade, do not raise mid-run).
    find_options = (
        (find_kw, retrieval_only_kw) if allow_generate else (retrieval_only_kw,)
    )
    notes: "list[str]" = []
    with (
        obs.run(
            "score",
            params={
                "n_segments": len(segs),
                "verify": str(verify),
                "backend": str(backend),
                "allow_generate": allow_generate,
            },
        ),
        spend_scope(budget) as run_budget,
    ):
        spent0, unknown0 = run_budget.spent_usd, run_budget.unknown_cost_calls
        for i, seg in enumerate(segs):
            seg_kw = _affordable_find_kw(
                seg,
                i,
                find_options,
                notes=notes,
                nothing_spent=(
                    run_budget.spent_usd == spent0
                    and run_budget.unknown_cost_calls == unknown0
                ),
            )
            if seg_kw is None:
                continue
            for c in find(seg, **seg_kw):
                all_candidates.append(c)
                v = c.verdict
                events.append(
                    ScoredEvent(
                        segment=i,
                        query=(c.event.query if c.event else ""),
                        sound_id=c.sound.id,
                        origin=getattr(c.origin, "value", c.origin),
                        confidence=(float(v.confidence) if v is not None else None),
                        reason=(v.reason if (v is not None and v.reason) else "chosen"),
                    )
                )
        timeline = plan(
            all_candidates,
            transcript=full_transcript,
            intended_use=use,
            library=library,
        )
        woven = None
        if do_weave:
            wk = {
                "master": master,
                "transcript": full_transcript,
                "intended_use": use,
                **weave_kwargs,
            }
            # weave judges every clip by its library record: the one find drew from
            wk["library"] = library if library is not None else default_library()
            woven = _weave(audio, timeline, **wk)
            timeline = woven.timeline
        spent = round(run_budget.spent_usd - spent0, 10)
        unknown = run_budget.unknown_cost_calls - unknown0
    return ScoreResult(
        timeline=timeline,
        events=events,
        weave=woven,
        spent_usd=spent,
        unknown_cost_calls=unknown,
        notes=notes,
    )


def _budget_from(budget, max_usd: Optional[float]):
    """``budget``, or ``Budget(max_usd=max_usd)`` for the shorthand (never both)."""
    if max_usd is None:
        return budget
    if budget is not None:
        raise TypeError(
            "pass budget= or max_usd=, not both (max_usd is shorthand for "
            "budget=Budget(max_usd=...))"
        )
    from .agent.policy import Budget

    return Budget(max_usd=max_usd)


#: The arguments of :func:`foley.find` that size its worst case (``find_upper_bound``).
_BOUND_KEYS = ("max_events", "backend", "llm", "verify", "budget")


def _affordable_find_kw(seg: str, i: int, options, *, notes: list, nothing_spent: bool):
    """The first of ``options`` (``find`` keywords, fullest first) whose worst case fits
    every budget in force, else ``None`` (skip the segment); a fallback is noted.

    Raises the refusal when nothing fits and nothing has been spent yet: the run then
    fails before spending, as ``find``'s own pre-flight does.
    """
    from .agent.tools import find_upper_bound
    from .cost import BudgetExceeded, check

    refusals: "list[BudgetExceeded]" = []
    for kw in options:
        bound = find_upper_bound(seg, **{k: kw[k] for k in _BOUND_KEYS if k in kw})
        try:
            check(bound, what=f"segment {i} (upper bound)")
        except BudgetExceeded as exc:
            refusals.append(exc)
            continue
        if refusals:
            notes.append(f"segment {i}: retrieval-only: {refusals[0]}")
        return kw
    if nothing_spent:
        raise refusals[-1]
    notes.append(f"segment {i}: skipped: {refusals[-1]}")
    return None


def _weave_option(weave_kwargs: dict, name: str):
    """The value :func:`foley.weave` will use for ``name``: the caller's, else its default."""
    import inspect

    from .weave import weave

    if name in weave_kwargs:
        return weave_kwargs[name]
    return inspect.signature(weave).parameters[name].default


def _narration_duration(audio, *, library, sr: int) -> Optional[float]:
    """The narration's duration in seconds when it is cheap to know before SELECT, else ``None``.

    An array is in weave's working layout at ``sr``; a path or bytes is read from its
    header. A library ref (or a file-like object) is left to ``weave``.
    """
    import os

    from .audio import duration_s

    if hasattr(audio, "shape"):
        return int(audio.shape[0]) / sr
    if isinstance(audio, (bytes, bytearray)):
        return duration_s(audio)
    if isinstance(audio, (str, os.PathLike)):
        is_ref = isinstance(audio, str) and library is not None and audio in library
        if not is_ref and os.path.isfile(audio):
            return duration_s(audio)
    return None


def _check_weave_kwargs(weave_kwargs: dict) -> None:
    """Raise ``TypeError`` for a key :func:`foley.weave` would refuse, naming near misses."""
    import inspect
    from difflib import get_close_matches

    from .weave import weave

    params = inspect.signature(weave).parameters.values()
    if any(p.kind is p.VAR_KEYWORD for p in params):
        return  # weave takes any keyword: nothing to check against
    accepted = {p.name for p in params if p.kind is p.KEYWORD_ONLY}
    unknown = sorted(set(weave_kwargs) - accepted)
    if not unknown:
        return
    own = set(inspect.signature(score).parameters) - {"segments", "weave_kwargs"}
    known = sorted(accepted | own)
    hints = {u: get_close_matches(u, known, n=1) for u in unknown}
    hint = "; ".join(f"{u!r}: did you mean {m[0]!r}?" for u, m in hints.items() if m)
    raise TypeError(
        f"score() got unexpected keyword argument(s) {unknown} (neither a score() "
        f"nor a foley.weave option; nothing was run). "
        + (hint + ". " if hint else "")
        + f"Known: {known}"
    )
