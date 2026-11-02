"""Broadcast-WAV bext + iXML metadata as caption and tags (#228).

The fixtures are built here, chunk by chunk: no commercial pack's bytes in the repo.
"""

import io
import struct
import time

import pytest

from foley.embedded_metadata import (
    FIELDS,
    chunks_from_fields,
    fields_from_chunks,
    iter_riff_chunks,
    read_embedded_metadata,
    write_embedded_metadata,
)


def _chunk(chunk_id: bytes, payload: bytes, *, pad=True) -> bytes:
    tail = b"\0" if pad and len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + tail


def _bext(description="", originator="", *, encoding="latin-1") -> bytes:
    fields = [
        (description, 256),
        (originator, 32),
        ("", 32),
        ("2024-01-02", 10),
        ("", 8),
    ]
    head = b"".join(text.encode(encoding).ljust(width, b"\0") for text, width in fields)
    return head + b"\0" * (602 - len(head))  # the rest of the v1 layout


def _ixml(*, encoding="UTF-8", user_tag="USER", **user) -> bytes:
    tags = "".join(f"<{k}>{v}</{k}>" for k, v in user.items())
    doc = f'<?xml version="1.0" encoding="{encoding}"?><BWFXML><{user_tag}>{tags}</{user_tag}></BWFXML>'
    return doc.encode(encoding)


def _wav(*chunks: bytes, form=b"RIFF") -> bytes:
    fmt = _chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16))
    body = b"WAVE" + fmt + b"".join(chunks)
    return form + struct.pack("<I", len(body)) + body


DATA = _chunk(b"data", b"\0\0" * 480)


def _read(tmp_path, content: bytes, **kwargs) -> dict:
    f = tmp_path / "x.wav"
    f.write_bytes(content)
    return read_embedded_metadata(f, **kwargs)


def test_ixml_user_fields_win_and_keywords_become_tags(tmp_path):
    meta = _read(tmp_path, _wav(
        _chunk(b"bext", _bext("bext says a door", "BOOM Library")), DATA,
        _chunk(b"iXML", _ixml(DESCRIPTION="Old oak door creaks open slowly", FXNAME="Creak",
                              CATID="DOORWood", KEYWORDS="door, creak; Wood ,DOOR", LIBRARY="Doors 2")),
    ))  # fmt: skip
    # iXML DESCRIPTION first; no iXML MANUFACTURER, so bext Originator
    assert meta["caption"] == "Old oak door creaks open slowly"
    assert meta["manufacturer"] == "BOOM Library"
    assert [meta[k] for k in ("fx_name", "ucs_catid", "library")] == [
        "Creak",
        "DOORWood",
        "Doors 2",
    ]
    assert meta["tags"] == ["door", "creak", "Wood"]  # de-duplicated ignoring case
    assert meta["raw"]["bext"]["origination_date"] == "2024-01-02"


def test_bext_alone_gives_the_caption(tmp_path):
    meta = _read(tmp_path, _wav(_chunk(b"bext", _bext("Rain on a tin roof")), DATA))
    assert meta["caption"] == "Rain on a tin roof" and "tags" not in meta


@pytest.mark.parametrize("encoding", ["utf-8", "latin-1"])
def test_bext_text_is_utf8_else_latin1(tmp_path, encoding):
    meta = _read(tmp_path, _wav(_chunk(b"bext", _bext("Café door", encoding=encoding))))
    assert meta["caption"] == "Café door"


@pytest.mark.parametrize("encoding", ["ISO-8859-1", "UTF-16"])
def test_ixml_honours_its_own_encoding_declaration(tmp_path, encoding):
    payload = (
        _ixml(encoding=encoding, DESCRIPTION="Café door", KEYWORDS="café") + b"\0\0\0\0"
    )
    meta = _read(tmp_path, _wav(_chunk(b"iXML", payload)))
    assert (meta["caption"], meta["tags"]) == ("Café door", ["café"])


def test_lowercase_user_block_and_nested_text(tmp_path):
    payload = _ixml(user_tag="user", fxname="Slam <b>hard</b>")
    assert _read(tmp_path, _wav(_chunk(b"iXML", payload)))["fx_name"] == "Slam hard"


def test_metadata_chunks_over_the_cap_are_skipped(tmp_path):
    content = _wav(_chunk(b"iXML", _ixml(DESCRIPTION="x" * 5000)))
    assert _read(tmp_path, content, max_chunk_bytes=4096) == {}
    assert _read(tmp_path, content)["caption"] == "x" * 5000


