"""What a pro sound file says about itself: Broadcast-WAV ``bext`` and iXML (#228).

Commercial packs (BOOM, Pro Sound Effects, Sonniss GDC) describe each file inside it:
the EBU Broadcast-WAV ``bext`` chunk (``Description``, ``Originator``, the origination
date) and an ``iXML`` chunk whose ``<USER>`` block carries the Soundminer / UCS fields
(``CATEGORY``, ``SUBCATEGORY``, ``CATID``, ``FXNAME``, ``DESCRIPTION``, ``KEYWORDS``,
``LIBRARY``, ``MANUFACTURER``, ...). :func:`read_embedded_metadata` reads both with the
standard library and returns foley's view of them::

    {"caption": ..., "tags": [...], "ucs_catid": ..., "fx_name": ..., "library": ...,
     "manufacturer": ..., "raw": {"bext": {...}, "ixml": {...}}}

Only the fields the file has are present. A file that is not a RIFF / RF64 / BW64 WAVE,
or has neither chunk, gives ``{}``; a missing file raises :class:`FileNotFoundError`.

:data:`FIELDS` is the one table between the chunks and foley's names, both ways: each
:class:`Field` has a canonical ``write`` location (where an exporter puts the value,
and where a reader looks first) and ordered ``read_also`` fallbacks, plus the
``decode`` / ``encode`` pair between the stored text and foley's value.
:func:`fields_from_chunks` and :func:`chunks_from_fields` are its two directions, so
the writer of #231 reuses the table rather than inverting it. The names are foley's
(``caption``, ``tags``, ``ucs_*`` as on :class:`~foley.base.SoundRecord` /
:class:`~foley.base.SoundEvent`, ``fx_name`` as on the UCS filename parse).

This module sits beside :mod:`foley.audio` rather than in :mod:`foley.index`: it is
file-format I/O that both ingest (reading) and export (writing) use, stdlib-only.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, Iterator, Mapping

#: The RIFF form types read: classic RIFF, EBU RF64 (Tech 3306), ITU-R BS.2088 BW64.
RIFF_FORMS = (b"RIFF", b"RF64", b"BW64")

#: A bext or iXML chunk bigger than this is skipped (real ones are a few kB).
MAX_METADATA_CHUNK_BYTES = 4 * 1024 * 1024

#: The fixed-width text fields at the start of a ``bext`` chunk (EBU Tech 3285).
BEXT_FIELDS = (
    ("description", 256),
    ("originator", 32),
    ("originator_reference", 32),
    ("origination_date", 10),
    ("origination_time", 8),
)

#: How keywords are separated in the wild, and how foley writes them.
KEYWORD_SEPARATORS = re.compile(r"[,;]")
KEYWORD_JOINER = ", "

#: The names :data:`FIELDS` locations use for the two chunks (also the ``raw`` keys).
BEXT, IXML = "bext", "ixml"

#: The 32-bit size RF64 / BW64 write for a chunk whose real size is in ``ds64``.
_SIZE_PLACEHOLDER = 0xFFFFFFFF
#: Offset of ``dataSize`` in a ``ds64`` payload (after the 8-byte ``riffSize``).
_DS64_DATA_SIZE_AT = 8
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


# --------------------------------------------------------------------------------------
# The field table: one SSOT for reading and writing
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    """A place a value lives: a ``bext`` field name or an iXML ``<USER>`` tag."""

    chunk: str  # BEXT | IXML
    key: str


def split_keywords(text: str) -> "list[str]":
    """Keywords from a ``KEYWORDS`` string: split on , and ;, de-duplicated ignoring case.

    >>> split_keywords("door, creak; Wood ,DOOR")
    ['door', 'creak', 'Wood']
    """
    seen, out = set(), []
    for word in (w.strip() for w in KEYWORD_SEPARATORS.split(text)):
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            out.append(word)
    return out


def join_keywords(tags) -> str:
    """The ``KEYWORDS`` string for ``tags`` (the inverse of :func:`split_keywords`).

    >>> join_keywords(["door", " creak "])
    'door, creak'
    """
    return KEYWORD_JOINER.join(filter(None, (tag.strip() for tag in tags)))


@dataclass(frozen=True)
class Field:
    """One foley field and where it lives in a WAV's metadata chunks.

    ``write`` is the canonical location: a writer puts the value there and a reader
    looks there first. ``read_also`` are read-only fallbacks, tried in order.
    ``decode`` turns the stored text into foley's value; ``encode`` turns it back.
    """

    name: str
    write: Location
    read_also: "tuple[Location, ...]" = ()
    decode: Callable[[str], Any] = str
    encode: Callable[[Any], str] = str

    @property
    def read_from(self) -> "tuple[Location, ...]":
        """Every location a reader tries, canonical first."""
        return (self.write, *self.read_also)


#: foley field <-> chunk locations (see :class:`Field`).
FIELDS: "tuple[Field, ...]" = (
    Field(
        "caption",
        Location(IXML, "DESCRIPTION"),
        read_also=(Location(BEXT, "description"), Location(IXML, "FXNAME")),
    ),
    Field(
        "tags", Location(IXML, "KEYWORDS"), decode=split_keywords, encode=join_keywords
    ),
    Field("fx_name", Location(IXML, "FXNAME")),
    Field("ucs_catid", Location(IXML, "CATID")),
    Field("ucs_category", Location(IXML, "CATEGORY")),
    Field("ucs_subcategory", Location(IXML, "SUBCATEGORY")),
    Field("library", Location(IXML, "LIBRARY")),
    Field(
        "manufacturer",
        Location(IXML, "MANUFACTURER"),
        read_also=(Location(BEXT, "originator"),),
    ),
    Field("designer", Location(IXML, "DESIGNER")),
)


def fields_from_chunks(raw: Mapping, *, fields=FIELDS) -> dict:
    """foley's fields from parsed chunks (``{"bext": {...}, "ixml": {...}}``), non-empty only.

    >>> fields_from_chunks({"bext": {"description": "Rain"}, "ixml": {"KEYWORDS": "a;b"}})
    {'caption': 'Rain', 'tags': ['a', 'b']}
    """
    out = {}
    for fld in fields:
        found = (raw.get(loc.chunk, {}).get(loc.key) for loc in fld.read_from)
        text = next(filter(None, found), None)
        value = fld.decode(text) if text else None
        if value:
            out[fld.name] = value
    return out


def chunks_from_fields(meta: Mapping, *, fields=FIELDS) -> "dict[str, dict[str, str]]":
    """Where a writer puts each of foley's fields: ``{chunk: {key: text}}``, canonical only.

    >>> chunks_from_fields({"caption": "Rain", "tags": ["a", "b"], "other": 1})
    {'ixml': {'DESCRIPTION': 'Rain', 'KEYWORDS': 'a, b'}}
    """
    out: "dict[str, dict[str, str]]" = {}
    for fld in fields:
        text = fld.encode(meta[fld.name]) if meta.get(fld.name) else ""
        if text:
            out.setdefault(fld.write.chunk, {})[fld.write.key] = text
    return out


# --------------------------------------------------------------------------------------
# The RIFF chunk walk
# --------------------------------------------------------------------------------------


def _is_chunk_header_at(f: BinaryIO, pos: int, total: int) -> bool:
    """Whether a plausible chunk header starts at ``pos``: a printable ASCII id and a
    size that fits in the file (or the RF64 / BW64 placeholder)."""
    if pos + 8 > total:
        return False
    f.seek(pos)
    header = f.read(8)
    (size,) = struct.unpack("<I", header[4:])
    printable = all(0x20 <= b < 0x7F for b in header[:4])
    return printable and (pos + 8 + size <= total or size == _SIZE_PLACEHOLDER)


def _next_chunk_at(f: BinaryIO, end: int, size: int, total: int) -> int:
    """Where the chunk after one ending at ``end`` starts.

    Chunks are word-aligned (an odd-sized one is followed by a pad byte); a writer that
    skipped the pad is tolerated only when the padded position holds no chunk header
    and the unpadded one does.
    """
    if not size & 1:
        return end
    if not _is_chunk_header_at(f, end + 1, total) and _is_chunk_header_at(
        f, end, total
    ):
        return end
    return end + 1


def iter_riff_chunks(
    f: BinaryIO, *, forms=RIFF_FORMS
) -> "Iterator[tuple[bytes, int, int]]":
    """``(chunk_id, offset, size)`` for each top-level chunk of a RIFF / RF64 / BW64 WAVE.

    Walks the chunk headers with seeks, never reading the audio, so a large file costs
    a few small reads. Stops quietly at a truncated chunk. For RF64 / BW64, a ``data``
    chunk sized ``0xFFFFFFFF`` takes its real size from ``ds64``'s ``dataSize``.

    >>> import io
    >>> body = b"WAVE" + b"abcd" + struct.pack("<I", 1) + b"x\\0"
    >>> wav = io.BytesIO(b"RIFF" + struct.pack("<I", len(body)) + body)
    >>> list(iter_riff_chunks(wav))
    [(b'abcd', 20, 1)]
    """
    total = f.seek(0, 2)
    f.seek(0)
    head = f.read(12)
    if len(head) < 12 or head[:4] not in forms or head[8:12] != b"WAVE":
        return
    pos, data_size = 12, None
    while pos + 8 <= total:
        f.seek(pos)
        header = f.read(8)
        chunk_id, (size,) = header[:4], struct.unpack("<I", header[4:])
        if chunk_id == b"data" and size == _SIZE_PLACEHOLDER and data_size is not None:
            size = data_size
        if pos + 8 + size > total:
            return
        if chunk_id == b"ds64" and size >= _DS64_DATA_SIZE_AT + 8:
            f.seek(pos + 8 + _DS64_DATA_SIZE_AT)
            (data_size,) = struct.unpack("<Q", f.read(8))
        yield chunk_id, pos + 8, size
        pos = _next_chunk_at(f, pos + 8 + size, size, total)


# --------------------------------------------------------------------------------------
# Chunk parsers
# --------------------------------------------------------------------------------------


def _decode_text(data: bytes) -> str:
    """Strict UTF-8, else Latin-1 (which decodes any bytes)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_bext(payload: bytes) -> "dict[str, str]":
    """The text fields of a ``bext`` chunk (NUL-padded; UTF-8 or Latin-1), non-empty only."""
    out, pos = {}, 0
    for name, width in BEXT_FIELDS:
        text = _decode_text(payload[pos : pos + width].split(b"\0", 1)[0]).strip()
        if text:
            out[name] = text
        pos += width
    return out


