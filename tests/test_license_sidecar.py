"""The per-folder licence sidecar for owned sound packs (#229)."""

import json

import pytest

from foley.index.license_sidecar import (
    SidecarError,
    find_sidecar,
    read_sidecar,
    sidecar_license,
)

PACK = """
license = "owned-pack"
licensor = "Sonniss"
pack = "GDC 2024"
attribution = "Sound effects: Sonniss GDC 2024"
"""


def _tree(tmp_path):
    """root/pack (sidecar) with a nested folder that overrides it, and a bare folder."""
    pack = tmp_path / "pack"
    (pack / "doors").mkdir(parents=True)
    (pack / "cc0").mkdir()
    (tmp_path / "bare").mkdir()
    (pack / "foley-license.toml").write_text(PACK)
    (pack / "cc0" / "foley-license.json").write_text(json.dumps({"license": "CC0-1.0"}))
    for f in (pack / "doors" / "a.wav", pack / "cc0" / "b.wav", tmp_path / "bare" / "c.wav"):
        f.write_bytes(b"")
    return pack


def test_a_file_takes_the_nearest_sidecar(tmp_path):
    pack = _tree(tmp_path)
    lic = sidecar_license(pack / "doors" / "a.wav", root=tmp_path)
    assert (lic.license_id, lic.rights_holder, lic.source_id) == ("owned-pack", "Sonniss", "GDC 2024")
    assert lic.rights_verified and lic.verified_at and lic.attribution_text
    assert (lic.commercial_ok, lic.redistribute_standalone_ok, lic.ai_training_ok) == (True, False, False)
    assert sidecar_license(pack / "cc0" / "b.wav", root=tmp_path).license_id == "CC0-1.0"


def test_no_sidecar_is_refused_not_guessed(tmp_path):
    _tree(tmp_path)
    with pytest.raises(SidecarError, match="does not guess"):
        sidecar_license(tmp_path / "bare" / "c.wav", root=tmp_path)
    # root bounds the search: a sidecar above it is not inherited
    (tmp_path / "foley-license.toml").write_text('license = "user-owned"')
    assert find_sidecar(tmp_path / "bare" / "c.wav", root=tmp_path / "bare") is None
    assert find_sidecar(tmp_path / "bare" / "c.wav", root=tmp_path).name == "foley-license.toml"


@pytest.mark.parametrize(
    "text, match",
    [
        ('license = "made-up"', "not a licence foley knows"),
        ('license = "unknown"', "not a licence foley knows"),
        ('licensor = "x"', "not a licence foley knows"),  # no license at all
        ('license = "owned-pack"\nprice = 99', r"unknown keys \['price'\]"),
        ('license = "owned-pack"\nai_training = "yes"', r"wrong types \['ai_training'\]"),
        ("license = ", "not valid toml"),
    ],
)
def test_an_invalid_sidecar_is_refused(tmp_path, text, match):
    (tmp_path / "foley-license.toml").write_text(text)
    with pytest.raises(SidecarError, match=match):
        read_sidecar(tmp_path / "foley-license.toml")


def test_ai_training_is_what_the_sidecar_says(tmp_path):
    (tmp_path / "foley-license.toml").write_text('license = "owned-pack"\nai_training = true')
    assert sidecar_license(tmp_path).ai_training_ok is True
    (tmp_path / "foley-license.toml").write_text('license = "CC0-1.0"\nai_training = false')
    assert sidecar_license(tmp_path).ai_training_ok is False  # narrowed below the row


def test_keep_takes_an_owned_pack_for_publishing_and_refuses_training(tmp_path):
    import foley

    (tmp_path / "foley-license.toml").write_text(PACK)
    lic = sidecar_license(tmp_path)
    assert foley.keep(lic, foley.IntendedUse(commercial=True))
    assert not foley.keep(lic, foley.IntendedUse(will_train=True))
    assert not foley.keep(lic, foley.IntendedUse(redistribute_standalone=True))
