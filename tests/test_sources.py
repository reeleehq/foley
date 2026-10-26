"""Tests for the bulk-corpus source adapters (``foley.sources``).

Dependency-light: adapters only enumerate + license clips (no decode/embed), so
these tests need neither numpy nor an audio codec — corpus dirs are built from
empty ``.wav`` placeholder files (the walk matches on suffix, never decodes) plus
small metadata files.
"""

import json
from pathlib import Path

from foley.base import AcquisitionMethod
from foley.bootstrap import COMMERCIAL_USE
from foley.licensing import keep
from foley.sources import (
    CORPUS_REGISTRY,
    ClipSpec,
    select_corpora,
)
from foley.sources.bbc_remarc import BBC_REMARC
from dataclasses import replace

from foley.sources.clotho import CLOTHO

#: Clotho with its (non-commercial) captions opted in — the eval-only configuration.
CLOTHO_WITH_CAPTIONS = replace(CLOTHO, include_captions=True)
from foley.sources.foleyset import FOLEYSET
from foley.sources.fsd50k import FSD50K, _license_id_from_url
from foley.sources.sonniss import SONNISS


def _touch_wavs(directory, names):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"")  # placeholder; adapters never decode


# ---------------------------------------------------------------------------
# registry + ring selection
# ---------------------------------------------------------------------------


def test_registry_has_all_corpora_with_expected_rings():
    assert set(CORPUS_REGISTRY) == {
        "fsd50k",
        "clotho",
        "foleyset",
        "sonniss",
        "bbc_remarc",
    }
    assert {n: a.ring for n, a in CORPUS_REGISTRY.items()} == {
        "fsd50k": 1,
        "clotho": 0,
        "foleyset": 0,
        "sonniss": 2,
        "bbc_remarc": 2,
    }


def test_default_rings_exclude_ring2():
    names = {a.name for a in select_corpora(rings=(0, 1))}
    assert names == {"clotho", "foleyset", "fsd50k"}
    assert "sonniss" not in names and "bbc_remarc" not in names


def test_explicit_corpora_allowlist_overrides_rings():
    assert [a.name for a in select_corpora(corpora=["sonniss"])] == ["sonniss"]


# ---------------------------------------------------------------------------
# CC-URL -> license_id mapping (fail-closed)
# ---------------------------------------------------------------------------


def test_license_id_from_url_maps_cc_families():
    assert _license_id_from_url("http://creativecommons.org/publicdomain/zero/1.0/") == (
        "CC0-1.0",
        True,
    )
    assert _license_id_from_url("https://creativecommons.org/licenses/by/4.0/") == (
        "CC-BY-4.0",
        True,
    )
    # the version is kept (#56): a 3.0 clip is credited as 3.0
    assert _license_id_from_url("http://creativecommons.org/licenses/by/3.0/") == (
        "CC-BY-3.0",
        True,
    )
    # by-nc must be recognized BEFORE the bare 'by'
    assert _license_id_from_url("https://creativecommons.org/licenses/by-nc/4.0/") == (
        "CC-BY-NC-4.0",
        True,
    )
    assert _license_id_from_url("http://creativecommons.org/licenses/sampling+/1.0/") == (
        "CC-Sampling+-1.0",
        True,
    )


def test_license_id_from_url_unknown_is_fail_closed():
    assert _license_id_from_url(None) == ("unknown", False)
    assert _license_id_from_url("http://example.com/whatever") == ("unknown", False)
    # licenses foley has no row for must fail closed (dropped), never mis-map to CC-BY:
    # by-sa / by-nd are NOT in LICENSE_FLAGS and must NOT match the bare 'by' branch.
    assert _license_id_from_url("https://creativecommons.org/licenses/by-sa/4.0/") == (
        "unknown",
        False,
    )
    assert _license_id_from_url("https://creativecommons.org/licenses/by-nd/4.0/") == (
        "unknown",
        False,
    )


