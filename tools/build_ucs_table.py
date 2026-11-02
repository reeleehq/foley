"""Build ``foley/index/taxonomy/data/ucs_master.json`` from the UCS master spreadsheet (#227).

The Universal Category System (https://universalcategorysystem.com, "a public domain
initiative") publishes its category list as ``UCS v8.2.1 Full List.xlsx`` in the
resources folder linked from its home page. Download it, then::

    python tools/build_ucs_table.py "UCS v8.2.1 Full List.xlsx"

Needs ``openpyxl`` (a dev-only tool; foley itself only reads the JSON).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

UCS_VERSION = "8.2.1"
SOURCE_URL = "https://universalcategorysystem.com"
OUT = Path(__file__).resolve().parents[1] / "foley/index/taxonomy/data/ucs_master.json"
HEADER = ("Category", "SubCategory", "CatID", "CatShort", "Explanations")


def unmojibake(text: str) -> str:
    """``text`` with Mac-Roman double-encoding undone (``saut‚àö¬©`` → ``sauté``).

    A few cells of the master were saved through Mac Roman more than once; undo it
    while that round trip still changes the text and stays valid UTF-8.

    >>> unmojibake("saut‚àö¬©"), unmojibake("quincea‚àö¬±era"), unmojibake("plain")
    ('sauté', 'quinceañera', 'plain')
    """
    while True:
        try:
            fixed = text.encode("mac_roman").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
        if fixed == text:
            return text
        text = fixed


def read_rows(xlsx: Path) -> "list[dict]":
    """The master's rows as ``{catid, category, subcategory, explanation, synonyms}``."""
    import openpyxl

    sheet = openpyxl.load_workbook(xlsx, read_only=True).worksheets[0]
    rows, cols = [], None
    for values in sheet.iter_rows(values_only=True):
        cells = [str(v).strip() if v is not None else "" for v in values]
        if cols is None:
            if tuple(cells[: len(HEADER)]) == HEADER:
                cols = {name: i for i, name in enumerate(cells) if name}
            continue
        catid = cells[cols["CatID"]]
        if not catid:
            continue
        synonyms = [
            unmojibake(s.strip())
            for s in cells[cols["Synonyms - Comma Separated"]].split(",")
        ]
        rows.append(
            {
                "catid": catid,
                "category": unmojibake(cells[cols["Category"]]),
                "subcategory": unmojibake(cells[cols["SubCategory"]]),
                "explanation": unmojibake(cells[cols["Explanations"]]),
                "synonyms": sorted({s.lower() for s in synonyms if s}),
                "confident": True,
            }
        )
    if cols is None:
        raise ValueError(f"no header row {HEADER} in {xlsx}")
    return rows


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    rows = read_rows(args.xlsx)
    doc = {
        "source": f"UCS v{UCS_VERSION} Full List ({SOURCE_URL})",
        "terms": "UCS is published as a public domain initiative (universalcategorysystem.com)",
        "version": UCS_VERSION,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
    )
    print(f"{len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
