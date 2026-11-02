"""UCS table loading + the UCS-filename CatID parse (report 04 §5.2, §6.4).

A UCS filename is underscore-delimited with the **CatID first**::

    CatID[-UserCategory]_[VendorCategory-]FXName_CreatorID_SourceID[_UserData].ext

Only the CatID carries the controlled taxonomy; it is looked up in the table (never
string-split, since the category prefix is variable-length).
:func:`parse_ucs_name` returns every block (:class:`~.model.UcsName`);
:func:`parse_ucs_filename` just the category pair. The
loader merges the in-code seed with an optional full-table JSON drop under
``taxonomy/data/ucs_full.json`` (JSON wins on CatID collision) — open/closed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from .model import UcsName, UcsRow, UcsTable
from .seed import SEED_UCS_TABLE

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


def _table(rows: "dict[str, UcsRow]") -> UcsTable:
    return UcsTable(
        by_catid=dict(rows), order=list(rows), _ci_index={c.lower(): c for c in rows}
    )


def load_ucs_table(*, data_dir=None, include_seed: bool = True) -> UcsTable:
    """Build the UCS lookup: the seed rows, overridden/extended by a JSON drop.

    Args:
        data_dir: Directory to look for ``ucs_full.json`` in (defaults to the
            package's ``taxonomy/data/``). When present, its rows override the
            seed on CatID collision and add the rest of the ~750-row master.
        include_seed: Start from the in-code seed table (default ``True``).

    Returns:
        A ready :class:`~foley.index.taxonomy.model.UcsTable`.
    """
    rows: dict[str, UcsRow] = {}
    if include_seed:
        for d in SEED_UCS_TABLE:
            rows[d["catid"]] = _row_from_dict(d)
    search_dir = Path(data_dir) if data_dir else _DATA_DIR
    full = search_dir / _UCS_FULL_FILE
    if full.exists():
        for d in _json_rows(full):
            rows[d["catid"]] = _row_from_dict(d)
    return _table(rows)


@lru_cache(maxsize=1)
def load_ucs_master() -> UcsTable:
    """The authoritative UCS v8.2.1 master (753 rows, 82 categories), without the seed.

    Opt-in for now: the default table (:func:`default_ucs_table`) is still the
    in-code seed, whose CatIDs mostly predate the master. Pass it where a table is
    taken (``parse_ucs_name(name, table=load_ucs_master())``). Row fields are the
    master's, verbatim (``SubCategory`` in capitals: ``('DOORS', 'WOOD')``), with its
    explanation and synonyms (lowercased).

    >>> t = load_ucs_master()
    >>> len(t), t.get("doorwood").subcategory, "WOODHndl" in t
    (753, 'WOOD', True)
    """
    return _table({d["catid"]: _row_from_dict(d) for d in _json_rows(UCS_MASTER_FILE)})


@lru_cache(maxsize=1)
def default_ucs_table() -> UcsTable:
    """The process-wide default UCS table (seed + any JSON drop), built once."""
    return load_ucs_table()


#: The block separator of a UCS filename, and the one that attaches the optional
#: UserCategory to the CatID and VendorCategory to the FXName.
BLOCK_SEP = "_"
ATTACH_SEP = "-"

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

    Fail-quiet like :func:`parse_ucs_filename`: ``None`` when the name has no ``_`` or
    its CatID is not in the table. Blocks past SourceID are the UserData (rejoined
    with ``_``); a block the name lacks is ``None``. The FXName block's head before a
    hyphen is the VendorCategory only when ``is_vendor_tag`` accepts it
    (:func:`looks_like_vendor_tag`), so ``Sci-Fi Door`` stays whole.

    >>> n = parse_ucs_name("DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take 2.wav")
    >>> (n.catid, n.category, n.subcategory, n.user_category)
    ('DOORWood', 'DOORS', 'Wood', 'Gate')
    >>> (n.vendor_category, n.fx_name, n.creator_id, n.source_id, n.user_data)
    ('SCIFI', 'Creak Open', 'JD', 'NYC', 'take 2')
    >>> m = parse_ucs_name("DOORWood_Sci-Fi Slam 5.1_JD_NYC")
    >>> (m.vendor_category, m.fx_name, m.creator_id, m.source_id, m.user_data)
    (None, 'Sci-Fi Slam 5.1', 'JD', 'NYC', None)
    >>> parse_ucs_name("DOORWood_Slam.wav").creator_id is None
    True
    >>> parse_ucs_name("NOTACAT_x_y_z.wav") is None, parse_ucs_name("plain.wav") is None
    (True, True)
    """
    blocks = _ucs_blocks(filename)
    if not blocks:
        return None
    catid, user_category = _split_attached(blocks[0])
    row = (table or default_ucs_table()).get(catid)
    if row is None:
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
