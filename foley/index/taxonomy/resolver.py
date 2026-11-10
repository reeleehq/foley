"""Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).

Staged precedence, highest wins (report 04 §5.3, [11 §3.1] — normalize
heterogeneous labels onto UCS via mapping/synonym tables):

    filename-parse  >  declared CatID  >  keyword/synonym  >  audioset-map  >  none

A *declared* CatID is one the file states about itself (the iXML ``CATID`` of a pro
pack, :mod:`foley.embedded_metadata`); like a filename's, it counts only when the
table knows it. A keyword match weaker than an AudioSet-map hit (its band is below
:attr:`MatchPolicy.audioset_confidence`) yields to one.

The keyword stage, in three pure steps over the table's
:class:`~foley.index.taxonomy.text.TermIndex` (built once per table):

1. **collect** — each term (subcategory, category name, synonym) found in one field
   of the input, word-boundary aware and across function words, becomes a
   :class:`Hit`; the hits of one CatID fold into its :class:`Evidence`;
2. **pick** — the highest score wins (one word counts once, whatever it hits); on a
   tie, the stronger evidence, with a category name as strong as a subcategory,
   then the category's generic (``GENERAL``/``MISC``) row, then table order;
3. **band** — the confidence says how much evidence there is
   (:meth:`MatchPolicy.band`), not which row won.

Everything tunable is one frozen :class:`MatchPolicy` (``policy=``). The
always-available default is this stdlib :class:`KeywordResolver`; a richer CLAP
zero-shot resolver (embed once, argmax over UCS label prompts, report 03 Part 2) can
be dropped in behind the same :class:`TaxonomyResolver` protocol.
"""

from __future__ import annotations

import math
import weakref
from collections import defaultdict
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Protocol, Sequence, runtime_checkable

from ...analysis import tokenize
from .audioset import default_audioset_ucs_map
from .model import (
    NON_SOUND_CATEGORIES,
    AudioSetUcsMap,
    CatIdResolution,
    UcsRow,
    UcsTable,
)
from .text import TermIndex, build_term_index
from .ucs import default_ucs_table, parse_ucs_name

#: A filename's or the file's own metadata's CatID: the sound says what it is.
STATED_CONFIDENCE: float = 1.0

#: English function words, dropped from both sides before matching, so a phrase
#: matches across them (``"rain on window"`` in "rain on a window"). Particles that
#: carry sound meaning (``up``, ``down``, ``out``, ``off``, ``over``: "wind up" is a
#: toy, "the wind picked up" is weather) are not here but in the ambiguous words.
DEFAULT_STOP_WORDS: frozenset = frozenset(
    (
        "a an the and or but if of in on at to for from by with without into onto "
        "under about as is are was were be been being am do does did has have had it "
        "its this that these those there here he she they we you i me him her them us "
        "my your his our their who what which when where why how not no nor so than "
        "then too very can could will would should may might must just also only all "
        "any some each every few more most other such own same"
    ).split()
)

#: Common narration words that the UCS master also lists as a subcategory or
#: synonym (``quiet`` is ``CRWDQuiet``, ``release`` an ``AIR`` synonym): they count
#: inside a multi-word term (``"glass break"``, ``"wind up"``), never alone
#: (``"take a break"``, ``"the price went up"``).
DEFAULT_AMBIGUOUS_WORDS: frozenset = frozenset(
    (
        "break shot hit bang run beat arc handle general misc sound tone quiet open "
        "release work little long big blue set hold catch drop fall person meeting "
        "day night time way thing place side part piece light heavy small large "
        "up down out off over"
    ).split()
)

#: Base weight of a matched term, by where it came from. A category name is its
#: rows' own name, as strong as a subcategory.
DEFAULT_KIND_WEIGHTS: "Mapping[str, float]" = MappingProxyType(
    {"subcategory": 3.0, "category": 3.0, "synonym": 2.0}
)

#: Evidence strengths, strongest first (indices into :attr:`MatchPolicy.bands`).
STRONG, SINGLE, WEAK = range(3)


