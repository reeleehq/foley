"""Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).

Staged precedence, highest wins (report 04 §5.3, [11 §3.1] — normalize
heterogeneous labels onto UCS via mapping/synonym tables):

    filename-parse  >  declared CatID  >  keyword/synonym  >  audioset-map  >  none

A *declared* CatID is one the file states about itself (the iXML ``CATID`` of a pro
pack, :mod:`foley.embedded_metadata`); like a filename's, it counts only when the
table knows it.

Matching is word-boundary aware (so ``"rain"`` matches "heavy rain" but not
"brainstorm"), a subcategory hit outranks a category-name hit, and multi-word
phrases outrank single tokens — with a deterministic table-order final tiebreak.
The always-available default is this stdlib :class:`KeywordResolver`; a richer
CLAP zero-shot resolver (embed once, argmax over UCS label prompts, report
03 Part 2) can be dropped in behind the same :class:`TaxonomyResolver` protocol.
"""

from __future__ import annotations

import math
from typing import Optional, Protocol, Sequence, runtime_checkable

from .audioset import default_audioset_ucs_map
from .model import (
    GENERIC_SUBCATEGORIES,
    NON_SOUND_CATEGORIES,
    AudioSetUcsMap,
    CatIdResolution,
    UcsTable,
)
from .text import stem, terms
from .ucs import default_ucs_table, parse_ucs_name

# Coarse per-stage confidence bands.
_CONF_FILENAME: float = 1.0
_CONF_DECLARED: float = 1.0  # the file's own metadata names its CatID
_CONF_KEYWORD_CONFIDENT: float = (
    0.8  # strong hit (subcategory/synonym) on a verified row
)
_CONF_KEYWORD_APPROX: float = 0.6  # strong hit on an approximate (confident=False) row
_CONF_KEYWORD_WEAK: float = 0.4  # category-name-only brush (no subcategory/synonym hit)
_CONF_AUDIOSET: float = 0.5

#: English function words: dropped from both sides before matching, so a phrase
#: matches across them (``"rain on window"`` in "rain on a window").
DEFAULT_STOP_WORDS: frozenset = frozenset(
    stem(w)
    for w in (
        "a an the and or but if of in on at to for from by with without into onto "
        "over under up down out off about as is are was were be been being am do does "
        "did has have had it its this that these those there here he she they we you "
        "i me him her them us my your his our their who what which when where why how "
        "not no nor so than then too very can could will would should may might must "
        "just also only all any some each every few more most other such own same"
    ).split()
)

#: Common narration words that the UCS master also lists as a subcategory or
#: synonym (``quiet`` is ``CRWDQuiet``, ``release`` an ``AIR`` synonym): they count
#: inside a multi-word term (``"glass break"``, ``"room tone"``), never alone
#: (``"take a break"``).
DEFAULT_AMBIGUOUS_WORDS: frozenset = frozenset(
    stem(w)
    for w in (
        "break shot hit bang run beat arc handle general misc sound tone quiet open "
        "release work little long big blue set hold catch drop fall person meeting "
        "day night time way thing place side part piece light heavy small large"
    ).split()
)

#: Categories the keyword stage never picks (a filename or declared CatID still may).
DEFAULT_SKIP_CATEGORIES: frozenset = NON_SOUND_CATEGORIES

#: Base weight of a matched term, by where it came from; a multi-word term adds
#: :data:`_PHRASE_BONUS` per extra word.
_KIND_WEIGHT = {"subcategory": 3.0, "synonym": 2.0, "category": 1.5}
_PHRASE_BONUS = 1.0


def _search_fields(tags: Sequence[str], caption: Optional[str]) -> "list[tuple]":
    """Per-field stemmed words (each tag, then the caption).

    Kept as separate fields so a multi-word phrase can only match *within* one
    field: a phrase must never straddle a tag<->caption (or tag<->tag) boundary
    (e.g. tags=['glass'] + caption='break room' must NOT match 'glass break').
    """
    texts = [t for t in (tags or ()) if t] + ([caption] if caption else [])
    return [f for f in (terms(t) for t in texts) if f]


def _contains(field_words: tuple, words: tuple) -> bool:
    n = len(words)
    return any(field_words[i : i + n] == words for i in range(len(field_words) - n + 1))


