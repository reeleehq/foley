"""Broadcast-WAV bext + iXML metadata as caption and tags (#228).

The fixtures are built here, chunk by chunk: no commercial pack's bytes in the repo.
"""

import struct

import pytest

from foley.index.embedded_metadata import read_embedded_metadata


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    pad = b"\0" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + pad


def _bext(description="", originator="") -> bytes:
    fields = [(description, 256), (originator, 32), ("", 32), ("2024-01-02", 10), ("", 8)]
    head = b"".join(text.encode("latin-1").ljust(width, b"\0") for text, width in fields)
    return head + b"\0" * (602 - len(head))  # the rest of the v1 layout


def _ixml(**user) -> bytes:
    tags = "".join(f"<{k}>{v}</{k}>" for k, v in user.items())
    return f'<?xml version="1.0" encoding="UTF-8"?><BWFXML><USER>{tags}</USER></BWFXML>'.encode()


def _wav(*chunks: bytes, form=b"RIFF") -> bytes:
    fmt = _chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16))
    body = b"WAVE" + fmt + b"".join(chunks)
    return form + struct.pack("<I", len(body)) + body


DATA = _chunk(b"data", b"\0\0" * 480)


def test_ixml_user_fields_win_and_keywords_become_tags(tmp_path):
    f = tmp_path / "DOORWood_Creak_JD_NYC.wav"
    f.write_bytes(_wav(
        _chunk(b"bext", _bext("bext says a door", "BOOM Library")), DATA,
        _chunk(b"iXML", _ixml(DESCRIPTION="Old oak door creaks open slowly", FXNAME="Creak",
                              CATID="DOORWood", KEYWORDS="door, creak; Wood ,", LIBRARY="Doors 2")),
    ))  # fmt: skip
    meta = read_embedded_metadata(f)
    assert meta["caption"] == "Old oak door creaks open slowly"  # iXML DESCRIPTION first
    assert (meta["fx_name"], meta["catid"], meta["library"]) == ("Creak", "DOORWood", "Doors 2")
    assert meta["manufacturer"] == "BOOM Library"  # no iXML MANUFACTURER: bext Originator
    assert meta["tags"] == ["door", "creak", "wood"]
    assert meta["raw"]["bext"]["origination_date"] == "2024-01-02"


def test_bext_alone_gives_the_caption(tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(_wav(_chunk(b"bext", _bext("Rain on a tin roof")), DATA))
    meta = read_embedded_metadata(f)
    assert meta["caption"] == "Rain on a tin roof" and meta["tags"] == []


@pytest.mark.parametrize(
    "content",
    [
        _wav(DATA),
        b"fLaC\0\0\0\x22" + b"\0" * 40,
        b"",
        _wav(_chunk(b"iXML", b"<not xml")),
        _wav(DATA, _chunk(b"bext", _bext("cut off")))[:-300],  # the bext chunk is cut
    ],
    ids=["no-chunks", "not-a-wav", "empty", "bad-ixml", "truncated-bext"],
)
def test_anything_else_is_quietly_empty(tmp_path, content):
    f = tmp_path / "x.wav"
    f.write_bytes(content)
    assert read_embedded_metadata(f) == {}
    assert read_embedded_metadata(tmp_path / "missing.wav") == {}


def test_rf64_takes_the_data_size_from_ds64(tmp_path):
    """An RF64 file's data chunk says 0xFFFFFFFF; iXML after it is still found."""
    data = b"\0\0" * 480
    ds64 = _chunk(b"ds64", struct.pack("<QQQI", 0, len(data), 0, 0))
    big_data = b"data" + struct.pack("<I", 0xFFFFFFFF) + data
    f = tmp_path / "big.wav"
    f.write_bytes(_wav(ds64, big_data, _chunk(b"iXML", _ixml(FXNAME="Rumble")), form=b"RF64"))
    assert read_embedded_metadata(f)["caption"] == "Rumble"


def test_a_real_encoder_file_with_injected_chunks(tmp_path):
    """A WAV written by soundfile, then given a bext chunk after its data, still reads."""
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    f = tmp_path / "real.wav"
    sf.write(f, np.zeros(1000, dtype="float32"), 48000, subtype="PCM_16")
    raw = f.read_bytes() + _chunk(b"bext", _bext("Tone"))
    f.write_bytes(raw[:4] + struct.pack("<I", len(raw) - 8) + raw[8:])
    assert read_embedded_metadata(f)["caption"] == "Tone"
