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
    assert (lic.license_id, lic.rights_holder, lic.license_name) == ("owned-pack", "Sonniss", "GDC 2024")
    assert lic.source == "licensed_library" and lic.source_id is None
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
        ('license = "made-up"', "is unknown"),
        ('license = "unknown"', "cannot be asserted"),
        ('license = "PDM-1.0"', "cannot be asserted"),  # a claim, not a grant
        ('license = "ElevenLabs-SFX"', "cannot be asserted"),
        ('licensor = "x"', "is unknown"),  # no license at all
        ('license = "owned-pack"\nprice = 99', r"unknown keys \['price'\]"),
        ('license = "owned-pack"\nai_training = "yes"', r"wrong types \['ai_training'\]"),
        ("license = ", "cannot read it as toml"),
    ],
)
def test_an_invalid_sidecar_is_refused(tmp_path, text, match):
    (tmp_path / "foley-license.toml").write_text(text)
    with pytest.raises(SidecarError, match=match):
        read_sidecar(tmp_path / "foley-license.toml")


def test_ai_training_can_only_narrow(tmp_path):
    import foley

    (tmp_path / "foley-license.toml").write_text('license = "Sonniss-GDC"\nai_training = true')
    lic = sidecar_license(tmp_path)
    assert lic.ai_training_ok is False  # the EULA forbids it; a sidecar cannot unlock it
    assert not foley.keep(lic, foley.IntendedUse(will_train=True))
    (tmp_path / "foley-license.toml").write_text('license = "CC0-1.0"\nai_training = false')
    assert sidecar_license(tmp_path).ai_training_ok is False  # narrowed below the row
    (tmp_path / "foley-license.toml").write_text('license = "CC0-1.0"')
    assert sidecar_license(tmp_path).ai_training_ok is True  # the row's own grant


def test_the_search_stays_inside_root(tmp_path):
    lib, outside = tmp_path / "lib", tmp_path / "outside"
    (lib / "pack").mkdir(parents=True)
    outside.mkdir()
    (tmp_path / "foley-license.toml").write_text('license = "CC0-1.0"')  # above the root
    (outside / "x.wav").write_bytes(b"")
    (lib / "pack" / "link.wav").symlink_to(outside / "x.wav")
    with pytest.raises(SidecarError, match="not under the library root"):
        find_sidecar(outside / "x.wav", root=lib)
    # a symlink is walked where it is listed, not where it points
    assert find_sidecar(lib / "pack" / "link.wav", root=lib) is None


def test_ambiguous_or_unreadable_sidecars_are_refused(tmp_path):
    (tmp_path / "foley-license.toml").write_text('license = "CC0-1.0"')
    (tmp_path / "foley-license.json").write_text('{"license": "owned-pack"}')
    with pytest.raises(SidecarError, match="expected one sidecar"):
        find_sidecar(tmp_path / "a.wav")
    sub = tmp_path / "sub"
    (sub / "foley-license.toml").mkdir(parents=True)  # a folder by that name
    with pytest.raises(SidecarError, match="expected one sidecar"):
        find_sidecar(sub / "a.wav", root=sub)
    bad = tmp_path / "bad" / "foley-license.toml"
    bad.parent.mkdir()
    bad.write_bytes(b"license = \"\xff\xfe\"")  # not UTF-8
    with pytest.raises(SidecarError, match="cannot read"):
        sidecar_license(bad.parent, root=bad.parent)
    bom = tmp_path / "bom" / "foley-license.json"
    bom.parent.mkdir()
    bom.write_bytes(b'\xef\xbb\xbf{"license": "CC0-1.0"}')  # a BOM is fine
    assert sidecar_license(bom.parent, root=bom.parent).license_id == "CC0-1.0"


def test_keep_takes_an_owned_pack_for_publishing_and_refuses_training(tmp_path):
    import foley

    (tmp_path / "foley-license.toml").write_text(PACK)
    lic = sidecar_license(tmp_path)
    assert foley.keep(lic, foley.IntendedUse(commercial=True))
    assert not foley.keep(lic, foley.IntendedUse(will_train=True))
    assert not foley.keep(lic, foley.IntendedUse(redistribute_standalone=True))