def _term_weight(term, row_count: int) -> float:
    """A matched term's weight: its kind's, a phrase bonus, and less if many rows share it.

    A subcategory or category is the row's own name, so it keeps its full weight; a
    synonym shared by ``n`` rows is divided by ``sqrt(n)`` (``"car"`` is a synonym of
    32 rows, ``"doorknob"`` of one).
    """
    weight = _KIND_WEIGHT[term.kind] + _PHRASE_BONUS * (len(term.words) - 1)
    return weight / math.sqrt(row_count) if term.kind == "synonym" else weight


def _keyword_stage(
    tags: Sequence[str],
    caption: Optional[str],
    table: UcsTable,
    *,
    stop_words: frozenset,
    ambiguous_words: frozenset,
    skip_categories: frozenset,
) -> "Optional[tuple]":
    """The best keyword match: ``(row, matched_terms, strong)``, or ``None``.

    ``strong`` means a subcategory or synonym matched; a category-name-only match is
    weak evidence, and lands on the category's generic row when it has one.
    """
    fields = _search_fields(tags, caption)
    if not fields:
        return None

    def content(words):  # a phrase matches across stop words: "rain on a window"
        return tuple(w for w in words if w not in stop_words)

    content_fields = [content(f) for f in fields]
    index = table.term_index
    scores: dict[str, list] = {}  # catid -> [score, matched, strong]
    for word in {w for f in fields for w in f}:
        for term in index.by_first_word.get(word, ()):
            words = content(term.words)
            if not words or (len(words) == 1 and words[0] in ambiguous_words):
                continue
            if not any(_contains(f, words) for f in content_fields):
                continue
            if term.kind == "subcategory" and words[0] in GENERIC_SUBCATEGORIES:
                continue
            row = table.by_catid[term.catid]
            if row.category in skip_categories:
                continue
            entry = scores.setdefault(term.catid, [0.0, [], False])
            entry[0] += _term_weight(term, index.row_count[term.words])
            text = " ".join(term.words)
            if text not in entry[1]:
                entry[1].append(text)
            entry[2] = entry[2] or term.kind != "category"
    if not scores:
        return None
    order = {catid: i for i, catid in enumerate(table.order)}

    def rank(catid):
        score, _, strong = scores[catid]
        return (
            round(score, 6),
            strong,
            table.by_catid[catid].is_generic,
            -order[catid],
        )

    best = max(scores, key=rank)
    score, matched, strong = scores[best]
    return table.by_catid[best], matched, strong


def _audioset_stage(
    labels: Sequence[str], audioset_map: AudioSetUcsMap, table: UcsTable
) -> "Optional[tuple]":
    for label in labels or ():
        catid = audioset_map.resolve(label)
        if catid:
            row = table.get(catid)
            if row is not None:
                return row, [label]
    return None