BILLION_LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    + b"".join(
        b'<!ENTITY lol%d "%s">'
        % (i, (b"&lol%d;" % (i - 1) if i > 1 else b"&lol;") * 10)
        for i in range(1, 10)
    )
    + b"]><BWFXML><USER><DESCRIPTION>&lol9;</DESCRIPTION></USER></BWFXML>"
)
XXE = (
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    b"<BWFXML><USER><DESCRIPTION>&xxe;</DESCRIPTION></USER></BWFXML>"
)


@pytest.mark.parametrize(
    "payload", [BILLION_LAUGHS, XXE], ids=["billion-laughs", "xxe"]
)
def test_xml_attacks_give_nothing_quickly(tmp_path, payload):
    start = time.perf_counter()
    assert _read(tmp_path, _wav(_chunk(b"iXML", payload))) == {}
    assert time.perf_counter() - start < 2


@pytest.mark.parametrize(
    "content",
    [
        _wav(DATA),
        b"fLaC\0\0\0\x22" + b"\0" * 40,
        b"",
        _wav(_chunk(b"iXML", b"<not xml")),
        _wav(_chunk(b"iXML", b'<?xml version="1.0" encoding="bogus"?><BWFXML/>')),
        _wav(DATA, _chunk(b"bext", _bext("cut off")))[:-300],  # the bext chunk is cut
    ],
    ids=[
        "no-chunks",
        "not-a-wav",
        "empty",
        "bad-ixml",
        "unknown-encoding",
        "truncated-bext",
    ],
)
def test_anything_else_is_quietly_empty(tmp_path, content):
    assert _read(tmp_path, content) == {}


def test_a_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_embedded_metadata(tmp_path / "missing.wav")


@pytest.mark.parametrize("form", [b"RF64", b"BW64"])
def test_rf64_takes_the_data_size_from_ds64(tmp_path, form):
    """The data chunk says 0xFFFFFFFF; its size is ds64's dataSize, not sampleCount."""
    frames = 1001
    audio = struct.pack(f"<{frames}h", *range(-500, 501))  # 2002 bytes, non-zero
    ds64 = _chunk(b"ds64", struct.pack("<QQQI", 0, len(audio), frames, 0))
    big_data = b"data" + struct.pack("<I", 0xFFFFFFFF) + audio
    ixml = _ixml(FXNAME="Rumble")
    assert len(ixml) % 2  # an odd-length tail chunk, so its pad byte matters
    body = _wav(ds64, big_data, _chunk(b"iXML", ixml), form=form)[8:]
    content = form + struct.pack("<I", 0xFFFFFFFF) + body

    chunks = list(iter_riff_chunks(io.BytesIO(content)))
    data_at = 12 + (8 + 16) + (8 + 28) + 8
    assert chunks == [
        (b"fmt ", 20, 16),
        (b"ds64", 44, 28),
        (b"data", data_at, len(audio)),
        (b"iXML", data_at + len(audio) + 8, len(ixml)),
    ]
    assert _read(tmp_path, content)["caption"] == "Rumble"


@pytest.mark.parametrize("pad", [True, False], ids=["padded", "unpadded-writer"])
def test_chunks_after_an_odd_one_are_found_with_or_without_the_pad(tmp_path, pad):
    odd = _chunk(b"junk", b"abc", pad=pad)
    meta = _read(tmp_path, _wav(odd, _chunk(b"iXML", _ixml(FXNAME="Thud")), DATA))
    assert meta["fx_name"] == "Thud"


def test_the_field_table_round_trips(tmp_path):
    """What the writer (#231) puts where FIELDS says reads back as the same fields."""
    meta = {
        "caption": "Old oak door creaks", "tags": ["door", "creak"], "fx_name": "Creak",
        "ucs_catid": "DOORWood", "ucs_category": "DOORS", "ucs_subcategory": "WOOD",
        "library": "Doors 2", "manufacturer": "BOOM Library", "designer": "JD",
        "license": "cc-by-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": '"Creak" by JD, CC BY 4.0',
    }  # fmt: skip
    assert set(meta) == {fld.name for fld in FIELDS}
    chunks = chunks_from_fields(meta)
    # the caption is copied into bext Description
    assert set(chunks) == {"ixml", "bext"}
    assert chunks["bext"] == {"description": meta["caption"]}
    assert fields_from_chunks(chunks) == meta
    read = _read(tmp_path, write_embedded_metadata(_wav(DATA), meta))
    assert {k: v for k, v in read.items() if k != "raw"} == meta