def test_license_id_from_url_nd_sa_variants_fail_closed():
    # Hardened in #5 (was CC-BY-NC-4.0): by-nc-nd / by-nc-sa (and bare by-nd / by-sa)
    # have NO foley LICENSE_FLAGS row, so mapping them to CC-BY-NC-4.0 fail-OPEN'd —
    # CC-BY-NC grants modification / derivative / standalone-redistribution rights
    # that ND/SA forbid, which keep() would admit for a non-commercial derivative
    # use. They now map to ('unknown', False): still dropped from commercial use (as
    # before), and now also rejected for derivative/redistribution use (fail-closed).
    for url in (
        "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "https://creativecommons.org/licenses/by-nd/4.0/",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ):
        assert _license_id_from_url(url) == ("unknown", False)
    # the plain by-nc (no ND/SA) still maps to CC-BY-NC-4.0 (a row we DO have)
    assert _license_id_from_url("https://creativecommons.org/licenses/by-nc/4.0/") == (
        "CC-BY-NC-4.0",
        True,
    )


# ---------------------------------------------------------------------------
# FSD50K per-clip licensing
# ---------------------------------------------------------------------------


def _fsd50k_corpus(tmp_path):
    """A synthetic FSD50K tree: clips-info JSON + 4 placeholder wavs."""
    info = {
        "111": {"license": "http://creativecommons.org/publicdomain/zero/1.0/", "uploader": "zoe"},
        "222": {"license": "https://creativecommons.org/licenses/by/4.0/", "uploader": "amy"},
        "333": {"license": "https://creativecommons.org/licenses/by-nc/4.0/", "uploader": "ben"},
        # 444 deliberately absent from metadata -> fail-closed unknown
    }
    meta_dir = tmp_path / "FSD50K.metadata"
    meta_dir.mkdir(parents=True)
    (meta_dir / "dev_clips_info_FSD50K.json").write_text(json.dumps(info))
    _touch_wavs(tmp_path / "FSD50K.dev_audio", ["111.wav", "222.wav", "333.wav", "444.wav"])
    return tmp_path


def test_fsd50k_resolves_per_clip_license(tmp_path):
    root = _fsd50k_corpus(tmp_path)
    by_id = {s.source_id: FSD50K.resolve_license(s) for s in FSD50K.iter_clips(str(root))}
    assert set(by_id) == {"111", "222", "333", "444"}

    cc0 = by_id["111"]
    assert cc0.license_id == "CC0-1.0"
    assert cc0.rights_verified is True
    assert cc0.commercial_ok and cc0.cache_bytes_ok and cc0.ai_training_ok
    assert cc0.acquisition_method == AcquisitionMethod.bulk
    assert cc0.creator_name == "zoe"
    assert cc0.source_url == "https://freesound.org/s/111/"

    ccby = by_id["222"]
    assert ccby.license_id == "CC-BY-4.0"
    assert ccby.requires_attribution is True
    assert ccby.creator_name == "amy"

    ccbync = by_id["333"]
    assert ccbync.license_id == "CC-BY-NC-4.0"
    assert ccbync.commercial_ok is False

    unknown = by_id["444"]  # absent from metadata -> fail-closed
    assert unknown.license_id == "unknown"
    assert unknown.rights_verified is False
    assert unknown.commercial_ok is False and unknown.ai_training_ok is False


def test_keep_commercial_filter_admits_cc0_ccby_drops_the_rest(tmp_path):
    root = _fsd50k_corpus(tmp_path)
    verdicts = {
        s.source_id: keep(FSD50K.resolve_license(s), COMMERCIAL_USE)
        for s in FSD50K.iter_clips(str(root))
    }
    assert verdicts == {"111": True, "222": True, "333": False, "444": False}


# ---------------------------------------------------------------------------
# uniform-license corpora
# ---------------------------------------------------------------------------


def test_foleyset_uniform_ccby_with_path_tag_hints(tmp_path):
    root = tmp_path / "foleyset"
    _touch_wavs(root / "Footsteps" / "Gravel", ["a.wav"])
    specs = list(FOLEYSET.iter_clips(str(root)))
    assert len(specs) == 1
    assert specs[0].meta["tag_hints"] == ["Footsteps", "Gravel"]
    lic = FOLEYSET.resolve_license(specs[0])
    assert lic.license_id == "CC-BY-4.0"
    assert lic.rights_verified is True
    assert lic.acquisition_method == AcquisitionMethod.bulk
    assert lic.cache_bytes_ok is True  # bulk download -> by-value


def test_clotho_injects_human_captions(tmp_path):
    root = tmp_path / "clotho"
    _touch_wavs(root, ["clip_a.wav", "clip_b.wav"])
    (root / "clotho_captions_evaluation.csv").write_text(
        "file_name,caption_1,caption_2\n"
        "clip_a.wav,a dog barks loudly,another caption\n"
        "clip_b.wav,,rain falls steadily\n"  # first caption empty -> use caption_2
    )
    by_name = {Path(s.path).name: s for s in CLOTHO_WITH_CAPTIONS.iter_clips(str(root))}
    assert by_name["clip_a.wav"].meta["caption"] == "a dog barks loudly"
    assert by_name["clip_b.wav"].meta["caption"] == "rain falls steadily"


def test_clotho_captions_survive_bom_and_non_utf8(tmp_path):
    # A BOM-prefixed header must not orphan the file_name column, and a non-UTF-8
    # (latin-1) caption export must degrade — never raise UnicodeDecodeError and
    # abort the whole ingest (the loader promises "degrade, don't raise").
    root = tmp_path / "clotho"
    _touch_wavs(root, ["clip_a.wav", "clip_b.wav"])
    # BOM + a valid header/row for clip_a
    (root / "bom_captions.csv").write_bytes(
        "﻿file_name,caption_1\nclip_a.wav,a dog barks loudly\n".encode("utf-8")
    )
    # latin-1 bytes for clip_b (0xe9 = é) — invalid UTF-8
    (root / "latin1_captions.csv").write_bytes(
        "file_name,caption_1\nclip_b.wav,cafe\xe9 ambience\n".encode("latin-1")
    )
    by_name = {Path(s.path).name: s for s in CLOTHO_WITH_CAPTIONS.iter_clips(str(root))}
    # BOM did not orphan the header -> caption resolved
    assert by_name["clip_a.wav"].meta.get("caption") == "a dog barks loudly"
    # latin-1 file did not crash; clip_b got some caption mentioning ambience
    assert "ambience" in by_name["clip_b.wav"].meta.get("caption", "")


# ---------------------------------------------------------------------------
# Ring-2 corpora carry the hard flags
# ---------------------------------------------------------------------------


def test_sonniss_forbids_ai_training_but_is_commercial():
    lic = SONNISS.resolve_license(ClipSpec(path="x.wav", source_id="x"))
    assert lic.license_id == "Sonniss-GDC"
    assert lic.ai_training_ok is False
    assert lic.commercial_ok is True
    assert lic.cache_bytes_ok is True  # user may keep a local copy; not embed+persist


def test_bbc_remarc_forbids_commercial_and_ai_training():
    lic = BBC_REMARC.resolve_license(ClipSpec(path="x.wav", source_id="x"))
    assert lic.license_id == "RemArc"
    assert lic.commercial_ok is False
    assert lic.ai_training_ok is False


# ---------------------------------------------------------------------------
# capabilities + list_backends + ledger (#60)
# ---------------------------------------------------------------------------
def SOURCE(name):
    from foley.sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    return SOURCE_REGISTRY[name]["config"]


def test_list_backends_supports_seed_and_kind():
    import foley

    seeded = foley.list_backends(supports="seed")
    assert "stable_audio" in seeded and "stable_audio_3" in seeded
    assert "elevenlabs" not in seeded and "freesound" not in seeded
    assert foley.list_backends(kind="retrieve", supports="seed") == []
    assert "freesound" in foley.list_backends(kind="retrieve")
    both = foley.list_backends(supports=["seed", "negative_prompt"])
    assert "stable_audio" in both and "fal_mirelo" in both
    assert "fal_sonilo" not in foley.list_backends(supports="seed")
    assert foley.list_backends(supports="offline_capable") == ["stable_audio", "stable_audio_3"]
    assert foley.capabilities_of(SOURCE("freesound"))["deterministic"] is None
    assert foley.capabilities_of(SOURCE("stable_audio_3"))["sample_rate"] == 44100


def test_list_backends_rejects_typos_and_derived_overrides():
    import pytest

    import foley

    for bad in ({"supports": "seeed"}, {"kind": "genrate"}, {"supports": "kind"}):
        with pytest.raises(ValueError):
            foley.list_backends(**bad)
    with pytest.raises(ValueError, match="derived"):
        foley.capabilities_of({"name": "x", "capabilities": {"kind": "retrieve"}})


def test_list_backends_flags_and_fake():
    import foley
    from foley.sources.registry import SOURCE_REGISTRY, register_source

    register_source(
        "fake_capab",
        {
            "name": "fake_capab",
            "kind": "generate",
            "data_egress": "local",
            "supported_affordances": ["prompt", "loop"],
            "native_defaults": {"sample_rate": 16000},
            "capabilities": {"watermarked": True},
        },
        adapter=object(),
    )
    try:
        view = foley.capabilities_of(SOURCE_REGISTRY["fake_capab"]["config"])
        assert view["loopable"] and view["offline_capable"] and not view["deterministic"]
        assert view["sample_rate"] == 16000
        assert "fake_capab" in foley.list_backends(supports=["loopable", "watermarked"])
        assert "fake_capab" in foley.list_backends(supports="loop")
        assert "fake_capab" not in foley.list_backends(supports="deterministic")
    finally:
        SOURCE_REGISTRY.pop("fake_capab", None)


def test_ledger_computes_planned_from_registry():
    import foley

    led = foley.ledger()
    assert "stable_audio" in led["implemented"]
    assert {t["name"] for t in led["planned"]} >= {"epidemic_sound"}
    assert not {t["name"] for t in led["planned"]} & set(led["implemented"])
    # a planned target that is now registered drops out of 'planned'
    led = foley.ledger(targets=[{"name": "freesound", "kind": "retrieve", "note": ""}])
    assert led["planned"] == []
    assert foley.ledger(targets=[])["planned"] == []
    assert foley.capability_report()["backends"]["implemented"]
