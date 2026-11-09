"""Data structures for the UCS/AudioSet taxonomy resolver (stdlib-only).

These are plain, immutable-ish records — the resolver logic lives in
:mod:`~foley.index.taxonomy.ucs`, :mod:`~foley.index.taxonomy.audioset`, and
:mod:`~foley.index.taxonomy.resolver`. Nothing here imports numpy/torch; the
whole taxonomy layer is a pure lookup over dicts (report 04 §5.3 — "taxonomies do
faceting and browse", the CLAP vector does the heavy retrieval).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional


#: Subcategories that name no particular sound (``RAIN``/``GENERAL``, ``AIR``/``MISC``).
GENERIC_SUBCATEGORIES: frozenset = frozenset({"general", "misc"})

#: Categories whose rows are production bookkeeping (``TMARK``, ``WIP``, ``SCNE``),
#: not kinds of sound: a filename may name them, a tagger or keyword match never does.
NON_SOUND_CATEGORIES: frozenset = frozenset({"ARCHIVED"})


@dataclass(frozen=True)
class UcsRow:
    """One Universal Category System entry.

    A ``catid`` (e.g. ``'DOORWood'``) is an OPAQUE key — the category prefix is
    variable-length and not reliably splittable — so ``catid -> (category,
    subcategory)`` is always a table lookup, never a string split (report
    04 §5.2). ``confident=False`` marks an APPROXIMATE CatID reconstructed for the
    seed table; verify it against the UCS master before treating it as
    authoritative.
    """

    catid: str
    category: str
    subcategory: str
    synonyms: tuple[str, ...] = ()
    confident: bool = False
    explanation: str = ""

    @property
    def is_generic(self) -> bool:
        """Whether the subcategory names no particular sound (``GENERAL``, ``MISC``)."""
        return self.subcategory.lower() in GENERIC_SUBCATEGORIES


@dataclass(frozen=True)
class UcsName:
    """Every field of a UCS filename (``foley.index.taxonomy.ucs.parse_ucs_name``).

    ``CatID[-UserCategory]_[VendorCategory-]FXName_CreatorID_SourceID[_UserData].ext``:
    underscores separate the blocks; a hyphen attaches the optional UserCategory to
    the CatID and the optional VendorCategory to the FXName. ``category`` and
    ``subcategory`` come from the table row of ``catid``; a block the name does not
    have is ``None``.
    """

    catid: str
    category: str
    subcategory: str
    fx_name: Optional[str] = None
    creator_id: Optional[str] = None
    source_id: Optional[str] = None
    user_category: Optional[str] = None
    vendor_category: Optional[str] = None
    user_data: Optional[str] = None


@dataclass
class UcsTable:
    """A loaded UCS lookup: by CatID (exact + case-insensitive) and by synonym.

    Attributes:
        by_catid: ``CatID -> UcsRow`` (case-sensitive primary key).
        order: The CatIDs in stable insertion order (deterministic tie-breaking).
    """

    by_catid: dict[str, UcsRow] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    # lower(catid) -> catid, for mixed-case CatIDs only: ``doorwood`` finds
    # ``DOORWood``, but ``rain`` (a word) never finds ``RAIN``.
    _ci_index: dict[str, str] = field(default_factory=dict)

    def get(self, catid: str) -> Optional[UcsRow]:
        """Look up a row by CatID: exact first, then case-insensitive."""
        row = self.by_catid.get(catid)
        if row is not None:
            return row
        canonical = self._ci_index.get(catid.lower())
        return self.by_catid.get(canonical) if canonical else None

    def __contains__(self, catid: str) -> bool:
        return self.get(catid) is not None

    def __len__(self) -> int:
        return len(self.by_catid)

    def __iter__(self):
        return iter(self.by_catid.values())

    @cached_property
    def term_index(self):
        """The rows' matchable terms (:class:`~foley.index.taxonomy.text.TermIndex`), built once."""
        from .text import build_term_index

        return build_term_index(self)


@dataclass
class AudioSetUcsMap:
    """AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).

    Keyed primarily by lowercased label **name** (robust); ``by_mid`` carries the
    best-effort ``/m/...`` machine ids as a secondary key. Every target CatID is
    validated against the UCS table at load time (fail-fast on a broken map).
    """

    by_name: dict[str, str] = field(default_factory=dict)
    by_mid: dict[str, str] = field(default_factory=dict)

    def resolve(self, label: str) -> Optional[str]:
        """Map one AudioSet label (a MID or a name) to a UCS CatID (or ``None``)."""
        if label in self.by_mid:
            return self.by_mid[label]
        return self.by_name.get(label.lower())


@dataclass
class CatIdResolution:
    """The result of resolving free tags/caption/labels to a UCS CatID.

    ``catid`` feeds :attr:`~foley.base.SoundRecord.ucs_category` and
    ``subcategory`` feeds :attr:`~foley.base.SoundRecord.ucs_subcategory` on
    ingest, and :attr:`~foley.base.SoundEvent.ucs_catid` on the query side.
    """

    catid: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    source: Optional[str] = (
        None  # 'filename' | 'metadata' | 'keyword' | 'audioset' | None
    )
    confidence: float = 0.0  # coarse per-stage band, 0..1
    matched_terms: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Truthy iff a CatID was resolved."""
        return self.catid is not None