@dataclass(frozen=True)
class MatchPolicy:
    """How the keyword stage matches, ranks and bands (one strategy object).

    Attributes:
        stop_words: Words dropped from both sides before matching.
        ambiguous_words: Words that match only inside a multi-word term.
        skip_categories: UCS categories the keyword stage never picks (a filename or
            declared CatID still may).
        kind_weights: Base weight of a hit by term kind (``subcategory``,
            ``category``, ``synonym``).
        phrase_bonus: Added per content word past the first of a multi-word term.
        strong_confidence: Band of strong evidence: a subcategory hit, a multi-word
            phrase, or two distinct content words on the row (a category name plus
            another word counts).
        single_confidence: Band of one content word that only this row lists as a
            synonym.
        weak_confidence: Band of a brush: a category name alone, or a synonym many
            rows share. A ``confident=False`` row drops one band (floored here).
        audioset_confidence: Band of an AudioSet-map hit; a weaker keyword match
            yields to one.
    """

    stop_words: frozenset = DEFAULT_STOP_WORDS
    ambiguous_words: frozenset = DEFAULT_AMBIGUOUS_WORDS
    skip_categories: frozenset = NON_SOUND_CATEGORIES
    kind_weights: "Mapping[str, float]" = field(default=DEFAULT_KIND_WEIGHTS)
    phrase_bonus: float = 1.0
    strong_confidence: float = 0.8
    single_confidence: float = 0.6
    weak_confidence: float = 0.4
    audioset_confidence: float = 0.5

    def __post_init__(self):
        if not (
            STATED_CONFIDENCE
            >= self.strong_confidence
            >= self.single_confidence
            >= self.weak_confidence
            >= 0
        ):
            raise ValueError(
                "confidence bands must descend within [0, 1]: strong >= single >= weak"
            )
        missing = {"subcategory", "category", "synonym"} - set(self.kind_weights)
        if missing:
            raise ValueError(f"kind_weights lacks {sorted(missing)}")

    @property
    def bands(self) -> "tuple[float, float, float]":
        """The keyword bands, by :data:`STRONG`, :data:`SINGLE`, :data:`WEAK`."""
        return (self.strong_confidence, self.single_confidence, self.weak_confidence)

    def band(self, strength: int, *, confident: bool = True) -> float:
        """The band of evidence of ``strength``; an unverified row drops one."""
        return self.bands[min(strength + (not confident), WEAK)]


DEFAULT_MATCH_POLICY = MatchPolicy()

#: The least confidence worth writing onto a record: an AudioSet-map hit's. A weak
#: keyword brush (a category name alone, a synonym many rows share) is below it.
RECORD_MIN_CONFIDENCE: float = DEFAULT_MATCH_POLICY.audioset_confidence


# ---------------------------------------------------------------------------
# the term index, cached per table (the table stays plain data)
# ---------------------------------------------------------------------------

_TERM_INDEXES: "weakref.WeakKeyDictionary[UcsTable, TermIndex]" = (
    weakref.WeakKeyDictionary()
)


def term_index(table: UcsTable) -> TermIndex:
    """The :class:`~.text.TermIndex` of ``table``, built once per table."""
    index = _TERM_INDEXES.get(table)
    if index is None:
        index = _TERM_INDEXES[table] = build_term_index(table)
    return index


# ---------------------------------------------------------------------------
# the keyword stage: collect -> pick -> band
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """One term of a row found in the input.

    ``words`` are the term's content lemmas (stop words dropped); ``shared_by`` is how
    many rows list the term.
    """

    catid: str
    kind: str
    text: str
    words: "tuple[str, ...]"
    weight: float
    shared_by: int


@dataclass(frozen=True)
class Evidence:
    """Everything the input says for one CatID: the folded :class:`Hit` s."""

    catid: str
    score: float
    matched: "tuple[str, ...]"
    words: frozenset
    kinds: frozenset
    phrase: bool
    unique_synonym: bool

    @property
    def strength(self) -> int:
        """How much the input says: :data:`STRONG`, :data:`SINGLE` or :data:`WEAK`.

        A category name alone is a brush (:data:`WEAK`): it says which category,
        not which row. See :class:`MatchPolicy` for the bands.
        """
        if "subcategory" in self.kinds or self.phrase or len(self.words) > 1:
            return STRONG
        return SINGLE if self.unique_synonym else WEAK

    @property
    def rank_strength(self) -> int:
        """:attr:`strength` for ranking, where a category name is as strong as a
        subcategory: it is the row's own name (``"glass"`` is the ``GLASS``
        category before it is ``DOORGlas``'s subcategory)."""
        return STRONG if "category" in self.kinds else self.strength


def _fields(
    tags: Sequence[str], caption: Optional[str], index: TermIndex, policy: MatchPolicy
) -> "list[tuple[frozenset, ...]]":
    """Per tag, then the caption: the lemmas each content word can be.

    Kept apart so a multi-word phrase matches only *within* one text: tags=['glass']
    plus caption='break room' must not match 'glass break'. An unknown word keeps
    its place (as no lemma), so no phrase reaches across it.
    """
    texts = [t for t in (tags or ()) if t] + ([caption] if caption else [])
    fields = [
        tuple(index.lemmas(w) for w in tokenize(t) if w not in policy.stop_words)
        for t in texts
    ]
    return [f for f in fields if f]


