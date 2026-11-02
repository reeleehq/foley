"""``format_ucs_name``: the inverse of ``parse_ucs_name`` (#231).

A seeded property test (no hypothesis dependency): for random blocks, including
underscores, hyphens, dots, path characters, vendor-looking heads and FXNames like
``Sci-Fi Door``, format -> parse -> format is stable and the parse gives back the
formatted blocks.
"""

import random
import re

import pytest

from foley.index.taxonomy import (
    UCS_NAME_BLOCKS,
    default_ucs_table,
    format_ucs_name,
    load_ucs_master,
    parse_ucs_name,
)

_PIECES = ["Sci-Fi", "Door", "BOOM-", "-", "_", " ", ".", ".wav", "5.1", "a/b", "é",
           "UFO", "x", "Creak", "  ", "\t", ":", "Hand-Held", "SFX2", "ab_cd"]  # fmt: skip


def _text(rng: random.Random):
    if rng.random() < 0.2:
        return None
    return "".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 4)))


def _random_blocks(rng: random.Random) -> dict:
    catid = rng.choice(default_ucs_table().order)
    blocks = {k: _text(rng) for k in UCS_NAME_BLOCKS}
    blocks["catid"] = rng.choice([catid, catid.lower(), catid.upper()])
    if rng.random() < 0.5:
        blocks["vendor_category"] = None
    return blocks


_PLAIN = re.compile(r"[A-Za-z0-9 ]*[A-Za-z0-9]")


def _plain_blocks(blocks: dict) -> dict:
    """The blocks that need no sanitising (letters, digits, inner spaces), whitespace
    collapsed: those must parse back exactly as given."""
    plain = {}
    for key in ("user_category", "fx_name", "creator_id", "source_id", "user_data"):
        text = " ".join(str(blocks[key] or "").split())
        if _PLAIN.fullmatch(text) and not (
            key == "fx_name" and blocks["vendor_category"]
        ):
            plain[key] = text
    return plain


@pytest.mark.parametrize("ext", [None, "wav"])
def test_format_parse_format_is_stable(ext):
    rng = random.Random(231)
    checked = 0
    for _ in range(3000):
        blocks = _random_blocks(rng)
        try:
            first = format_ucs_name(blocks, ext=ext)
        # a VendorCategory that cannot be read back, or with no FXName
        except ValueError:
            assert blocks["vendor_category"] is not None
            continue
        name = parse_ucs_name(first)
        assert name is not None, first
        again = format_ucs_name(name, ext=ext)
        assert again == first, (blocks, first, again)
        assert parse_ucs_name(again) == name
        for key, value in _plain_blocks(blocks).items():  # contents survive
            assert getattr(name, key) == value, (key, blocks, first)
        checked += 1
    assert checked > 2000


def test_hyphenated_fx_names_and_vendor_tags_round_trip():
    plain = format_ucs_name(catid="DOORWood", fx_name="Sci-Fi Door", creator_id="JD",
                            source_id="NYC", ext="wav")  # fmt: skip
    assert plain == "DOORWood_Sci-Fi Door_JD_NYC.wav"
    n = parse_ucs_name(plain)
    assert (n.vendor_category, n.fx_name) == (None, "Sci-Fi Door")
    vendored = format_ucs_name(n, vendor_category="boom", ext="wav")
    assert vendored == "DOORWood_BOOM-Sci-Fi Door_JD_NYC.wav"
    m = parse_ucs_name(vendored)
    assert (m.vendor_category, m.fx_name) == ("BOOM", "Sci-Fi Door")
    # without a vendor, a head that reads as a vendor tag loses its hyphen
    assert format_ucs_name(catid="DOORWood", fx_name="UFO-Hum") == "DOORWood_UFO Hum"


def test_blocks_are_sanitised_and_user_data_keeps_its_underscores():
    name = format_ucs_name(catid="DOORWood", user_category="Gate_A", fx_name="Slam/Bang_2",
                           creator_id="J_D", source_id="", user_data="fs_12345", ext=".wav")  # fmt: skip
    assert name == "DOORWood-Gate A_Slam Bang 2_J D__fs_12345.wav"
    parsed = parse_ucs_name(name)
    assert (parsed.source_id, parsed.user_data) == (None, "fs_12345")


def test_a_trailing_extension_lookalike_is_unmade_in_a_stem():
    stem = format_ucs_name(catid="DOORWood", fx_name="Door v.Two")
    assert (
        stem == "DOORWood_Door v Two" and parse_ucs_name(stem).fx_name == "Door v Two"
    )


def test_the_catid_must_be_in_the_table():
    with pytest.raises(ValueError, match="not a CatID"):
        # a master CatID, not in the seed
        format_ucs_name(catid="WOODHndl", fx_name="x")
    master = load_ucs_master()
    name = format_ucs_name(catid="woodhndl", fx_name="x", table=master)
    assert (
        name == "WOODHndl_x" and parse_ucs_name(name, table=master).catid == "WOODHndl"
    )
    with pytest.raises(ValueError, match="not a CatID"):
        format_ucs_name(fx_name="x")


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"colour": "red"}, TypeError),
        ({"ext": "tar.gz"}, ValueError),
        ({"vendor_category": "123"}, ValueError),
        ({"vendor_category": "BOOM", "fx_name": None}, ValueError),
    ],
)
def test_what_format_refuses(kwargs, error):
    with pytest.raises(error):
        format_ucs_name({"catid": "DOORWood", "fx_name": "x"}, **kwargs)


def test_a_long_name_is_cut_on_character_boundaries_and_stays_stable():
    rng = random.Random(4)
    for _ in range(300):
        blocks = _random_blocks(rng) | {"vendor_category": None}
        blocks["creator_id"] = "é" * rng.randint(0, 200)
        blocks["fx_name"] = "Sci-Fi " * rng.randint(0, 60)
        blocks["user_data"] = "keep_me"
        first = format_ucs_name(blocks, ext="wav", max_bytes=120)
        assert len(first.encode()) <= 120
        name = parse_ucs_name(first)
        assert name.user_data == "keep_me"
        assert format_ucs_name(name, ext="wav", max_bytes=120) == first
    with pytest.raises(ValueError, match="cannot be cut"):
        format_ucs_name(catid="DOORWood", user_data="x" * 300)
