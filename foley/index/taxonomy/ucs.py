"""UCS table loading + the UCS-filename CatID parse (report 04 §5.2, §6.4).

A UCS filename is underscore-delimited with the **CatID first**::

    CatID[-UserCategory]_[VendorCategory-]FXName_CreatorID_SourceID[_UserData].ext

Only the CatID carries the controlled taxonomy; it is looked up in the table (never
string-split, since the category prefix is variable-length).
:func:`parse_ucs_name` returns every block (:class:`~.model.UcsName`);
:func:`parse_ucs_filename` just the category pair; :func:`format_ucs_name` is the
inverse of :func:`parse_ucs_name` (it sanitises each block so the name parses back). The
default table is the shipped UCS v8.2.1 master with the seed's curated phrases added,
and an optional house drop under ``taxonomy/data/ucs_full.json`` on top (it wins on
CatID collision) — open/closed. A CatID matches case-insensitively only when it is
mixed-case (``doorwood`` is ``DOORWood``). An all-capitals one (``RAIN``, ``MIX``,
``RAW``, ``REF``) must be written as such, and counts only in a name with every
mandatory block (:data:`UCS_MANDATORY_BLOCKS`), since ``RAW_01.wav`` and
``MIX_final.wav`` are ordinary names.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields as dataclass_fields, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Union

from .model import UcsName, UcsRow, UcsTable
from .seed import LEGACY_CATIDS, SEED_UCS_TABLE

_DATA_DIR = Path(__file__).parent / "data"
_UCS_FULL_FILE = "ucs_full.json"
#: The UCS v8.2.1 master as shipped (``tools/build_ucs_table.py``; #227).
UCS_MASTER_FILE = _DATA_DIR / "ucs_master.json"


def _row_from_dict(d: dict) -> UcsRow:
    return UcsRow(
        catid=d["catid"],
        category=d["category"],
        subcategory=d["subcategory"],
        synonyms=tuple(s.lower() for s in d.get("synonyms", ())),
        confident=bool(d.get("confident", False)),
        explanation=d.get("explanation", ""),
    )


def _json_rows(path: Path) -> "list[dict]":
    """The rows of a UCS JSON file: a bare list, or ``{"rows": [...], ...provenance}``."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["rows"] if isinstance(doc, dict) else doc


def _table(
    rows: "dict[str, UcsRow]",
    *,
    legacy_catids: "Mapping[str, str]" = MappingProxyType({}),
) -> UcsTable:
    """A :class:`UcsTable` of ``rows``; each legacy CatID whose target is a row (and
    that is not a row itself) resolves to it."""
    return UcsTable(
        by_catid=dict(rows),
        order=list(rows),
        _ci_index={c.lower(): c for c in rows if not c.isupper()},
        legacy={
            old.lower(): new
            for old, new in legacy_catids.items()
            if new in rows and old not in rows
        },
    )


def _with_phrases(row: UcsRow, phrases) -> UcsRow:
    """``row`` with ``phrases`` appended to its synonyms (order kept, no repeats)."""
    extra = tuple(
        p for p in dict.fromkeys(s.lower() for s in phrases) if p not in row.synonyms
    )
    return replace(row, synonyms=row.synonyms + extra) if extra else row


