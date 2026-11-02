"""What a pro sound file says about itself: Broadcast-WAV ``bext`` and iXML (#228, #231).

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

:func:`write_embedded_metadata` is the other direction (#231): it puts foley's fields
into a RIFF WAV's ``bext`` and ``iXML`` chunks, replacing the fields it writes and
keeping the rest of each chunk, and leaves the audio bytes as they are.

:data:`FIELDS` is the one table between the chunks and foley's names, both ways: each
:class:`Field` has a canonical ``write`` location (where an exporter puts the value,
and where a reader looks first) and ordered ``read_also`` fallbacks, plus the
``decode`` / ``encode`` pair between the stored text and foley's value.
:func:`fields_from_chunks` and :func:`chunks_from_fields` are its two directions, so
the writer of #231 reuses the table rather than inverting it. The names are foley's
(``caption``, ``tags``, ``ucs_*`` as on :class:`~foley.base.SoundRecord` /
:class:`~foley.base.SoundEvent`, ``fx_name`` as on the UCS filename parse, and
``license`` / ``license_url`` / ``attribution`` as in the rights dict of
:func:`foley.export_sound`).

The caption is also written to bext ``Description`` (cut to its 256 bytes on a
character boundary): DAWs and most library tools (Pro Tools, BaseHead, Soundly) show
the BWF Description, while the iXML ``DESCRIPTION`` keeps the whole caption and is read
first, so a long caption still reads back whole.

This module sits beside :mod:`foley.audio` rather than in :mod:`foley.index`: it is
file-format I/O that both ingest (reading) and export (writing) use, stdlib-only.
"""

from __future__ import annotations

import io
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, Iterator, Mapping, Optional

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

#: The size of a ``bext`` chunk's fixed part (EBU Tech 3285), before its CodingHistory.
BEXT_FIXED_BYTES = 602

#: The root and ``<USER>`` tags of a new iXML document, and the iXML version it states.
IXML_ROOT, IXML_USER, IXML_VERSION = "BWFXML", "USER", "1.61"

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


def unique_words(words) -> "list[str]":
    """``words`` stripped, without blanks or repeats (ignoring case), first spelling kept.

    >>> unique_words([" door", "DOOR", None, "", "creak"])
    ['door', 'creak']
    """
    seen, out = set(), []
    for word in (w.strip() for w in words if w):
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            out.append(word)
    return out


def split_keywords(text: str) -> "list[str]":
    """Keywords from a ``KEYWORDS`` string: split on , and ;, de-duplicated ignoring case.

    >>> split_keywords("door, creak; Wood ,DOOR")
    ['door', 'creak', 'Wood']
    """
    return unique_words(KEYWORD_SEPARATORS.split(text))


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
    looks there first. ``write_also`` are copies a writer also fills (for tools that
    read only there), read next. ``read_also`` are read-only fallbacks, tried in order.
    ``decode`` turns the stored text into foley's value; ``encode`` turns it back.
    """

    name: str
    write: Location
    read_also: "tuple[Location, ...]" = ()
    decode: Callable[[str], Any] = str
    encode: Callable[[Any], str] = str
    write_also: "tuple[Location, ...]" = ()

    @property
    def write_to(self) -> "tuple[Location, ...]":
        """Every location a writer fills: the canonical one, then its copies."""
        return (self.write, *self.write_also)

    @property
    def read_from(self) -> "tuple[Location, ...]":
        """Every location a reader tries: where it is written, then the fallbacks."""
        return (*self.write_to, *self.read_also)


#: foley field <-> chunk locations (see :class:`Field`).
FIELDS: "tuple[Field, ...]" = (
    Field(
        "caption",
        Location(IXML, "DESCRIPTION"),
        write_also=(Location(BEXT, "description"),),
        read_also=(Location(IXML, "FXNAME"),),
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
    Field("license", Location(IXML, "LICENSE")),
    Field("license_url", Location(IXML, "LICENSE_URL")),
    Field("attribution", Location(IXML, "ATTRIBUTION")),
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


def chunks_from_fields(
    meta: Mapping, *, fields=FIELDS, clear=()
) -> "dict[str, dict[str, Optional[str]]]":
    """Where a writer puts each of foley's fields: ``{chunk: {key: text}}`` (``write_to``).

    A field named in ``clear`` that ``meta`` has no value for maps to ``None``: the
    writer removes it, so a file never keeps a stale value of a field the caller owns.

    >>> chunks_from_fields({"caption": "Rain", "tags": ["a", "b"], "other": 1})
    {'ixml': {'DESCRIPTION': 'Rain', 'KEYWORDS': 'a, b'}, 'bext': {'description': 'Rain'}}
    >>> chunks_from_fields({"license": None}, clear=["license"])
    {'ixml': {'LICENSE': None}}
    """
    out: "dict[str, dict[str, Optional[str]]]" = {}
    for fld in fields:
        text = fld.encode(meta[fld.name]) if meta.get(fld.name) else ""
        value = text or (None if fld.name in clear else "")
        for loc in fld.write_to if value != "" else ():
            out.setdefault(loc.chunk, {})[loc.key] = value
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
    f: BinaryIO, *, forms=RIFF_FORMS, stop_at_declared_end: bool = False
) -> "Iterator[tuple[bytes, int, int]]":
    """``(chunk_id, offset, size)`` for each top-level chunk of a RIFF / RF64 / BW64 WAVE.

    Walks the chunk headers with seeks, never reading the audio, so a large file costs
    a few small reads. Stops quietly at a truncated chunk. ``stop_at_declared_end``
    also stops at the RIFF's declared end when that is inside the file: a writer must
    not fold trailing bytes into the WAVE, while a reader keeps going, since many files
    understate their RIFF size and still carry ``bext`` / iXML after it. For RF64 /
    BW64, a ``data`` chunk sized ``0xFFFFFFFF`` takes its real size from ``ds64``'s
    ``dataSize``.

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
    declared_end = 8 + struct.unpack("<I", head[4:8])[0]
    if stop_at_declared_end and 12 < declared_end < total:
        total = declared_end
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


