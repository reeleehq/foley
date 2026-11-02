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
            (:func:`foley.cost.default_max_usd`, #88).
        **weave_kwargs: Forwarded to :func:`foley.weave` (e.g. ``language``, ``aligner``,
            ``sign_cert``, ``watermark``). Checked against ``weave``'s signature before
            anything runs, so a typo costs nothing.

    Returns:
        A :class:`ScoreResult` (``timeline`` + ``events`` rationale; ``weave`` when woven).

    Raises:
        TypeError: If a ``weave_kwargs`` key is not a :func:`foley.weave` option (raised
            before any find, verify or generation call).
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
            duration = _narration_duration(
                audio, library=library, sr=_weave_option(weave_kwargs, "sr")
            )
            if duration is not None:
                seg_aligner.spans(
                    duration
                )  # a start past the audio's end, before SELECT
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

    if not allow_generate:
        # find's loop budget turns the fallback off (its pre-flight then counts no
        # generation); the run's spend is still capped by the scope below.
        base = budget if budget is not None else Budget(max_usd=default_max_usd(llm))
        find_kw["budget"] = base.without_generation()
    if budget is None and active_budget() is None:
        # One cap for the whole score run, sized to the LLM the caller chose (#88).
        budget = Budget(max_usd=default_max_usd(llm))
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
            # weave judges every clip by its library record: the one find drew from
            wk["library"] = library if library is not None else default_library()
            woven = _weave(audio, timeline, **wk)
            timeline = woven.timeline
    return ScoreResult(timeline=timeline, events=events, weave=woven)


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
