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

Stdlib-only at import (numpy/torch/whisperx stay lazy inside ``find``/``weave``), so importing
this keeps ``import foley`` dol-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .base import SoundDesignTimeline
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
    library=None,
    intended_use=None,
    commercial_ok: Optional[bool] = None,
    max_events: int = 6,
    verify: str = "listen",
    master: str = "podcast",
    weave: Optional[bool] = None,
    llm: Optional[str] = None,
    budget=None,
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
        library: The :class:`foley.index.SoundLibrary` (default: the process-wide default).
        intended_use: The rights intent (default:
            :data:`foley.licensing.DEFAULT_INTENDED_USE` — commercial publishing, the
            same default as :func:`foley.find` and every MCP tool).
        commercial_ok: Shorthand override of the default intent's ``commercial``;
            ``False`` explicitly admits non-commercial material.
        max_events: The sparse density cap **per segment** (restraint).
        verify: The max verify rung — ``'clap'`` | ``'listen'`` | ``'judge'``.
        master: The delivery :data:`~foley.base.MASTER_PROFILES` target (``'podcast'`` default).
        weave: Force weaving on/off; default auto (``True`` iff ``audio`` is given).
        llm: Which LLM the SELECT rungs use (``'fake'`` | ``'local'`` | ``'anthropic'``;
            ``None`` reads ``$FOLEY_LLM``, else the free default) — see :func:`foley.find`.
        budget: The run's :class:`~foley.agent.policy.Budget` — one spend cap
            (``max_usd``) across every segment's paid calls (#57). Default: $1, or $3
            when ``llm`` (or ``$FOLEY_LLM``) is ``'anthropic'``
            (:func:`foley.cost.default_max_usd`, #88).
        **weave_kwargs: Forwarded to :func:`foley.weave` (e.g. ``sign_cert``, ``watermark``).

    Returns:
        A :class:`ScoreResult` (``timeline`` + ``events`` rationale; ``weave`` when woven).
    """
    from . import find, obs, plan
    from . import weave as _weave
    from .licensing import intended_use_for

    segs = [segments] if isinstance(segments, str) else list(segments)
    use = intended_use_for(intended_use, commercial_ok=commercial_ok)
    full_transcript = transcript or " ".join(segs)
    do_weave = (audio is not None) if weave is None else bool(weave)

    find_kw = {
        "max_events": max_events,
        "verify": verify,
        "intended_use": use,
        "llm": llm,
    }
    if budget is not None:
        find_kw["budget"] = budget  # its loop counts and its cap, for every segment
    if library is not None:
        find_kw["library"] = library

    all_candidates = []
    events: "list[ScoredEvent]" = []
    from .cost import active_budget, default_max_usd, spend_scope

    if budget is None and active_budget() is None:
        # One cap for the whole score run, sized to the LLM the caller chose (#88).
        from .agent.policy import Budget

        budget = Budget(max_usd=default_max_usd(llm))
    with (
        obs.run("score", params={"n_segments": len(segs), "verify": str(verify)}),
        spend_scope(budget),
    ):
        for i, seg in enumerate(segs):
            for c in find(seg, **find_kw):
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
            if library is not None:
                wk["library"] = library
            woven = _weave(audio, timeline, **wk)
            timeline = woven.timeline
    return ScoreResult(timeline=timeline, events=events, weave=woven)