def _contains(field: "tuple[frozenset, ...]", words: "tuple[str, ...]") -> bool:
    """Whether ``words`` (lemmas) occur one after another in ``field``."""
    n = len(words)
    return any(
        all(w in field[i + j] for j, w in enumerate(words))
        for i in range(len(field) - n + 1)
    )


def _hits(
    fields: "list[tuple[frozenset, ...]]",
    table: UcsTable,
    index: TermIndex,
    policy: MatchPolicy,
) -> "Iterable[Hit]":
    """Every term of ``table`` found in one of ``fields``, as a :class:`Hit`.

    A term is looked for only in a field holding all its content lemmas, so a field
    costs the terms its own words index.
    """
    ambiguous = {l for w in policy.ambiguous_words for l in index.lemmas(w)}

    def content(term) -> "Optional[tuple[str, ...]]":  # None: never matches alone
        row = table.by_catid[term.catid]
        if row.category in policy.skip_categories:
            return None
        if term.kind == "subcategory" and row.is_generic:
            return None  # GENERAL / MISC name no sound
        words = tuple(
            l for w, l in zip(term.words, term.lemmas) if w not in policy.stop_words
        )
        if not words or (len(words) == 1 and words[0] in ambiguous):
            return None
        return words

    found: dict[int, tuple] = {}  # id(term) -> (term, content); a term counts once
    for f in fields:
        present = frozenset().union(*f)
        for lemma in present:
            for term in index.by_lemma.get(lemma, ()):
                if id(term) in found:
                    continue
                words = content(term)
                if words and present.issuperset(words) and _contains(f, words):
                    found[id(term)] = (term, words)
    for term, words in found.values():
        shared_by = index.row_count[term.lemmas]
        weight = policy.kind_weights[term.kind] + policy.phrase_bonus * (len(words) - 1)
        if term.kind == "synonym":  # "car" is a synonym of 32 rows, "doorknob" of one
            weight /= math.sqrt(shared_by)
        yield Hit(term.catid, term.kind, term.text, words, weight, shared_by)


def _score(hits: "Sequence[Hit]") -> float:
    """Every phrase hit's weight, plus each single word's best hit.

    One word is one piece of evidence: ``"vehicles"`` naming the ``VEHICLES``
    category does not count again because a row also lists ``vehicle`` as a synonym
    (which would carry it past the category's generic row).
    """
    best: dict[str, float] = {}
    for h in hits:
        if len(h.words) == 1:
            best[h.words[0]] = max(best.get(h.words[0], 0.0), h.weight)
    return sum(h.weight for h in hits if len(h.words) > 1) + sum(best.values())


def _evidence(catid: str, hits: "Sequence[Hit]") -> Evidence:
    """Fold one CatID's hits (in a stable order) into its :class:`Evidence`."""
    hits = sorted(hits, key=lambda h: (-h.weight, h.text, h.kind))
    return Evidence(
        catid=catid,
        score=round(_score(hits), 6),
        matched=tuple(dict.fromkeys(h.text for h in hits)),
        words=frozenset(w for h in hits for w in h.words),
        kinds=frozenset(h.kind for h in hits),
        phrase=any(len(h.words) > 1 for h in hits),
        unique_synonym=any(h.kind == "synonym" and h.shared_by == 1 for h in hits),
    )


def _collect(hits: "Iterable[Hit]", table: UcsTable) -> "list[Evidence]":
    """One :class:`Evidence` per CatID that ``hits`` touch.

    A category-name hit sits on its category's representative row (the index lists
    it once); every other row of that category with a hit of its own gets it too.
    """
    by_catid: dict[str, list[Hit]] = defaultdict(list)
    named: dict[str, Hit] = {}  # category -> its name's hit
    for hit in hits:
        by_catid[hit.catid].append(hit)
        if hit.kind == "category":
            named[table.by_catid[hit.catid].category] = hit
    for catid, row_hits in by_catid.items():
        name = named.get(table.by_catid[catid].category)
        if name is not None and name.catid != catid:
            row_hits.append(replace(name, catid=catid))
    return [_evidence(c, hs) for c, hs in by_catid.items()]


