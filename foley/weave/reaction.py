"""Audience-reaction timing — a crowd answers an event, it does not coincide with it.

The mistake this module exists to prevent: syncing a cheer, laugh or applause clip to the
*instant of the on-screen event*. A real audience needs time to see, recognise and react,
so the reaction must start **after** the event has become legible, then swell, then decay.
Placing it on the event reads as a laugh track pasted on the cut; placing it after reads
as a room reacting.

Pure and stdlib-only. The numbers are working craft defaults (see :data:`REACTIONS`), not
measurements: published latency data for audience laughter/applause is thin, and the
figures here are the conventional sound-editing ones (a beat of recognition, a swell of a
second or so, a tail that thins out). Tune them per scene with ``latency=``.

Rules encoded here (each is one keyword or field):

* **Legibility, not occurrence.** ``legible_at`` is when the audience can *see* the event
  (an entrance when the figure is mostly on screen, a reveal when the new face has settled),
  and the latency is added to that, never to the start of the motion.
* **Rise, then fall.** A reaction has an attack (``rise_s``) to ``peak`` and a ``decay_s``
  tail; ``gain_points`` returns the envelope as ``(t, gain)`` breakpoints.
* **Second waves are smaller.** A repeat of the same reaction peaks lower
  (:data:`REPEAT_PEAK`), so cheers "die down" and bump again rather than climb forever.
* **Cut a crowd with a hush.** :func:`hush_plan` places a "shh" after the applause has run
  its course and ducks the applause under it, so the characters can sleep.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Reaction:
    """How one kind of crowd response is shaped, relative to the event that triggers it."""

    latency_s: float  # event legible -> first audible response
    rise_s: float  # onset -> peak
    decay_s: float  # peak -> fade to silence (the tail)
    peak: float = 1.0  # linear gain at the peak


#: Working defaults per reaction kind (seconds). Overridable per call.
REACTIONS: Mapping[str, Reaction] = {
    "gasp": Reaction(0.20, 0.15, 0.6, 0.7),
    "whistle": Reaction(0.45, 0.05, 0.5, 0.8),
    "cheer": Reaction(0.50, 0.9, 3.0, 1.0),  # surprised-and-glad: fast swell, slow thinning
    "laugh": Reaction(0.60, 0.5, 1.8, 0.9),  # needs the gag to land; shortest swell
    "applause": Reaction(0.55, 1.1, 2.5, 0.9),  # claps ripple in: never full density at once
}

#: Peak multiplier for each successive repeat of the same kind in one scene.
REPEAT_PEAK: float = 0.65

#: Seconds the applause is allowed to run at full before a hush, and how long the hush
#: takes to bring the room down (the applause is ducked, not hard-cut).
HUSH_AFTER_S: float = 1.2
HUSH_DUCK_S: float = 0.7


@dataclass(frozen=True)
class ReactionCue:
    """One placed crowd response (times are shot-local seconds)."""

    kind: str
    event_t: float  # when the event became legible
    onset: float  # first audible moment
    peak_t: float
    end: float  # when the tail has faded to silence
    peak: float  # linear gain at the peak

    def gain_points(self) -> list[tuple[float, float]]:
        """Envelope breakpoints ``(t, gain)``: silence -> peak -> silence."""
        return [(self.onset, 0.0), (self.peak_t, self.peak), (self.end, 0.0)]


def reaction_cue(
    kind: str,
    legible_at: float,
    *,
    latency: float | None = None,
    repeat: int = 0,
    table: Mapping[str, Reaction] = REACTIONS,
) -> ReactionCue:
    """Place a ``kind`` response to an event that became legible at ``legible_at``.

    ``repeat`` is how many earlier responses of this kind the scene already had; each one
    scales the peak by :data:`REPEAT_PEAK`.

    >>> c = reaction_cue("cheer", 1.0)
    >>> c.onset > c.event_t
    True
    >>> reaction_cue("cheer", 6.0, repeat=1).peak < reaction_cue("cheer", 1.0).peak
    True
    """
    if kind not in table:
        raise KeyError(f"unknown reaction kind {kind!r}; known: {sorted(table)}")
    r = table[kind]
    onset = legible_at + (r.latency_s if latency is None else latency)
    return ReactionCue(
        kind=kind,
        event_t=legible_at,
        onset=onset,
        peak_t=onset + r.rise_s,
        end=onset + r.rise_s + r.decay_s,
        peak=r.peak * REPEAT_PEAK**repeat,
    )


def reaction_plan(
    events: Sequence[tuple[str, float]],
    *,
    table: Mapping[str, Reaction] = REACTIONS,
) -> list[ReactionCue]:
    """Place ``[(kind, legible_at), ...]``, shrinking repeats of a kind automatically.

    >>> [c.kind for c in reaction_plan([("cheer", 1.0), ("laugh", 4.0), ("cheer", 6.0)])]
    ['cheer', 'laugh', 'cheer']
    """
    seen: dict[str, int] = {}
    cues = []
    for kind, t in sorted(events, key=lambda e: e[1]):
        cues.append(reaction_cue(kind, t, repeat=seen.get(kind, 0), table=table))
        seen[kind] = seen.get(kind, 0) + 1
    return cues


def hush_plan(
    applause: ReactionCue,
    *,
    after: float | None = None,
) -> tuple[float, ReactionCue]:
    """Where a "shh" goes to quiet ``applause``, and the applause cue ducked to match.

    Returns ``(shh_onset, ducked_applause)``. The hush lands ``HUSH_AFTER_S`` after the
    applause peak (or at ``after``), and the applause fades out over ``HUSH_DUCK_S`` from
    then, so the crowd is *answering* the hush rather than being cut.

    >>> t, a = hush_plan(reaction_cue("applause", 8.0))
    >>> a.end > t
    True
    """
    t = applause.peak_t + HUSH_AFTER_S if after is None else after
    return t, replace(applause, end=t + HUSH_DUCK_S)