def load_ucs_table(
    *,
    data_dir=None,
    master=UCS_MASTER_FILE,
    include_seed: bool = True,
    legacy_catids: "Mapping[str, str]" = LEGACY_CATIDS,
) -> UcsTable:
    """Build the UCS lookup: the v8.2.1 master, the seed's phrases, then a JSON drop.

    Args:
        data_dir: Directory to look for ``ucs_full.json`` in (defaults to the
            package's ``taxonomy/data/``). Its rows override any row on CatID
            collision and add new ones (a house extension of UCS).
        master: The UCS master JSON (default: the shipped v8.2.1 table). ``None``,
            or a path that does not exist, falls back to the seed rows alone.
        include_seed: Add the seed's curated phrases to their master rows (default
            ``True``); with no master, the seed rows are the table.
        legacy_catids: Old CatIDs a stored record may carry, mapped to real ones
            (default :data:`~foley.index.taxonomy.seed.LEGACY_CATIDS`); the table's
            ``get`` resolves them.

    Returns:
        A ready :class:`~foley.index.taxonomy.model.UcsTable`.

    Raises:
        ValueError: no master and ``include_seed=False``: there would be no rows.

    >>> t = load_ucs_table()
    >>> len(t), t.get("RAIN").category, "rain on window" in t.get("RAIN").synonyms
    (753, 'RAIN', True)
    """
    master_path = Path(master) if master else None
    rows: dict[str, UcsRow] = {}
    if master_path is not None and master_path.exists():
        rows = {d["catid"]: _row_from_dict(d) for d in _json_rows(master_path)}
    elif not include_seed:
        raise ValueError(
            f"no UCS master at {master!r} and include_seed=False: the table would be "
            "empty (pass include_seed=True for the seed rows alone)"
        )
    if include_seed:
        for d in SEED_UCS_TABLE:
            known = rows.get(d["catid"])
            rows[d["catid"]] = (
                _with_phrases(known, d["synonyms"])
                if known is not None
                else _row_from_dict({**d, "confident": True})
            )
    search_dir = Path(data_dir) if data_dir else _DATA_DIR
    full = search_dir / _UCS_FULL_FILE
    if full.exists():
        for d in _json_rows(full):
            rows[d["catid"]] = _row_from_dict(d)
    return _table(rows, legacy_catids=legacy_catids)


@lru_cache(maxsize=1)
def load_ucs_master() -> UcsTable:
    """The UCS v8.2.1 master as shipped (753 rows, 82 categories): no seed, no drop.

    Row fields are the master's, verbatim (``SubCategory`` in capitals:
    ``('DOORS', 'WOOD')``), with its explanation and synonyms (lowercased). The
    default table (:func:`default_ucs_table`) is this plus the seed's phrases.

    >>> t = load_ucs_master()
    >>> len(t), t.get("doorwood").subcategory, "WOODHndl" in t
    (753, 'WOOD', True)
    """
    return _table({d["catid"]: _row_from_dict(d) for d in _json_rows(UCS_MASTER_FILE)})


@lru_cache(maxsize=1)
def default_ucs_table() -> UcsTable:
    """The process-wide default UCS table (master + seed phrases + any drop), built once."""
    return load_ucs_table()


#: The block separator of a UCS filename, and the one that attaches the optional
#: UserCategory to the CatID and VendorCategory to the FXName.
BLOCK_SEP = "_"
ATTACH_SEP = "-"

#: The blocks every UCS filename has (``CatID_FXName_CreatorID_SourceID``). A name
#: whose CatID is all capitals (``RAW``, ``MIX``, ``RAIN``) must have all of them to
#: read as UCS: with fewer, ``RAW_01.wav`` is just a name.
UCS_MANDATORY_BLOCKS = ("catid", "fx_name", "creator_id", "source_id")


def _reads_as_word(token: str, row: UcsRow) -> bool:
    """Whether a filename's CatID ``token`` is an all-capitals CatID (``RAW``), as
    written: an ordinary name may start with it too."""
    return token == row.catid and token.isupper()


#: A filename extension: a short alphanumeric suffix (``.wav``, ``.flac``). A dot
#: anywhere else (``Creak 5.1_JD``) belongs to the name.
_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


def looks_like_vendor_tag(prefix: str) -> bool:
    """Whether the text before an FXName's first hyphen reads as a VendorCategory.

    UCS lets a vendor prefix the FXName (``BOOM-Creak Open``), but hyphens are common
    inside FX names (``Hand-Held Creak``, ``Sci-Fi Door``). So only an upper-case
    tag with no spaces counts.

    >>> looks_like_vendor_tag("BOOM"), looks_like_vendor_tag("Sci"), looks_like_vendor_tag("SFX 2")
    (True, False, False)
    """
    return prefix.isupper() and prefix.isalnum()


def _ucs_blocks(filename) -> "list[str]":
    """The stripped blocks of a filename (directory and extension dropped; ``[]`` without a separator)."""
    stem = _EXTENSION.sub("", Path(str(filename)).name).strip()
    return [b.strip() for b in stem.split(BLOCK_SEP)] if BLOCK_SEP in stem else []