def _pick(evidence: "Sequence[Evidence]", table: UcsTable) -> Evidence:
    """The best :class:`Evidence`: score, then :attr:`~Evidence.rank_strength` (a
    shared synonym never beats a named row), then the generic row (a category name
    alone lands on ``GENERAL``/``MISC``), then table order."""
    order = {catid: i for i, catid in enumerate(table.order)}

    def rank(ev: Evidence):
        return (
            ev.score,
            -ev.rank_strength,
            table.by_catid[ev.catid].is_generic,
            -order[ev.catid],
        )

    return max(evidence, key=rank)


def _resolution(
    row: UcsRow, source: str, confidence: float, matched
) -> CatIdResolution:
    return CatIdResolution(
        catid=row.catid,
        category=row.category,
        subcategory=row.subcategory,
        source=source,
        confidence=confidence,
        matched_terms=list(matched),
    )


def keyword_resolution(
    tags: Sequence[str] = (),
    caption: Optional[str] = None,
    *,
    table: Optional[UcsTable] = None,
    policy: MatchPolicy = DEFAULT_MATCH_POLICY,
) -> CatIdResolution:
    """The keyword stage alone: the best row for ``tags``/``caption``, banded.

    >>> keyword_resolution(caption="a heavy wooden door creaks open").catid
    'DOORWood'
    >>> r = keyword_resolution(caption="the wind picked up")
    >>> r.catid, r.confidence
    ('WIND', 0.4)
    """
    table = table if table is not None else default_ucs_table()
    index = term_index(table)
    fields = _fields(tags, caption, index, policy)
    evidence = _collect(_hits(fields, table, index, policy), table)
    if not evidence:
        return CatIdResolution()
    best = _pick(evidence, table)
    row = table.by_catid[best.catid]
    confidence = policy.band(best.strength, confident=row.confident)
    return _resolution(row, "keyword", confidence, best.matched)


def _audioset_resolution(
    labels: Sequence[str],
    audioset_map: AudioSetUcsMap,
    table: UcsTable,
    confidence: float,
) -> CatIdResolution:
    for label in labels or ():
        catid = audioset_map.resolve(label)
        row = table.get(catid) if catid else None
        if row is not None:
            return _resolution(row, "audioset", confidence, [label])
    return CatIdResolution()


def resolve_catid(
    *,
    tags: Sequence[str] = (),
    caption: Optional[str] = None,
    audioset_labels: Sequence[str] = (),
    filename: Optional[str] = None,
    catid: Optional[str] = None,
    table: Optional[UcsTable] = None,
    audioset_map: Optional[AudioSetUcsMap] = None,
    policy: MatchPolicy = DEFAULT_MATCH_POLICY,
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
        policy: How keywords match and band (default :data:`DEFAULT_MATCH_POLICY`;
            vary it with ``dataclasses.replace``).

    Returns:
        A :class:`~foley.index.taxonomy.model.CatIdResolution` (falsy when
        nothing resolved).
    """
    table = table if table is not None else default_ucs_table()

    name = parse_ucs_name(filename, table=table) if filename else None
    if name is not None:
        row = table.by_catid[name.catid]
        return _resolution(row, "filename", STATED_CONFIDENCE, [name.catid])

    row = table.get(catid) if catid else None
    if row is not None:
        return _resolution(row, "metadata", STATED_CONFIDENCE, [catid])

    keyword = keyword_resolution(tags, caption, table=table, policy=policy)
    if keyword and keyword.confidence >= policy.audioset_confidence:
        return keyword
    audioset_map = (
        audioset_map if audioset_map is not None else default_audioset_ucs_map()
    )
    audioset = _audioset_resolution(
        audioset_labels, audioset_map, table, policy.audioset_confidence
    )
    return audioset or keyword


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
        policy: MatchPolicy = DEFAULT_MATCH_POLICY,
    ):
        """Create a resolver over the given (or default) UCS table + AudioSet map.

        ``policy`` is as in :func:`resolve_catid`.
        """
        self.table = table if table is not None else default_ucs_table()
        self.audioset_map = (
            audioset_map if audioset_map is not None else default_audioset_ucs_map()
        )
        self.policy = policy

    def resolve(self, record) -> CatIdResolution:
        """Resolve a :class:`~foley.base.SoundRecord`'s tags/caption/labels/uri."""
        return resolve_catid(
            tags=getattr(record, "tags", ()) or (),
            caption=getattr(record, "caption", None),
            audioset_labels=getattr(record, "audioset_labels", ()) or (),
            filename=getattr(record, "uri", None),
            table=self.table,
            audioset_map=self.audioset_map,
            policy=self.policy,
        )
