"""What a pro sound file says about itself: Broadcast-WAV ``bext`` and iXML (#228).

Commercial packs (BOOM, Pro Sound Effects, Sonniss GDC) describe each file inside it:
the EBU Broadcast-WAV ``bext`` chunk (``Description``, ``Originator``, the origination
date) and an ``iXML`` chunk whose ``<USER>`` block carries the Soundminer / UCS fields
(``CATEGORY``, ``SUBCATEGORY``, ``CATID``, ``FXNAME``, ``DESCRIPTION``, ``KEYWORDS``,
``LIBRARY``, ``MANUFACTURER``, ...). :func:`read_embedded_metadata` reads both with
the standard library and returns foley's view of them::

    {"caption": ..., "tags": [...], "catid": ..., "fx_name": ..., "library": ...,
     "manufacturer": ..., "raw": {"bext": {...}, "ixml": {...}}}

Fail-quiet: a file that is not a RIFF/RF64 WAV, or has neither chunk, gives ``{}``.
:data:`FIELD_MAP` is the one table between the embedded fields and foley's names, for
the reader here and a writer later (#231).
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from typing import BinaryIO, Iterator, Optional

#: foley field -> where it is read from, in precedence order: ``("ixml", TAG)`` is an
#: iXML ``<USER>`` tag, ``("bext", FIELD)`` a ``bext`` field.
FIELD_MAP: "dict[str, tuple[tuple[str, str], ...]]" = {
    "caption": (("ixml", "DESCRIPTION"), ("bext", "description"), ("ixml", "FXNAME")),
    "fx_name": (("ixml", "FXNAME"),),
    "catid": (("ixml", "CATID"),),
    "category": (("ixml", "CATEGORY"),),
    "subcategory": (("ixml", "SUBCATEGORY"),),
    "library": (("ixml", "LIBRARY"),),
    "manufacturer": (("ixml", "MANUFACTURER"), ("bext", "originator")),
    "designer": (("ixml", "DESIGNER"),),
    "keywords": (("ixml", "KEYWORDS"),),
}

#: The fixed-width text fields at the start of a ``bext`` chunk (EBU Tech 3285).
BEXT_FIELDS = (
    ("description", 256),
    ("originator", 32),
    ("originator_reference", 32),
    ("origination_date", 10),
    ("origination_time", 8),
)

#: How keywords are separated in the wild (commas, semicolons).
_KEYWORD_SEP = re.compile(r"[,;]")

#: The 32-bit size RF64 writes for a chunk whose real size is in ``ds64``.
_RF64_PLACEHOLDER = 0xFFFFFFFF


def iter_riff_chunks(f: BinaryIO) -> "Iterator[tuple[bytes, int, int]]":
    """``(chunk_id, offset, size)`` for each top-level chunk of a RIFF / RF64 WAVE file.

    Walks the chunk headers with seeks, never reading the audio, so a large file costs
    a few small reads. Stops quietly at a truncated chunk. For RF64, the ``data``
    chunk's real size comes from ``ds64``.

    >>> import io
    >>> body = b"WAVE" + b"abcd" + struct.pack("<I", 1) + b"x\\0"
    >>> wav = io.BytesIO(b"RIFF" + struct.pack("<I", len(body)) + body)
    >>> list(iter_riff_chunks(wav))
    [(b'abcd', 20, 1)]
    """
    f.seek(0, 2)
    total = f.tell()
    f.seek(0)
    head = f.read(12)
    if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
        return
    pos, data_size = 12, None
    while pos + 8 <= total:
        f.seek(pos)
        chunk_id, (size,) = (h := f.read(8))[:4], struct.unpack("<I", h[4:8])
        if chunk_id == b"ds64" and size >= 24:
            f.seek(pos + 8 + 16)  # riffSize (8), dataSize (8)
            (data_size,) = struct.unpack("<Q", f.read(8))
        if size == _RF64_PLACEHOLDER and chunk_id == b"data" and data_size is not None:
            size = data_size
        if pos + 8 + size > total:
            return
        yield chunk_id, pos + 8, size
        pos += 8 + size + (size & 1)  # chunks are word-aligned


def parse_bext(payload: bytes) -> "dict[str, str]":
    """The text fields of a ``bext`` chunk (NUL-padded, Latin-1 / ASCII), non-empty only."""
    out, pos = {}, 0
    for name, width in BEXT_FIELDS:
        text = payload[pos : pos + width].split(b"\0", 1)[0].decode("latin-1").strip()
        if text:
            out[name] = text
        pos += width
    return out


def parse_ixml_user(payload: bytes) -> "dict[str, str]":
    """The ``<USER>`` fields of an iXML chunk (tag → text), or ``{}`` if unreadable."""
    text = payload.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return {}
    user = root.find("USER")
    if user is None:
        return {}
    return {
        child.tag.upper(): (child.text or "").strip()
        for child in user
        if (child.text or "").strip()
    }


def _pick(raw: "dict[str, dict]", sources) -> Optional[str]:
    """The first non-empty value of ``sources`` (``(chunk, field)`` pairs) in ``raw``."""
    for chunk, field in sources:
        value = raw.get(chunk, {}).get(field)
        if value:
            return value
    return None


def read_embedded_metadata(path) -> dict:
    """foley's view of a WAV's ``bext`` and iXML metadata (see the module docs), or ``{}``.

    >>> read_embedded_metadata(__file__)  # not a WAV
    {}
    """
    parsers = {b"bext": ("bext", parse_bext), b"iXML": ("ixml", parse_ixml_user)}
    raw: "dict[str, dict]" = {}
    try:
        with open(path, "rb") as f:
            for chunk_id, offset, size in iter_riff_chunks(f):
                if chunk_id in parsers:
                    name, parse = parsers[chunk_id]
                    f.seek(offset)
                    raw[name] = parse(f.read(size))
    except (OSError, struct.error):
        return {}
    raw = {k: v for k, v in raw.items() if v}
    if not raw:
        return {}
    out = {name: _pick(raw, sources) for name, sources in FIELD_MAP.items()}
    keywords = out.pop("keywords")
    tags = [k.strip().lower() for k in _KEYWORD_SEP.split(keywords or "") if k.strip()]
    return {**{k: v for k, v in out.items() if v}, "tags": tags, "raw": raw}