def _split_attached(block: str) -> "tuple[str, Optional[str]]":
    """``(left, right)`` of ``block`` at its first :data:`ATTACH_SEP`; ``(block, None)`` if none."""
    left, sep, right = block.partition(ATTACH_SEP)
    left, right = left.strip(), right.strip()
    return (left, right) if sep and left and right else (block, None)


def parse_catid_token(filename) -> Optional[str]:
    """Return the CatID candidate of a UCS-style filename, else ``None``.

    Strips directory, extension and an attached ``-UserCategory``; requires at least
    one ``_`` (the field delimiter). Does not validate the token against the table.

    >>> parse_catid_token("DOORWood-Gate_Creak_JD_NYC.wav")
    'DOORWood'
    """
    blocks = _ucs_blocks(filename)
    return (_split_attached(blocks[0])[0] or None) if blocks else None


def parse_ucs_name(
    filename,
    *,
    table: Optional[UcsTable] = None,
    is_vendor_tag: Callable[[str], bool] = looks_like_vendor_tag,
) -> Optional[UcsName]:
    """Every block of a UCS filename as a :class:`~.model.UcsName`, else ``None``.

    Fail-quiet like :func:`parse_ucs_filename`: ``None`` when the name has no ``_``,
    its CatID is not in the table, or its CatID is all capitals (``RAW``, ``MIX``) and
    it lacks a mandatory block (:data:`UCS_MANDATORY_BLOCKS`). Blocks past SourceID
    are the UserData (rejoined with ``_``); a block the name lacks is ``None``. The
    FXName block's head before a hyphen is the VendorCategory only when
    ``is_vendor_tag`` accepts it (:func:`looks_like_vendor_tag`), so ``Sci-Fi Door``
    stays whole.

    >>> n = parse_ucs_name("DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take 2.wav")
    >>> (n.catid, n.category, n.subcategory, n.user_category)
    ('DOORWood', 'DOORS', 'WOOD', 'Gate')
    >>> (n.vendor_category, n.fx_name, n.creator_id, n.source_id, n.user_data)
    ('SCIFI', 'Creak Open', 'JD', 'NYC', 'take 2')
    >>> m = parse_ucs_name("DOORWood_Sci-Fi Slam 5.1_JD_NYC")
    >>> (m.vendor_category, m.fx_name, m.creator_id, m.source_id, m.user_data)
    (None, 'Sci-Fi Slam 5.1', 'JD', 'NYC', None)
    >>> parse_ucs_name("DOORWood_Slam.wav").creator_id is None
    True
    >>> parse_ucs_name("NOTACAT_x_y_z.wav") is None, parse_ucs_name("plain.wav") is None
    (True, True)
    >>> parse_ucs_name("MIX_final.wav") is None, parse_ucs_name("RAIN_Heavy_JD_NYC.wav").catid
    (True, 'RAIN')
    """
    blocks = _ucs_blocks(filename)
    if not blocks:
        return None
    catid, user_category = _split_attached(blocks[0])
    row = (table if table is not None else default_ucs_table()).get(catid)
    if row is None:
        return None
    if _reads_as_word(catid, row) and len(blocks) < len(UCS_MANDATORY_BLOCKS):
        return None

    def block(i: int) -> Optional[str]:
        return (blocks[i] or None) if len(blocks) > i else None

    fx_name, vendor = block(1), None
    if fx_name:
        head, tail = _split_attached(fx_name)
        if tail is not None and is_vendor_tag(head):
            vendor, fx_name = head, tail
    return UcsName(
        catid=row.catid,
        category=row.category,
        subcategory=row.subcategory,
        fx_name=fx_name,
        creator_id=block(2),
        source_id=block(3),
        user_category=user_category,
        vendor_category=vendor,
        user_data=BLOCK_SEP.join(blocks[4:]) or None,
    )


def parse_ucs_filename(
    filename, *, table: Optional[UcsTable] = None
) -> "tuple[Optional[str], Optional[str]]":
    """Parse a UCS-conformant filename to ``(ucs_category, ucs_subcategory)``.

    Fail-quiet: returns ``(None, None)`` when the name is not UCS-conformant or
    its CatID token is unknown (so a wrong subcategory is never emitted).

    Args:
        filename: A path or filename (only the basename's token 0 is used).
        table: The UCS table to resolve against (defaults to
            :func:`default_ucs_table`).
    """
    name = parse_ucs_name(filename, table=table)
    return (name.category, name.subcategory) if name else (None, None)