def _xml_document(payload: bytes) -> bytes:
    """An iXML payload's XML bytes: up to the first NUL character (a NUL code unit in UTF-16)."""
    if payload[:2] not in _UTF16_BOMS:
        return payload.split(b"\0", 1)[0].strip()
    end = payload.find(b"\0\0")
    while end != -1 and end % 2:
        end = payload.find(b"\0\0", end + 1)
    return payload if end == -1 else payload[:end]


def parse_ixml_user(payload: bytes) -> "dict[str, str]":
    """The ``<USER>`` fields of an iXML chunk (upper-cased tag -> text), or ``{}``.

    The bytes go to the XML parser as they are, so the document's own encoding
    declaration (UTF-8, Latin-1, UTF-16, ...) is honoured.
    """
    try:
        root = ET.fromstring(_xml_document(payload))
    except (ET.ParseError, LookupError, ValueError):
        return {}
    user = next((el for el in root if el.tag.upper() == "USER"), None)  # or <user>
    if user is None:
        return {}
    pairs = ((child.tag.upper(), "".join(child.itertext()).strip()) for child in user)
    return {tag: text for tag, text in pairs if text}


#: Chunk id -> (its name in ``raw`` and :data:`FIELDS`, its parser).
CHUNK_PARSERS = {b"bext": (BEXT, parse_bext), b"iXML": (IXML, parse_ixml_user)}


