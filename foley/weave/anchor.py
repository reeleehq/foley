"""Symbolic-anchor → sample-onset heuristics — the SELECT→WEAVE timing bridge (report 06 §2.4).

Pure, stdlib-only functions that turn a placed sound's *symbolic* anchor (SELECT's
``"on 'pushed open'"`` string, or a resolved :class:`~foley.base.Placement`) into a
concrete trigger time (seconds) against a forced-aligned ``word_timeline``
(``[{'word','start','end'}, ...]``). Cheapest-first, exactly as report 06 §2.4:

* **word anchor** (one-shots) — fire on the onset of the trigger word;
* **pre-roll** — shift a clip earlier so its salient transient lands on the anchor;
* **sentence span** (beds) — start at the first word of the sentence, run to the last;
* **scene / paragraph boundary** (stingers, ambience swaps) — the boundary's first word;
* **pause snapping** — nudge an onset to the nearest inter-word gap to avoid masking speech.

These are pure ``(anchor, word_timeline) -> seconds`` functions with no I/O and no
heavy dependency, so they are independently unit-testable and keep ``import
foley.weave`` dol-only. Every word lookup goes through one resolver,
:func:`match_word`, which also says HOW it matched (``exact`` / ``stem`` / ``fuzzy`` /
``fallback``); :func:`resolve_placement` records that on the resolved placement. ``foley.weave.anchor.parse_symbolic_anchor`` is the single
SSOT bridge from SELECT's sparse ``TimelineItem.onset`` string to a
:class:`~foley.base.Placement`.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import replace
from typing import Optional

from ..base import Anchor, Layer, MatchKind, Placement

#: Inter-word gap (seconds) that ends a sentence segment (report 06 §2.4 uses
#: ``> ~350 ms`` as a lightweight sentence segmenter over the aligned transcript).
SEGMENT_GAP_S: float = 0.35

#: A stem match needs at least this many letters; a cue shorter than the spoken word
#: must also hold this share of it (``slam`` → ``slammed``), so ``a`` never claims ``apple``.
#: A spoken word that is a compound cue's tail must leave a head this long too
#: (``foot|steps``), so ``th|under`` is not a compound of ``thunder`` (#263).
PREFIX_MIN_CHARS: int = 3
PREFIX_MIN_SHARE: float = 0.5

#: A fuzzy match needs at least this ``difflib`` ratio, and a candidate at least this
#: share of the cue's length: ``the`` scores 0.6 against ``thunder`` but is not it (#257).
FUZZY_MIN_RATIO: float = 0.6
FUZZY_MIN_LENGTH_SHARE: float = 0.6

#: Trailing punctuation that also ends a sentence segment.
_SENTENCE_END = ".!?"

#: A leading connective the symbolic anchor phrase may carry (``on 'x'`` /
#: ``as 'x'`` / ``when 'x'``); stripped so the bare word ref remains.
_LEADING_CONNECTIVE = re.compile(r"^(?:on|at|as|when|during|over)\b", re.IGNORECASE)

_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")
_NUMBER = re.compile(r"[-+]?\d*\.?\d+")
_WORD_TOKEN = re.compile(r"[a-z0-9]+")


def _norm(word: str) -> str:
    """Lower-case a token and strip surrounding punctuation for matching."""
    return "".join(_WORD_TOKEN.findall(word.lower()))


def parse_symbolic_anchor(
    onset: Optional[str], *, layer: "Layer" = Layer.sfx_fg, loop: bool = False
) -> Placement:
    """Parse SELECT's sparse symbolic ``onset`` string into a resolved-later :class:`Placement`.

    The anchor *type* follows the item's role (report 06 §2.4): beds
    (``loop`` / ``ambience`` / ``music``) span a **sentence**, stingers land on a
    **scene** boundary, and everything else is a **word** anchor; the ``ref`` is the
    quoted phrase the sound lands on. A ``None`` onset means "no cue": beds span from
    the start, one-shots sit at ``absolute`` 0; so does a bed's unquoted span phrase
    (``"under the whole line"``), which names no word to land on. A bare number (defensive — SELECT is
    told never to emit one) is read as an absolute offset in seconds.

    Args:
        onset: The symbolic anchor string (e.g. ``"on 'pushed open'"``) or ``None``.
        layer: The item's mix layer (selects span/boundary vs word anchoring).
        loop: Whether the item is a looping bed (span-anchored).

    Returns:
        A :class:`Placement` whose ``onset`` (seconds) is resolved later by
        :func:`resolve_anchor` against the ``word_timeline``.
    """
    is_bed = loop or layer in (Layer.ambience, Layer.music)
    if onset is None:
        return Placement(anchor=Anchor.sentence if is_bed else Anchor.absolute)
    text = onset.strip()
    quoted = _QUOTED.search(text)
    if quoted is None:
        # No quoted phrase. A pure number (no alphabetic chars) is an absolute offset;
        # a bed's phrase describes its span ("under the whole line"), not a word to
        # match; otherwise treat the (connective-stripped) remainder as the word ref.
        stripped = _LEADING_CONNECTIVE.sub("", text).strip(" '\"")
        number = _NUMBER.search(text)
        if number is not None and not any(c.isalpha() for c in stripped):
            return Placement(anchor=Anchor.absolute, onset=float(number.group()))
        ref = None if is_bed else (stripped or None)
    else:
        ref = quoted.group(1).strip() or None
    if is_bed:
        anchor = Anchor.sentence
    elif layer is Layer.stinger:
        anchor = Anchor.scene
    else:
        anchor = Anchor.word
    return Placement(anchor=anchor, ref=ref)


def match_word(
    ref: Optional[str], word_timeline: "list[dict]"
) -> "tuple[Optional[dict], MatchKind]":
    """Return the ``word_timeline`` entry best matching ``ref`` and how it matched (#263).

    The one word resolver every anchor goes through, cheapest and surest first (earliest
    occurrence wins at each step): the phrase's first token **exactly**; else a word
    sharing its **stem** (:func:`_is_stem_match`); else the closest word by lexical
    (``difflib``) ratio over any token, among words at least
    :data:`FUZZY_MIN_LENGTH_SHARE` of its length (**fuzzy**, which can be a false match).
    ``(None, MatchKind.fallback)`` when nothing is close or ``ref`` is empty.

    >>> wt = [{"word": "The"}, {"word": "doors"}, {"word": "slammed."}]
    >>> [(w["word"], k.value) for w, k in (match_word(c, wt) for c in ("door", "slam"))]
    [('doors', 'stem'), ('slammed.', 'stem')]
    >>> match_word("zzzzz", wt)
    (None, <MatchKind.fallback: 'fallback'>)
    """
    tokens = [_norm(t) for t in (ref or "").split() if _norm(t)]
    if not tokens or not word_timeline:
        return None, MatchKind.fallback
    normed = [(_norm(w.get("word", "")), w) for w in word_timeline]
    head = tokens[0]
    for nw, w in normed:
        if nw == head:
            return w, MatchKind.exact
    for nw, w in normed:
        if nw and _is_stem_match(head, nw):
            return w, MatchKind.stem
    best, best_ratio = None, 0.0
    for token in tokens:
        for nw, w in normed:
            if not nw or len(nw) < FUZZY_MIN_LENGTH_SHARE * len(token):
                continue
            ratio = difflib.SequenceMatcher(None, token, nw).ratio()
            if ratio > best_ratio:
                best, best_ratio = w, ratio
    if best_ratio >= FUZZY_MIN_RATIO:
        return best, MatchKind.fuzzy
    return None, MatchKind.fallback


def nearest_word(ref: Optional[str], word_timeline: "list[dict]") -> Optional[dict]:
    """The ``word_timeline`` entry best matching ``ref`` (see :func:`match_word`), or ``None``."""
    return match_word(ref, word_timeline)[0]


def _is_stem_match(cue: str, word: str) -> bool:
    """Whether the spoken ``word`` and the ``cue`` share a stem long enough to mean it.

    The spoken word may be the cue's stem at either end (``gun`` for ``gunshot``,
    ``steps`` for ``footsteps``) once it has :data:`PREFIX_MIN_CHARS` letters; as the
    cue's tail it must also leave a head that long, since English inflects at the end,
    so a tail match is a compound (``foot|steps``), never ``th|under``. A cue
    shorter than the word must start it and hold :data:`PREFIX_MIN_SHARE` of it (an
    inflection, ``slam`` for ``slammed``), so a short cue never claims a longer word.

    >>> _is_stem_match("slam", "slammed"), _is_stem_match("gunshot", "gun")
    (True, True)
    >>> _is_stem_match("footsteps", "steps"), _is_stem_match("apple", "a"), _is_stem_match("car", "carpets")
    (True, False, False)
    >>> _is_stem_match("thunder", "under")
    False
    """
    if len(word) <= len(cue):
        is_tail = cue.endswith(word) and len(cue) - len(word) >= PREFIX_MIN_CHARS
        return len(word) >= PREFIX_MIN_CHARS and (cue.startswith(word) or is_tail)
    return (
        word.startswith(cue)
        and len(cue) >= PREFIX_MIN_CHARS
        and len(cue) >= PREFIX_MIN_SHARE * len(word)
    )


def _segment_sentences(
    word_timeline: "list[dict]", *, gap_s: float = SEGMENT_GAP_S
) -> "list[list[dict]]":
    """Group the ``word_timeline`` into sentence segments (pure, report 06 §2.4).

    A new segment starts when the inter-word gap exceeds ``gap_s`` or the previous
    word ended a sentence (``.!?``).
    """
    segments: "list[list[dict]]" = []
    current: "list[dict]" = []
    prev_end: Optional[float] = None
    prev_word = ""
    for w in word_timeline:
        gap = None if prev_end is None else float(w.get("start", 0.0)) - prev_end
        boundary = current and (
            (gap is not None and gap > gap_s)
            or (bool(prev_word) and prev_word[-1] in _SENTENCE_END)
        )
        if boundary:
            segments.append(current)
            current = []
        current.append(w)
        prev_end = float(w.get("end", w.get("start", 0.0)))
        prev_word = str(w.get("word", ""))
    if current:
        segments.append(current)
    return segments


def _span_onset(
    ref: Optional[str], word_timeline: "list[dict]"
) -> "tuple[float, float, MatchKind]":
    """Return the ``(start, end, match_kind)`` of the sentence span ``ref`` sits in.

    With no ``ref`` (a bed with no cue) the span is the whole narration by design
    (``absolute``); with an unmatched ``ref`` it is the whole narration as a ``fallback``.
    """
    if not word_timeline:
        return 0.0, 0.0, (MatchKind.absolute if not ref else MatchKind.fallback)
    whole = (
        float(word_timeline[0].get("start", 0.0)),
        float(word_timeline[-1].get("end", word_timeline[-1].get("start", 0.0))),
    )
    if not ref:
        return (*whole, MatchKind.absolute)
    w, kind = match_word(ref, word_timeline)
    if w is None:
        return (*whole, kind)
    for seg in _segment_sentences(word_timeline):
        if any(sw is w for sw in seg):
            return (
                float(seg[0].get("start", 0.0)),
                float(seg[-1].get("end", seg[-1].get("start", 0.0))),
                kind,
            )
    return (*whole, kind)


def _apply_pre_roll(onset: float, pre_roll: float) -> float:
    """Shift ``onset`` earlier by ``pre_roll``, clamped at 0 (report 06 §2.4)."""
    return max(0.0, onset - pre_roll)


def _snap_to_pause(
    onset: float, word_timeline: "list[dict]", *, radius_s: float = SEGMENT_GAP_S
) -> float:
    """Snap ``onset`` to the nearest inter-word pause within ``radius_s`` (avoids masking speech).

    Returns ``onset`` unchanged when no pause falls within the radius. Pure and
    optional — not applied by :func:`resolve_anchor` unless requested.
    """
    best, best_dist = onset, radius_s
    for a, b in zip(word_timeline, word_timeline[1:]):
        gap_mid = (float(a.get("end", 0.0)) + float(b.get("start", 0.0))) / 2.0
        dist = abs(gap_mid - onset)
        if dist < best_dist:
            best, best_dist = gap_mid, dist
    return best


def resolve_placement(
    placement: Placement,
    word_timeline: "list[dict]",
    *,
    snap_pauses: bool = False,
) -> Placement:
    """Resolve a :class:`Placement` against the ``word_timeline`` — a NEW placement.

    Dispatches on ``placement.anchor`` (report 06 §2.4): ``absolute`` uses the
    stored offset; ``word`` fires on the trigger word; ``sentence`` spans its
    sentence (filling ``duration`` when unset — beds loop to fill it); ``scene`` /
    ``paragraph`` land on the boundary. ``pre_roll`` is then subtracted (clamped at
    0), and — when ``snap_pauses`` — the onset snaps to the nearest inter-word gap.
    ``match_kind`` records how the anchor matched (:class:`~foley.base.MatchKind`): a
    cue with no word timings, or that matched no word, is a ``fallback`` at its stored
    onset (word) or the whole narration (span); a cue-less span is ``absolute``.

    Args:
        placement: The symbolic placement to resolve.
        word_timeline: The forced-aligned ``[{'word','start','end'}, ...]``.
        snap_pauses: If ``True``, snap the resolved onset to the nearest pause.

    Returns:
        A copy with ``onset`` (seconds), ``duration`` (filled only for a span anchor
        whose ``duration`` was unset) and ``match_kind`` resolved.
    """
    duration = placement.duration
    names_no_word = placement.anchor is not Anchor.word and not placement.ref
    if placement.anchor is Anchor.absolute or (names_no_word and not word_timeline):
        onset, kind = placement.onset, MatchKind.absolute
    elif not word_timeline:
        onset, kind = placement.onset, MatchKind.fallback
    elif placement.anchor is Anchor.word:
        w, kind = match_word(placement.ref, word_timeline)
        onset = float(w["start"]) if w else placement.onset
    else:  # sentence span, or scene / paragraph boundary (the span's first word)
        onset, end, kind = _span_onset(placement.ref, word_timeline)
        if placement.anchor is Anchor.sentence and duration is None:
            duration = max(0.0, end - onset)
    onset = _apply_pre_roll(onset, placement.pre_roll)
    if snap_pauses and word_timeline:
        onset = _snap_to_pause(onset, word_timeline)
    return replace(placement, onset=onset, duration=duration, match_kind=kind)


def resolve_anchor(
    placement: Placement,
    word_timeline: "list[dict]",
    *,
    snap_pauses: bool = False,
) -> "tuple[float, Optional[float]]":
    """Resolve a :class:`Placement` to ``(onset_seconds, duration_seconds_or_None)``.

    The tuple view of :func:`resolve_placement` (which also says how it matched).
    """
    resolved = resolve_placement(placement, word_timeline, snap_pauses=snap_pauses)
    return resolved.onset, resolved.duration