def resolve_catid(
    *,
    tags: Sequence[str] = (),
    caption: Optional[str] = None,
    audioset_labels: Sequence[str] = (),
    filename: Optional[str] = None,
    catid: Optional[str] = None,
    table: Optional[UcsTable] = None,
    audioset_map: Optional[AudioSetUcsMap] = None,
    stop_words: frozenset = DEFAULT_STOP_WORDS,
    ambiguous_words: frozenset = DEFAULT_AMBIGUOUS_WORDS,
    skip_categories: frozenset = DEFAULT_SKIP_CATEGORIES,
) -> CatIdResolution:
    """Resolve inputs to a best UCS CatID by the staged precedence.

    Args:
        tags: Free tags on the sound.
        caption: Free-text caption/description.
        audioset_labels: AudioSet MIDs or names (e.g. from PANNs).
        filename: Optional UCS-style filename/path (its token-0 CatID wins if
            recognized).
        catid: Optional CatID the sound declares (e.g. its iXML ``CATID``); wins
            over keywords when the table knows it, else it is ignored.
        table: UCS table (defaults to :func:`default_ucs_table`).
        audioset_map: AudioSet->UCS map (defaults to
            :func:`~foley.index.taxonomy.audioset.default_audioset_ucs_map`).
        stop_words: Stemmed words dropped from both sides before matching
            (default :data:`DEFAULT_STOP_WORDS`).
        ambiguous_words: Stemmed words that match only inside a multi-word term,
            never alone (default :data:`DEFAULT_AMBIGUOUS_WORDS`).
        skip_categories: UCS categories the keyword stage never picks (default
            :data:`DEFAULT_SKIP_CATEGORIES`; a filename or declared CatID still may).

    Returns:
        A :class:`~foley.index.taxonomy.model.CatIdResolution` (falsy when
        nothing resolved).
    """
    table = table or default_ucs_table()
    audioset_map = audioset_map or default_audioset_ucs_map()

    if filename:
        name = parse_ucs_name(filename, table=table)
        if name is not None:
            return CatIdResolution(
                catid=name.catid,
                category=name.category,
                subcategory=name.subcategory,
                source="filename",
                confidence=_CONF_FILENAME,
                matched_terms=[name.catid],
            )

    row = table.get(catid) if catid else None
    if row is not None:
        return CatIdResolution(
            catid=row.catid,
            category=row.category,
            subcategory=row.subcategory,
            source="metadata",
            confidence=_CONF_DECLARED,
            matched_terms=[catid],
        )

    kw = _keyword_stage(
        tags,
        caption,
        table,
        stop_words=stop_words,
        ambiguous_words=ambiguous_words,
        skip_categories=skip_categories,
    )
    if kw is not None:
        row, matched, strong = kw
        if not strong:  # category-name-only brush — weak evidence
            conf = _CONF_KEYWORD_WEAK
        else:
            conf = _CONF_KEYWORD_CONFIDENT if row.confident else _CONF_KEYWORD_APPROX
        return CatIdResolution(
            catid=row.catid,
            category=row.category,
            subcategory=row.subcategory,
            source="keyword",
            confidence=conf,
            matched_terms=matched,
        )

    ash = _audioset_stage(audioset_labels, audioset_map, table)
    if ash is not None:
        row, matched = ash
        return CatIdResolution(
            catid=row.catid,
            category=row.category,
            subcategory=row.subcategory,
            source="audioset",
            confidence=_CONF_AUDIOSET,
            matched_terms=matched,
        )

    return CatIdResolution()


@runtime_checkable
class TaxonomyResolver(Protocol):
    """Resolve a :class:`~foley.base.SoundRecord` to a UCS CatID."""

    def resolve(self, record) -> CatIdResolution:
        """Return the CatID resolution for ``record``."""


class KeywordResolver:
    """The default stdlib resolver — staged keyword/synonym/AudioSet resolution.

    Zero heavy dependencies. Bind a different :class:`TaxonomyResolver` (e.g. a
    future CLAP zero-shot resolver) by keyword injection to upgrade quality.
    """

    def __init__(
        self,
        *,
        table: Optional[UcsTable] = None,
        audioset_map: Optional[AudioSetUcsMap] = None,
        stop_words: frozenset = DEFAULT_STOP_WORDS,
        ambiguous_words: frozenset = DEFAULT_AMBIGUOUS_WORDS,
        skip_categories: frozenset = DEFAULT_SKIP_CATEGORIES,
    ):
        """Create a resolver over the given (or default) UCS table + AudioSet map.

        ``stop_words``, ``ambiguous_words`` and ``skip_categories`` are as in :func:`resolve_catid`.
        """
        self.table = table or default_ucs_table()
        self.audioset_map = audioset_map or default_audioset_ucs_map()
        self.stop_words = stop_words
        self.ambiguous_words = ambiguous_words
        self.skip_categories = skip_categories

    def resolve(self, record) -> CatIdResolution:
        """Resolve a :class:`~foley.base.SoundRecord`'s tags/caption/labels/uri."""
        return resolve_catid(
            tags=getattr(record, "tags", ()) or (),
            caption=getattr(record, "caption", None),
            audioset_labels=getattr(record, "audioset_labels", ()) or (),
            filename=getattr(record, "uri", None),
            table=self.table,
            audioset_map=self.audioset_map,
            stop_words=self.stop_words,
            ambiguous_words=self.ambiguous_words,
            skip_categories=self.skip_categories,
        )