#: The most bytes a fixed-width field can cut off the end of one UTF-8 character.
_UTF8_TAIL = 3


def _decode_text(data: bytes, *, may_be_cut: bool = False) -> str:
    """Strict UTF-8, else Latin-1 (which decodes any bytes).

    ``may_be_cut``: the bytes filled their fixed-width field, so a UTF-8 character
    may have been cut at the end; drop up to :data:`_UTF8_TAIL` bytes before giving up
    on UTF-8. Off otherwise, since a Latin-1 ``é`` (``0xE9``) also looks like a cut lead.

    >>> _decode_text("café".encode()[:-1], may_be_cut=True), _decode_text("café".encode("latin-1"))
    ('caf', 'café')
    """
    for cut in range(_UTF8_TAIL + 1 if may_be_cut else 1):
        try:
            return data[: len(data) - cut].decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < len(data) - _UTF8_TAIL:  # not a cut tail: not UTF-8
                break
    return data.decode("latin-1")


def parse_bext(payload: bytes) -> "dict[str, str]":
    """The text fields of a ``bext`` chunk (NUL-padded; UTF-8 or Latin-1), non-empty only."""
    out, pos = {}, 0
    for name, width in BEXT_FIELDS:
        field = payload[pos : pos + width]
        text = _decode_text(
            field.split(b"\0", 1)[0], may_be_cut=b"\0" not in field
        ).strip()
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
    user = next((el for el in root if el.tag.upper() == IXML_USER), None)  # or <user>
    if user is None:
        return {}
    pairs = ((child.tag.upper(), "".join(child.itertext()).strip()) for child in user)
    return {tag: text for tag, text in pairs if text}


#: Chunk id -> (its name in ``raw`` and :data:`FIELDS`, its parser).
CHUNK_PARSERS = {b"bext": (BEXT, parse_bext), b"iXML": (IXML, parse_ixml_user)}


# --------------------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------------------


def _open_wav(src) -> BinaryIO:
    """A binary file object over ``src``: a path, or the WAV's bytes."""
    if isinstance(src, (bytes, bytearray, memoryview)):
        return io.BytesIO(src)
    return open(src, "rb")