#: The blocks of a UCS filename, as :class:`~.model.UcsName` fields (``category`` and
#: ``subcategory`` are not blocks: they come from the CatID's table row).
UCS_NAME_BLOCKS = tuple(
    f.name
    for f in dataclass_fields(UcsName)
    if f.name not in ("category", "subcategory")
)

#: Characters a filename block may not hold (path separators, Windows-reserved
#: characters, controls); each becomes a space.
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_WHITESPACE = re.compile(r"\s+")
_CATID = re.compile(r"[A-Za-z0-9]+")


def _clean(text: Optional[str], *, unmake_ext: bool = False) -> str:
    """``text`` with unsafe characters and :data:`BLOCK_SEP` as spaces, whitespace collapsed.

    ``unmake_ext``: a trailing ``.abc``, which a parse would strip as an extension,
    has its dot made a space.
    """
    text = _UNSAFE_CHARS.sub(" ", str(text or "")).replace(BLOCK_SEP, " ")
    text = _WHITESPACE.sub(" ", text).strip()
    if unmake_ext and _EXTENSION.search(text):
        return _clean(_EXTENSION.sub(lambda m: " " + m.group()[1:], text))
    return text


def _vendor_tag(vendor: str, is_vendor_tag: Callable[[str], bool]) -> str:
    """A VendorCategory cleaned to upper-case alphanumerics (what
    :func:`looks_like_vendor_tag` accepts); one that still is not a tag raises."""
    tag = re.sub(r"[^0-9A-Za-z]", "", vendor).upper()
    if not (tag and is_vendor_tag(tag)):
        raise ValueError(f"{vendor!r} cannot be read back as a VendorCategory")
    return tag


def _unvendored(fx_name: str, is_vendor_tag: Callable[[str], bool]) -> str:
    """``fx_name`` with the hyphen made a space wherever its head would read as a
    vendor tag (``BOOM-Creak``), until none does (``Sci-Fi Door`` is kept)."""
    while True:  # each pass removes a hyphen, so this ends
        head, tail = _split_attached(fx_name)
        if tail is None or not is_vendor_tag(head):
            return fx_name
        fx_name = _clean(fx_name.replace(ATTACH_SEP, " ", 1))


#: The longest filename, in UTF-8 bytes, that :func:`format_ucs_name` makes
#: (``NAME_MAX`` on ext4, APFS and NTFS-as-seen-by-most-tools).
UCS_NAME_MAX_BYTES = 255

#: The blocks :func:`format_ucs_name` shortens, longest first, to fit
#: :data:`UCS_NAME_MAX_BYTES`. The CatID, VendorCategory and UserData are kept whole
#: (UserData may hold an id that must stay unique).
UCS_SHORTENABLE_BLOCKS = ("fx_name", "creator_id", "source_id", "user_category")


