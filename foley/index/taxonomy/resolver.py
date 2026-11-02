"""Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).

Staged precedence, highest wins (report 04 §5.3, [11 §3.1] — normalize
heterogeneous labels onto UCS via mapping/synonym tables):

    filename-parse  >  keyword/synonym  >  audioset-map  >  none

Matching is word-boundary aware (so ``"rain"`` matches "heavy rain" but not
"brainstorm"), a subcategory hit outranks a category-name hit, and multi-word
phrases outrank single tokens — with a deterministic table-order final tiebreak.
The always-available default is this stdlib :class:`KeywordResolver`; a richer
CLAP zero-shot resolver (embed once, argmax over UCS label prompts, report
03 Part 2) can be dropped in behind the same :class:`TaxonomyResolver` protocol.
"""

from __future__ import annotations

import re
from typing import Optional, Protocol, Sequence, runtime_checkable

from .audioset import default_audioset_ucs_map
from .model import AudioSetUcsMap, CatIdResolution, UcsTable
from .ucs import default_ucs_table, parse_ucs_name

# Coarse per-stage confidence bands.
_CONF_FILENAME: float = 1.0
_CONF_KEYWORD_CONFIDENT: float = (
    0.8  # strong hit (subcategory/synonym) on a verified row
)
_CONF_KEYWORD_APPROX: float = 0.6  # strong hit on an approximate (confident=False) row
_CONF_KEYWORD_WEAK: float = 0.4  # category-name-only brush (no subcategory/synonym hit)
_CONF_AUDIOSET: float = 0.5

# Common English words that also happen to be a UCS subcategory/synonym token; they
# are too ambiguous to resolve a CatID on their own, so they match ONLY inside a
# multi-word phrase (e.g. "glass break"), never as a bare single token ("take a
# break"). Prevents high-scoring false positives on ordinary narration.
_AMBIGUOUS_SINGLE_TOKENS = frozenset(
    {"break", "shot", "hit", "bang", "run", "beat", "arc", "handle", "general"}
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    """Lowercase and collapse non-alphanumerics to single spaces."""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _search_fields(tags: Sequence[str], caption: Optional[str]) -> "list[str]":
    """Per-field normalized strings (each tag, then the caption).

    Kept as separate fields so a multi-word phrase can only match *within* one
    field — a bigram must never straddle a tag<->caption (or tag<->tag) boundary
    (e.g. tags=['glass'] + caption='break room' must NOT match 'glass break').
    """
    fields = [_normalize(t) for t in (tags or ()) if t]
    if caption:
        fields.append(_normalize(caption))
    return [f for f in fields if f]


def _keyword_stage(
    tags: Sequence[str], caption: Optional[str], table: UcsTable
) -> "Optional[tuple]":
    fields = _search_fields(tags, caption)
    if not fields:
        return None
    padded_fields = [f" {f} " for f in fields]
    tokens: set[str] = set()
    for f in fields:
        tokens.update(f.split())

    def hit(phrase: str) -> bool:
        p = _normalize(phrase)
        if not p:
            return False
        if " " in p:  # multi-word: word-boundary substring within a single field
            needle = f" {p} "
            return any(needle in pf for pf in padded_fields)
        if p in _AMBIGUOUS_SINGLE_TOKENS:  # too ambiguous to match bare
            return False
        return p in tokens  # single token: exact word (across fields)

    # ``strong`` = a subcategory or synonym matched (real evidence); a bare
    # category-name brush is ``weak`` and gets a lower reported confidence.
    best = None  # ((score, -order_index), row, matched_terms, strong)
    for order_index, catid in enumerate(table.order):
        row = table.by_catid[catid]
        matched: list[str] = []
        score = 0.0
        strong = False
        sub = row.subcategory.lower()
        if sub and sub != "general" and hit(sub):
            score += 3.0 + sub.count(" ")
            matched.append(sub)
            strong = True
        for syn in row.synonyms:
            if hit(syn):
                score += 2.0 + syn.count(" ")
                matched.append(syn)
                strong = True
        cat = row.category.lower()
        if cat not in matched and hit(cat):
            score += 0.5
            matched.append(cat)
        if score <= 0:
            continue
        key = (score, -order_index)
        if best is None or key > best[0]:
            best = (key, row, matched, strong)
    if best is None:
        return None
    return best[1], best[2], best[3]


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
    table: Optional[UcsTable] = None,
    audioset_map: Optional[AudioSetUcsMap] = None,
) -> CatIdResolution:
    """Resolve inputs to a best UCS CatID by the staged precedence.

    Args:
        tags: Free tags on the sound.
        caption: Free-text caption/description.
        audioset_labels: AudioSet MIDs or names (e.g. from PANNs).
        filename: Optional UCS-style filename/path (its token-0 CatID wins if
            recognized).
        table: UCS table (defaults to :func:`default_ucs_table`).
        audioset_map: AudioSet->UCS map (defaults to
            :func:`~foley.index.taxonomy.audioset.default_audioset_ucs_map`).

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

    kw = _keyword_stage(tags, caption, table)
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
    ):
        """Create a resolver over the given (or default) UCS table + AudioSet map."""
        self.table = table or default_ucs_table()
        self.audioset_map = audioset_map or default_audioset_ucs_map()

    def resolve(self, record) -> CatIdResolution:
        """Resolve a :class:`~foley.base.SoundRecord`'s tags/caption/labels/uri."""
        return resolve_catid(
            tags=getattr(record, "tags", ()) or (),
            caption=getattr(record, "caption", None),
            audioset_labels=getattr(record, "audioset_labels", ()) or (),
            filename=getattr(record, "uri", None),
            table=self.table,
            audioset_map=self.audioset_map,
        )