def test_a_real_encoder_file_with_injected_chunks(tmp_path):
    """A WAV written by soundfile, then given a bext chunk after its data, still reads."""
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    f = tmp_path / "real.wav"
    sf.write(f, np.zeros(1000, dtype="float32"), 48000, subtype="PCM_16")
    raw = f.read_bytes() + _chunk(b"bext", _bext("Tone"))
    f.write_bytes(raw[:4] + struct.pack("<I", len(raw) - 8) + raw[8:])
    assert read_embedded_metadata(f)["caption"] == "Tone"


def test_a_utf8_description_cut_at_the_field_width_stays_utf8(tmp_path):
    """bext Description is 256 bytes: a UTF-8 character cut there must not turn the field into mojibake."""
    desc = (
        "a" + "é" * 128
    ).encode()  # 257 bytes: the field's 256 cut the last é in half
    payload = desc[:256] + b"\0" * (602 - 256)
    f = tmp_path / "cut.wav"
    f.write_bytes(_wav(_chunk(b"bext", payload), DATA))
    assert read_embedded_metadata(f)["caption"] == "a" + "é" * 127


# ---------------------------------------------------------------------------
# The writer (#231)
# ---------------------------------------------------------------------------


def _chunks(wav: bytes) -> "list[tuple[bytes, int, int]]":
    return list(iter_riff_chunks(io.BytesIO(wav)))


def _payload(wav: bytes, chunk_id: bytes) -> bytes:
    (at, size), *_ = [(at, size) for cid, at, size in _chunks(wav) if cid == chunk_id]
    return wav[at : at + size]


def _assert_well_formed(wav: bytes):
    assert wav[:4] == b"RIFF" and struct.unpack("<I", wav[4:8])[0] == len(wav) - 8
    listed = _chunks(wav)
    assert all(at % 2 == 0 for _, at, _ in listed)  # word-aligned
    last_id, last_at, last_size = listed[-1]
    # nothing lost or left over
    assert last_at + last_size + (last_size & 1) == len(wav)


def test_writing_keeps_the_audio_bytes_and_soundfile_reads_the_file(tmp_path):
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    buf = io.BytesIO()
    samples = (np.arange(1001) % 200 - 100).astype("int16")
    sf.write(buf, samples, 48000, format="WAV", subtype="PCM_16")
    plain = buf.getvalue()
    meta = {"caption": "A door creaks", "tags": ["door"], "ucs_catid": "DOORWood"}
    wav = write_embedded_metadata(plain, meta)
    _assert_well_formed(wav)
    assert _payload(wav, b"data") == _payload(plain, b"data")
    np.testing.assert_array_equal(sf.read(io.BytesIO(wav), dtype="int16")[0], samples)
    read = read_embedded_metadata(wav)  # bytes are read as well as paths
    assert (read["caption"], read["tags"], read["ucs_catid"]) == (
        "A door creaks",
        ["door"],
        "DOORWood",
    )
    ids = [cid for cid, _, _ in _chunks(wav)]
    assert ids.index(b"bext") < ids.index(b"data") and ids.index(b"iXML") < ids.index(
        b"data"
    )


def test_existing_chunks_are_rewritten_in_place_and_keep_what_is_not_written():
    ixml = _ixml(LIBRARY="Doors 2", DESCRIPTION="old")
    ixml = ixml.replace(
        b"<USER>", b"<SPEED><TIMECODE_RATE>25/1</TIMECODE_RATE></SPEED><USER>"
    )
    src = _wav(
        _chunk(b"bext", _bext("old", "BOOM Library")), DATA, _chunk(b"iXML", ixml)
    )
    wav = write_embedded_metadata(src, {"caption": "new", "fx_name": "Creak"})
    _assert_well_formed(wav)
    assert [cid for cid, _, _ in _chunks(wav)] == [b"fmt ", b"bext", b"data", b"iXML"]
    read = read_embedded_metadata(wav)
    assert read["raw"]["bext"] == {
        "description": "new",
        "originator": "BOOM Library",
        "origination_date": "2024-01-02",
    }
    assert read["raw"]["ixml"] == {
        "LIBRARY": "Doors 2",
        "DESCRIPTION": "new",
        "FXNAME": "Creak",
    }
    assert b"<TIMECODE_RATE>25/1</TIMECODE_RATE>" in _payload(wav, b"iXML")


