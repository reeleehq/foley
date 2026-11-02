"""The sound-design timeline as an editable document — hydrate, edit, caption.

The timeline is the SSOT and the reproducible seed; :func:`foley.weave.render` is a
pure projection of it. This module owns the *document* operations, all pure and
stdlib-only (no numpy, no I/O):

* :func:`hydrate` — resolve each item's symbolic anchor into a concrete
  :class:`~foley.base.Placement` and fill processing/id defaults, **idempotently**
  (``hydrate ∘ hydrate == hydrate``) and without clobbering a hand-set placement.
* Pure edit transforms (:func:`swap_clip`, :func:`nudge`, :func:`set_gain`,
  :func:`toggle`, :func:`set_master`) — each returns a NEW timeline, so an edit +
  re-render reproduces exactly that change (the "editable, re-renderable" DoD).
* Accessibility **SDH captions** (:func:`to_webvtt` / :func:`to_srt`) — bracketed
  SFX labels (``[door creak]``) derived from the *items*, never from the narration
  transcript, so no speech text leaks into a shipped caption file.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Optional

from ..base import Processing, SoundDesignTimeline, TimelineItem
from .anchor import parse_symbolic_anchor, resolve_anchor, resolve_placement

#: How long a one-shot's caption stays on screen (seconds) when the item has no
#: resolved duration of its own.
DISPLAY_WINDOW_S: float = 2.0


def _cue_id(item: TimelineItem, placement) -> str:
    """A stable, content-derived cue id for ``item`` (clip + symbolic anchor + layer).

    Deterministic across re-renders (so caches and diffs are stable) and independent
    of list position. Collisions between genuinely-identical placements are
    disambiguated by :func:`hydrate`.
    """
    key = "|".join(
        str(x)
        for x in (
            item.clip_ref,
            item.onset,
            item.layer.value if hasattr(item.layer, "value") else item.layer,
            placement.anchor.value
            if hasattr(placement.anchor, "value")
            else placement.anchor,
            placement.ref,
        )
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def hydrate(
    timeline: SoundDesignTimeline, word_timeline: "Optional[list]" = None
) -> SoundDesignTimeline:
    """Resolve every item's anchor + fill processing/id, returning a NEW timeline.

    Idempotent: an item that already carries a :class:`~foley.base.Placement` keeps
    its symbolic anchor (a hand edit is never clobbered) but is re-resolved against
    ``word_timeline`` so a re-recorded/re-aligned narration re-flows the SFX
    (report 06 §6.1); each placement records how its anchor matched
    (``match_kind``, #263). ``processing`` falls back to the sparse ``gain`` and ``id`` to a
    stable content hash. The resolved ``word_timeline`` is cached on the returned
    timeline (the reproducible seed).

    Args:
        timeline: The (sparse or partially-resolved) timeline.
        word_timeline: The forced alignment; defaults to ``timeline.word_timeline``.

    Returns:
        A hydrated copy with resolved placements, filled processing, stable ids.
    """
    wt = word_timeline if word_timeline is not None else timeline.word_timeline
    items: "list[TimelineItem]" = []
    seen: "dict[str, int]" = {}
    for it in timeline.items:
        placement = it.placement or parse_symbolic_anchor(
            it.onset, layer=it.layer, loop=it.loop
        )
        resolved = resolve_placement(placement, wt)
        resolved = replace(resolved, loop=placement.loop or it.loop)
        processing = it.processing or Processing(gain_db=it.gain)
        cue = it.id or _cue_id(it, resolved)
        if cue in seen:  # disambiguate identical placements, deterministically
            seen[cue] += 1
            cue = f"{cue}-{seen[cue]}"
        else:
            seen[cue] = 0
        items.append(replace(it, id=cue, placement=resolved, processing=processing))
    return replace(timeline, items=items, word_timeline=list(wt))


def _find(timeline: SoundDesignTimeline, item_id: str) -> int:
    """Index of the item whose id (or clip_ref) matches ``item_id``; -1 if none."""
    for i, it in enumerate(timeline.items):
        if it.id == item_id or it.clip_ref == item_id:
            return i
    return -1


def _edit_item(
    timeline: SoundDesignTimeline, item_id: str, **changes
) -> SoundDesignTimeline:
    """Return a NEW timeline with ``changes`` applied to the matching item."""
    idx = _find(timeline, item_id)
    if idx < 0:
        raise KeyError(f"no timeline item with id/clip_ref {item_id!r}")
    items = list(timeline.items)
    items[idx] = replace(items[idx], **changes)
    return replace(timeline, items=items)


def swap_clip(
    timeline: SoundDesignTimeline, item_id: str, new_clip_ref: str
) -> SoundDesignTimeline:
    """Swap an item's clip (keeping its placement/processing) — a NEW timeline."""
    return _edit_item(timeline, item_id, clip_ref=new_clip_ref)


def nudge(
    timeline: SoundDesignTimeline, item_id: str, delta_s: float
) -> SoundDesignTimeline:
    """Shift an item's resolved onset by ``delta_s`` seconds — a NEW timeline.

    Resolves the item's anchor against the timeline's ``word_timeline`` first, then shifts
    the resolved onset and pins the anchor to ``absolute`` so the manual offset survives a
    re-hydrate. This means nudging a still-symbolic (not-yet-hydrated) item on a timeline
    that carries alignment shifts from the item's *true* resolved onset, not from 0. On a
    pre-alignment timeline with no ``word_timeline`` a word/sentence anchor is genuinely
    unresolvable, so there the shift is relative to 0 — hydrate/weave first for such items.
    """
    idx = _find(timeline, item_id)
    if idx < 0:
        raise KeyError(f"no timeline item with id/clip_ref {item_id!r}")
    it = timeline.items[idx]
    from ..base import Anchor, MatchKind

    base = it.placement or parse_symbolic_anchor(it.onset, layer=it.layer, loop=it.loop)
    onset0, _ = resolve_anchor(base, list(timeline.word_timeline or ()))
    moved = replace(
        base,
        anchor=Anchor.absolute,
        match_kind=MatchKind.absolute,
        onset=max(0.0, onset0 + delta_s),
        # onset0 already folds in any pre_roll; zero it so a re-hydrate (absolute branch)
        # doesn't subtract the pre_roll a second time.
        pre_roll=0.0,
    )
    items = list(timeline.items)
    items[idx] = replace(it, placement=moved)
    return replace(timeline, items=items)


def set_gain(
    timeline: SoundDesignTimeline, item_id: str, gain_db: float
) -> SoundDesignTimeline:
    """Set an item's processing gain (dB, voice-relative) — a NEW timeline."""
    idx = _find(timeline, item_id)
    if idx < 0:
        raise KeyError(f"no timeline item with id/clip_ref {item_id!r}")
    it = timeline.items[idx]
    proc = replace(it.processing or Processing(gain_db=it.gain), gain_db=gain_db)
    items = list(timeline.items)
    items[idx] = replace(it, processing=proc, gain=gain_db)
    return replace(timeline, items=items)


def toggle(
    timeline: SoundDesignTimeline, item_id: str, enabled: bool
) -> SoundDesignTimeline:
    """Non-destructively mute/unmute an item — a NEW timeline."""
    return _edit_item(timeline, item_id, enabled=enabled)


def set_master(timeline: SoundDesignTimeline, master) -> SoundDesignTimeline:
    """Set the timeline's master profile (name or :class:`MasterProfile`) — a NEW timeline."""
    from ..base import resolve_master

    return replace(timeline, master=resolve_master(master))


# ---------------------------------------------------------------------------
# SDH captions (WebVTT / SRT) — from the items, never the narration transcript
# ---------------------------------------------------------------------------


def _label(item: TimelineItem) -> str:
    """A bracketed SDH label for ``item`` (e.g. ``[door creak]``), from its event/clip.

    Prefers the originating :class:`~foley.base.SoundEvent`'s ``query``/``caption``
    (carried on ``item.event``), else a humanised ``clip_ref``. Never reads the
    narration transcript, so no speech text can leak into the caption file.
    """
    text = ""
    if isinstance(item.event, dict):
        text = str(item.event.get("query") or item.event.get("caption") or "").strip()
    if not text:
        text = str(item.clip_ref).replace("_", " ").replace("-", " ").strip()
    return f"[{text}]"


def _fmt_ts(seconds: float, *, sep: str) -> str:
    """Format ``seconds`` as ``HH:MM:SS<sep>mmm`` (``sep='.'`` VTT, ``','`` SRT)."""
    seconds = max(0.0, seconds)
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    if ms == 1000:  # rounding spilled into the next second
        s += 1
        ms = 0
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}{sep}{ms:03d}"