def read_metadata_chunks(
    path, *, max_chunk_bytes: int = MAX_METADATA_CHUNK_BYTES, parsers=CHUNK_PARSERS
) -> "dict[str, dict[str, str]]":
    """The parsed, non-empty metadata chunks of a WAV (``{"bext": ..., "ixml": ...}``).

    ``path`` is a file path or the WAV's bytes. Chunks larger than ``max_chunk_bytes``
    are skipped unread. A file that is not a WAV gives ``{}``; one that cannot be
    opened (missing, a directory, no permission) raises the ``OSError``, so a wrong
    path is not mistaken for a file without metadata.
    """
    raw = {}
    with _open_wav(path) as f:
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

    ``path`` is a file path or the WAV's bytes.

    >>> read_embedded_metadata(__file__)  # not a WAV
    {}
    """
    raw = read_metadata_chunks(path, max_chunk_bytes=max_chunk_bytes)
    if not raw:
        return {}
    return {**fields_from_chunks(raw, fields=fields), "raw": raw}


# --------------------------------------------------------------------------------------
# Chunk builders and the writer (#231)
# --------------------------------------------------------------------------------------


def _fixed_width(text: str, width: int) -> bytes:
    """``text`` as UTF-8 in ``width`` bytes, NUL-padded, cut before a character that
    would not fit whole.

    >>> _fixed_width("café", 4), _fixed_width("ab", 4)
    (b'caf\\x00', b'ab\\x00\\x00')
    """
    cut = text.encode("utf-8")[:width].decode("utf-8", "ignore")
    return cut.encode("utf-8").ljust(width, b"\0")


def _ignore(note: str) -> None:
    """The default ``report``: drop the note."""


def build_bext(
    fields: "Mapping[str, Optional[str]]",
    *,
    base: bytes = b"",
    report: Callable[[str], Any] = _ignore,
) -> bytes:
    """A ``bext`` payload with ``fields`` (:data:`BEXT_FIELDS` names) written over ``base``.

    ``base`` is the file's existing ``bext`` payload, so what foley does not write (the
    time reference, UMID, loudness, CodingHistory) is kept; with none, the rest is
    zero (version 0: no UMID). Text is UTF-8 (ASCII is a subset), cut on a character
    boundary at the field's width; a ``None`` value empties its field. ``report`` is
    accepted for the builder protocol (nothing in a ``bext`` is ever lost).

    >>> parse_bext(build_bext({"description": "Rain"}))
    {'description': 'Rain'}
    """
    offsets, pos = {}, 0
    for name, width in BEXT_FIELDS:
        offsets[name], pos = (pos, width), pos + width
    unknown = set(fields) - set(offsets)
    if unknown:
        raise ValueError(f"not bext text fields: {sorted(unknown)}")
    payload = bytearray(base.ljust(BEXT_FIXED_BYTES, b"\0"))
    for name, text in fields.items():
        at, width = offsets[name]
        payload[at : at + width] = _fixed_width(text or "", width)
    return bytes(payload)


def _ixml_root(base: bytes, report: Callable[[str], Any]) -> ET.Element:
    """The iXML document of ``base`` (comments and processing instructions kept) to
    write into, or a new one if it has none, or one that does not parse (reported)."""
    if _xml_document(base):
        builder = ET.TreeBuilder(insert_comments=True, insert_pis=True)
        try:
            return ET.fromstring(_xml_document(base), ET.XMLParser(target=builder))
        except (ET.ParseError, LookupError, ValueError) as exc:
            report(f"the existing iXML did not parse ({exc}) and was replaced")
    root = ET.Element(IXML_ROOT)
    ET.SubElement(root, "IXML_VERSION").text = IXML_VERSION
    return root


def _child(parent: ET.Element, tag: str) -> "Optional[ET.Element]":
    """``parent``'s first child element tagged ``tag`` (ignoring case), or ``None``."""
    wanted = tag.upper()
    match = (c for c in parent if isinstance(c.tag, str) and c.tag.upper() == wanted)
    return next(match, None)


def build_ixml(
    fields: "Mapping[str, Optional[str]]",
    *,
    base: bytes = b"",
    report: Callable[[str], Any] = _ignore,
) -> bytes:
    """An iXML payload (UTF-8) with ``fields`` as ``<USER>`` children, written into ``base``.

    ``base`` is the file's existing iXML payload: its other elements, its comments,
    and the ``<USER>`` fields not in ``fields``, are kept; a ``None`` value removes
    its field. A ``base`` that does not parse is replaced, and ``report`` told.

    >>> parse_ixml_user(build_ixml({"CATID": "DOORWood", "FXNAME": "Creak & slam"}))
    {'CATID': 'DOORWood', 'FXNAME': 'Creak & slam'}
    """
    root = _ixml_root(base, report)
    user = _child(root, IXML_USER)
    if user is None:
        user = ET.SubElement(root, IXML_USER)
    for key, text in fields.items():
        while text is None and (old := _child(user, key)) is not None:
            user.remove(old)
        if text is None:
            continue
        el = _child(user, key)
        if el is None:
            el = ET.SubElement(user, key)
        el.clear()
        el.text = text
    doc = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{doc}'.encode("utf-8")


#: Chunk name (as in :data:`FIELDS` and ``raw``) -> (its chunk id, its builder).
CHUNK_BUILDERS = {BEXT: (b"bext", build_bext), IXML: (b"iXML", build_ixml)}

#: A metadata chunk the file does not have yet is inserted before this one.
INSERT_BEFORE = b"data"


def _chunk_bytes(chunk_id: bytes, payload: bytes) -> bytes:
    """A chunk: header, payload and the pad byte that word-aligns an odd payload."""
    pad = b"\0" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + pad