def test_duplicate_metadata_chunks_collapse_to_one():
    src = _wav(
        _chunk(b"iXML", _ixml(FXNAME="a")), DATA, _chunk(b"iXML", _ixml(FXNAME="b"))
    )
    wav = write_embedded_metadata(src, {"caption": "c"})
    assert [cid for cid, _, _ in _chunks(wav)].count(b"iXML") == 1
    assert read_embedded_metadata(wav)["raw"]["ixml"] == {
        "FXNAME": "b",
        "DESCRIPTION": "c",
    }


def test_an_odd_sized_chunk_is_padded():
    wav = write_embedded_metadata(_wav(DATA), {"fx_name": "x" * 8})  # odd iXML payload
    _assert_well_formed(wav)
    assert len(_payload(wav, b"iXML")) % 2 == 1


def test_a_long_utf8_caption_is_cut_safely_in_bext_and_whole_in_ixml():
    caption = "a" + "é" * 200  # 401 bytes
    read = read_embedded_metadata(
        write_embedded_metadata(_wav(DATA), {"caption": caption})
    )
    assert read["caption"] == caption  # iXML DESCRIPTION, read first
    assert read["raw"]["bext"]["description"] == "a" + "é" * 127  # 255 bytes, no half é


def test_nothing_to_write_returns_the_bytes_untouched():
    src = _wav(DATA)
    assert write_embedded_metadata(src, {"caption": "", "tags": []}) is src


@pytest.mark.parametrize(
    "wav, match",
    [
        (_wav(DATA, form=b"RF64"), "RIFF WAVE"),
        (b"fLaC" + b"\0" * 40, "RIFF WAVE"),
        (_wav(), "truncated"),
    ],
)
def test_what_the_writer_refuses(wav, match):
    with pytest.raises(ValueError, match=match):
        write_embedded_metadata(wav, {"caption": "x"})


def _write(src: bytes, meta: dict, **kwargs) -> "tuple[bytes, list[str]]":
    notes = []
    return write_embedded_metadata(src, meta, report=notes.append, **kwargs), notes


def test_cleared_fields_are_removed_from_an_existing_ixml():
    src = _wav(
        DATA, _chunk(b"iXML", _ixml(LICENSE_URL="https://vendor/eula", LIBRARY="L"))
    )
    wav, notes = _write(
        src, {"license": "cc-by-nc-4.0"}, clear=["license", "license_url"]
    )
    assert read_embedded_metadata(wav)["raw"]["ixml"] == {
        "LIBRARY": "L",
        "LICENSE": "cc-by-nc-4.0",
    }
    assert notes == []
    # a removal alone does not create a chunk the file lacks
    assert _write(_wav(DATA), {}, clear=["license"])[0] == _wav(DATA)


def test_bytes_after_the_declared_riff_end_are_not_folded_in():
    src = _wav(DATA) + _chunk(b"iXML", _ixml(FXNAME="outside"))  # RIFF size not updated
    assert read_embedded_metadata(src) == {}
    wav, notes = _write(src, {"caption": "c"})
    _assert_well_formed(wav)
    assert read_embedded_metadata(wav)["raw"]["ixml"] == {"DESCRIPTION": "c"}
    assert notes and "dropped" in notes[0]


def test_what_the_writer_cannot_keep_is_reported():
    broken = _wav(DATA, _chunk(b"iXML", b"<BWFXML><USER>"))
    wav, notes = _write(broken, {"caption": "c"})
    assert read_embedded_metadata(wav)["caption"] == "c" and "did not parse" in notes[0]
    dupes = _wav(
        _chunk(b"iXML", _ixml(FXNAME="a")), DATA, _chunk(b"iXML", _ixml(FXNAME="b"))
    )
    assert "collapsed" in _write(dupes, {"caption": "c"})[1][0]
    big = _wav(DATA, _chunk(b"iXML", _ixml(FXNAME="a" * 64)))
    notes = []
    from foley.embedded_metadata import chunks_from_fields, write_metadata_chunks

    write_metadata_chunks(big, chunks_from_fields({"caption": "c"}), max_chunk_bytes=16,
                          report=notes.append)  # fmt: skip
    assert "replaced, not merged" in notes[0]