# --------------------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------------------


def read_metadata_chunks(
    path, *, max_chunk_bytes: int = MAX_METADATA_CHUNK_BYTES, parsers=CHUNK_PARSERS
) -> "dict[str, dict[str, str]]":
    """The parsed, non-empty metadata chunks of a WAV (``{"bext": ..., "ixml": ...}``).

    Chunks larger than ``max_chunk_bytes`` are skipped unread.
    """
    raw = {}
    with open(path, "rb") as f:
        for chunk_id, offset, size in iter_riff_chunks(f):
            if chunk_id in parsers and size <= max_chunk_bytes:
                name, parse = parsers[chunk_id]
                f.seek(offset)
                raw[name] = parse(f.read(size))
    return {name: fields for name, fields in raw.items() if fields}


def read_embedded_metadata(
    path, *, max_chunk_bytes: int = MAX_METADATA_CHUNK_BYTES, fields=FIELDS
) -> dict:
    """foley's view of a WAV's ``bext`` and iXML metadata (see the module docs), or ``{}``.

    >>> read_embedded_metadata(__file__)  # not a WAV
    {}
    """
    raw = read_metadata_chunks(path, max_chunk_bytes=max_chunk_bytes)
    if not raw:
        return {}
    return {**fields_from_chunks(raw, fields=fields), "raw": raw}