def _caption_cues(
    timeline: SoundDesignTimeline, *, window_s: float
) -> "list[tuple[float, float, str]]":
    """Ordered ``(start, end, label)`` caption cues for enabled, placed items."""
    cues: "list[tuple[float, float, str]]" = []
    for it in timeline.items:
        if not it.enabled or it.placement is None:
            continue
        start = float(it.placement.onset)
        dur = it.placement.duration if it.placement.duration else window_s
        cues.append((start, start + float(dur), _label(it)))
    cues.sort(key=lambda c: (c[0], c[1]))
    return cues


def to_webvtt(
    timeline: SoundDesignTimeline, *, window_s: float = DISPLAY_WINDOW_S
) -> str:
    """Render the timeline's SFX cues as a WebVTT SDH caption file (report 06 / issue #8).

    Each enabled, placed item becomes one ``[bracketed]`` cue at its resolved onset.
    """
    lines = ["WEBVTT", ""]
    for start, end, label in _caption_cues(timeline, window_s=window_s):
        lines.append(f"{_fmt_ts(start, sep='.')} --> {_fmt_ts(end, sep='.')}")
        lines.append(label)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def to_srt(timeline: SoundDesignTimeline, *, window_s: float = DISPLAY_WINDOW_S) -> str:
    """Render the timeline's SFX cues as an SRT SDH caption file (report 06 / issue #8)."""
    blocks: "list[str]" = []
    for i, (start, end, label) in enumerate(
        _caption_cues(timeline, window_s=window_s), start=1
    ):
        blocks.append(
            f"{i}\n{_fmt_ts(start, sep=',')} --> {_fmt_ts(end, sep=',')}\n{label}\n"
        )
    return "\n".join(blocks)
