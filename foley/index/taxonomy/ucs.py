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
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .model import UcsName, UcsRow, UcsTable
from .seed import SEED_UCS_TABLE

_DATA_DIR = Path(__file__).parent / "data"
_UCS_FULL_FILE = "ucs_full.json"


def _row_from_dict(d: dict) -> UcsRow:
    return UcsRow(
        catid=d["catid"],
        category=d["category"],
        subcategory=d["subcategory"],
        synonyms=tuple(s.lower() for s in d.get("synonyms", ())),
        confident=bool(d.get("confident", False)),
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
        for d in json.loads(full.read_text(encoding="utf-8")):
            rows[d["catid"]] = _row_from_dict(d)
    order = list(rows)
    ci_index = {c.lower(): c for c in rows}
    return UcsTable(by_catid=dict(rows), order=order, _ci_index=ci_index)


@lru_cache(maxsize=1)
def default_ucs_table() -> UcsTable:
    """The process-wide default UCS table (seed + any JSON drop), built once."""
    return load_ucs_table()


def _ucs_blocks(filename) -> "list[str]":
    """The underscore-delimited blocks of a filename's stem (``[]`` without a ``_``)."""
    stem = Path(str(filename)).stem.strip()
    return [b.strip() for b in stem.split("_")] if "_" in stem else []


def _split_hyphen(block: str, *, head: bool) -> "tuple[str, Optional[str]]":
    """``block`` split on its first hyphen: ``(main, extra)``, ``extra`` the head or tail."""
    left, sep, right = block.partition("-")
    if not sep or not left or not right:
        return block, None
    return (right, left) if head else (left, right)


def parse_catid_token(filename) -> Optional[str]:
    """Return the CatID candidate of a UCS-style filename, else ``None``.

    Strips directory, extension and an attached ``-UserCategory``; requires at least
    one ``_`` (the field delimiter). Does not validate the token against the table.

    >>> parse_catid_token("DOORWood-Gate_Creak_JD_NYC.wav")
    'DOORWood'
    """
    blocks = _ucs_blocks(filename)
    return (_split_hyphen(blocks[0], head=False)[0] or None) if blocks else None


def parse_ucs_name(filename, *, table: Optional[UcsTable] = None) -> Optional[UcsName]:
    """Every block of a UCS filename as a :class:`~.model.UcsName`, else ``None``.

    Fail-quiet like :func:`parse_ucs_filename`: ``None`` when the name has no ``_`` or
    its CatID is not in the table. Blocks past SourceID are the UserData (rejoined
    with ``_``); a block the name lacks is ``None``. A hyphen in the FXName block is
    read as the VendorCategory separator, as UCS defines it.

    >>> n = parse_ucs_name("DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take 2.wav")
    >>> (n.catid, n.category, n.subcategory, n.user_category)
    ('DOORWood', 'DOORS', 'Wood', 'Gate')
    >>> (n.vendor_category, n.fx_name, n.creator_id, n.source_id, n.user_data)
    ('SCIFI', 'Creak Open', 'JD', 'NYC', 'take 2')
    >>> parse_ucs_name("DOORWood_Slam.wav").creator_id is None
    True
    >>> parse_ucs_name("NOTACAT_x_y_z.wav") is None
    True
    """
    blocks = _ucs_blocks(filename)
    if not blocks:
        return None
    catid, user_category = _split_hyphen(blocks[0], head=False)
    row = (table or default_ucs_table()).get(catid)
    if row is None:
        return None
    fx_name = vendor = None
    if len(blocks) > 1 and blocks[1]:
        fx_name, vendor = _split_hyphen(blocks[1], head=True)
    at = lambda i: (blocks[i] or None) if len(blocks) > i else None  # noqa: E731
    return UcsName(
        catid=row.catid,
        category=row.category,
        subcategory=row.subcategory,
        fx_name=fx_name,
        creator_id=at(2),
        source_id=at(3),
        user_category=user_category,
        vendor_category=vendor,
        user_data="_".join(blocks[4:]) or None,
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