def format_ucs_name(
    name: "Union[UcsName, Mapping, None]" = None,
    /,
    *,
    ext: Optional[str] = None,
    table: Optional[UcsTable] = None,
    is_vendor_tag: Callable[[str], bool] = looks_like_vendor_tag,
    max_bytes: int = UCS_NAME_MAX_BYTES,
    **blocks,
) -> str:
    """The UCS filename of ``name`` (a :class:`~.model.UcsName` or a mapping of its
    blocks), with ``blocks`` (:data:`UCS_NAME_BLOCKS`) overriding it: the inverse of
    :func:`parse_ucs_name`.

    Each block is sanitised so the name parses back to the same blocks: unsafe
    characters and underscores inside a block become spaces, whitespace is collapsed,
    a VendorCategory is upper-cased, and a hyphen that would make an FXName's head
    read as a VendorCategory becomes a space (``Sci-Fi Door`` stays as it is). A name
    over ``max_bytes`` has its longest shortenable block
    (:data:`UCS_SHORTENABLE_BLOCKS`) cut on a character boundary until it fits. So
    ``format_ucs_name(parse_ucs_name(f))`` is ``f`` for any ``f`` this function made.
    The CatID is looked up in ``table`` (default: :func:`default_ucs_table`) and
    written in its canonical spelling; an unknown one raises, since the name would
    not parse. An all-capitals CatID keeps every mandatory block, empty if need be
    (``RAIN_Heavy__``), so the name reads back as UCS.

    Args:
        name: The blocks to format (``category`` / ``subcategory`` are ignored).
        ext: The extension to append (``'wav'`` or ``'.wav'``), or ``None`` for a stem.
        table: The UCS table the CatID must be in.
        is_vendor_tag: What reads as a VendorCategory (as in :func:`parse_ucs_name`).
        max_bytes: The longest name to make, in UTF-8 bytes, extension included.
        **blocks: Block values overriding ``name``'s.

    Raises:
        TypeError: a keyword is not a UCS block.
        ValueError: no CatID, or one not in ``table``; a bad ``ext``; a
            VendorCategory that cannot be read back or has no FXName; a name that
            cannot be cut to ``max_bytes``.

    >>> format_ucs_name(catid="doorwood", fx_name="Sci-Fi Door_slam", creator_id="JD",
    ...                 source_id="NYC", ext="wav")
    'DOORWood_Sci-Fi Door slam_JD_NYC.wav'
    >>> n = parse_ucs_name("DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take_2.wav")
    >>> format_ucs_name(n, ext="wav")
    'DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take_2.wav'
    >>> format_ucs_name(catid="DOORWood", fx_name="BOOM-Creak")  # not a vendor tag
    'DOORWood_BOOM Creak'
    >>> len(format_ucs_name(catid="DOORWood", fx_name="x" * 300, user_data="id1"))
    255
    """
    unknown = set(blocks) - set(UCS_NAME_BLOCKS)
    if unknown:
        raise TypeError(f"not UCS filename blocks: {sorted(unknown)}")
    given = dict(name) if isinstance(name, Mapping) else vars(name) if name else {}
    values = {k: blocks.get(k, given.get(k)) for k in UCS_NAME_BLOCKS}
    row = (table or default_ucs_table()).get(str(values["catid"] or ""))
    if row is None or not _CATID.fullmatch(row.catid):
        raise ValueError(f"{values['catid']!r} is not a CatID of the UCS table")
    suffix = "" if ext is None else "." + str(ext).lstrip(".")
    if ext is not None and not _EXTENSION.fullmatch(suffix):
        raise ValueError(f"{ext!r} is not a filename extension")

    def settle(
        key: str, text
    ) -> str:  # a stem's last block must not end like an extension
        text = _clean(text, unmake_ext=ext is None)
        return (
            _unvendored(text, is_vendor_tag)
            if key == "fx_name" and not vendor
            else text
        )

    vendor = values["vendor_category"]
    vendor = (
        _vendor_tag(settle("vendor_category", vendor), is_vendor_tag)
        if vendor
        else None
    )
    texts = {k: settle(k, values[k]) for k in UCS_SHORTENABLE_BLOCKS}
    user_data = [
        settle("user_data", p) for p in str(values["user_data"] or "").split(BLOCK_SEP)
    ]

    def compose() -> str:
        uc, fx = texts["user_category"], texts["fx_name"]
        if vendor and not fx:
            raise ValueError("a VendorCategory attaches to an FXName; there is none")
        parts = [
            f"{row.catid}{ATTACH_SEP}{uc}" if uc else row.catid,
            f"{vendor}{ATTACH_SEP}{fx}" if vendor else fx,
            texts["creator_id"],
            texts["source_id"],
        ]
        if any(user_data):
            parts += user_data
        else:  # an all-capitals CatID keeps its mandatory blocks, empty or not
            keep = len(UCS_MANDATORY_BLOCKS) if row.catid.isupper() else 2
            while len(parts) > keep and not parts[-1]:
                parts.pop()
        return BLOCK_SEP.join(parts) + suffix

    while (excess := len(compose().encode("utf-8")) - max_bytes) > 0:
        key = max(UCS_SHORTENABLE_BLOCKS, key=lambda k: len(texts[k].encode("utf-8")))
        size = len(texts[key].encode("utf-8"))
        if not size:
            raise ValueError(
                f"the name cannot be cut to {max_bytes} bytes: {compose()!r}"
            )
        cut = texts[key].encode("utf-8")[: max(size - excess, 0)]
        texts[key] = settle(key, cut.decode("utf-8", "ignore"))
    return compose()