def write_metadata_chunks(
    wav: bytes,
    chunks: "Mapping[str, Mapping[str, Optional[str]]]",
    *,
    builders=CHUNK_BUILDERS,
    max_chunk_bytes: int = MAX_METADATA_CHUNK_BYTES,
    report: Callable[[str], Any] = _ignore,
) -> bytes:
    """``wav`` (RIFF WAVE bytes) with ``chunks`` (``{"bext": {...}, "ixml": {...}}``) written.

    A chunk the file has is rewritten in place (the first of its kind; any others are
    dropped, since a reader would see two), keeping what ``chunks`` does not set (a
    ``None`` value removes its field); one it lacks is inserted before ``data``, unless
    all it would hold is removals. Every other chunk, ``data`` included, is copied
    byte for byte; the RIFF size is recomputed and odd chunks are padded.

    What is lost is told to ``report`` (one sentence each): duplicate chunks, an
    existing chunk over ``max_chunk_bytes`` (replaced, not merged), an iXML that does
    not parse (replaced), and bytes after the last whole chunk or the RIFF's
    declared end (dropped).

    Raises:
        ValueError: ``wav`` is not a RIFF WAVE (RF64 / BW64 are refused: their sizes
            live in ``ds64``), has no whole ``data`` chunk, would outgrow RIFF's
            4 GB, or ``chunks`` names a chunk with no builder.
    """
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError(
            f"only RIFF WAVE files take metadata here, not a {bytes(wav[:4])!r} file"
        )
    unknown = set(chunks) - set(builders)
    if unknown:
        raise ValueError(f"no builder for chunks {sorted(unknown)}")
    listed = list(
        iter_riff_chunks(io.BytesIO(wav), forms=(b"RIFF",), stop_at_declared_end=True)
    )
    present = {chunk_id for chunk_id, _, _ in listed}
    if INSERT_BEFORE not in present:
        raise ValueError(f"no whole {INSERT_BEFORE!r} chunk: the file is truncated")
    new = {}
    for name, values in chunks.items():
        chunk_id, build = builders[name]
        if chunk_id not in present and all(v is None for v in values.values()):
            continue  # nothing to remove from a chunk the file does not have
        sizes = [(at, size) for cid, at, size in listed if cid == chunk_id]
        if len(sizes) > 1:
            report(
                f"{len(sizes)} {chunk_id.decode()} chunks were collapsed into one "
                f"(the last one's fields kept)"
            )
        if sizes and sizes[-1][1] > max_chunk_bytes:
            report(
                f"the existing {chunk_id.decode()} chunk ({sizes[-1][1]} bytes) is over "
                f"{max_chunk_bytes} bytes and was replaced, not merged"
            )
        # the last of its kind is the base: a reader sees that one
        at, size = sizes[-1] if sizes and sizes[-1][1] <= max_chunk_bytes else (0, 0)
        new[chunk_id] = build(values, base=wav[at : at + size], report=report)
    _, last_at, last_size = listed[-1]
    if len(wav) > last_at + last_size + (last_size & 1):
        dropped = len(wav) - last_at - last_size - (last_size & 1)
        report(f"{dropped} bytes after the WAVE's last whole chunk were dropped")
    out, written = [], set()
    for chunk_id, at, size in listed:
        if chunk_id == INSERT_BEFORE:
            out += [_chunk_bytes(c, p) for c, p in new.items() if c not in present]
        if chunk_id not in new:
            out.append(_chunk_bytes(chunk_id, wav[at : at + size]))
        elif chunk_id not in written:
            out.append(_chunk_bytes(chunk_id, new[chunk_id]))
            written.add(chunk_id)
    body = b"WAVE" + b"".join(out)
    if len(body) >= _SIZE_PLACEHOLDER:
        raise ValueError("the file would outgrow RIFF's 4 GB; it needs RF64")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def write_embedded_metadata(
    wav: bytes,
    meta: Mapping,
    *,
    fields=FIELDS,
    clear=(),
    report: Callable[[str], Any] = _ignore,
) -> bytes:
    """``wav`` with foley's fields ``meta`` written where :data:`FIELDS` says (``bext``
    and ``iXML``): the inverse of :func:`read_embedded_metadata`.

    Fields named in ``clear`` that ``meta`` has no value for are removed from the file
    (see :func:`chunks_from_fields`). ``wav`` comes back unchanged when there is
    nothing to write. See :func:`write_metadata_chunks` for what is kept, what is
    refused and what is told to ``report``.
    """
    chunks = chunks_from_fields(meta, fields=fields, clear=clear)
    return write_metadata_chunks(wav, chunks, report=report) if chunks else wav
