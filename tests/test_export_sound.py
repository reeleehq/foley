"""``foley.export_sound``: a sound's bytes + ``lacing.Rights``-shaped rights + provenance (#66).

The three sounds of the issue's acceptance -- a Freesound CC0, an FSD50K CC BY and a
Stable Audio clip (AI, revenue-capped) -- plus the fail-closed refusal of a sound whose
bytes may not be kept, and the sha256 chain from the FLAC archive to the exported WAV.
The ``lacing`` / ``an`` checks skip when those packages are absent: foley never imports
them, the dict field names are the contract.
"""

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import io  # noqa: E402

import foley  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.base import AcquisitionMethod, LicenseRecord, SoundRecord  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.licensing import (  # noqa: E402
    LICENSE_EXCLUDED_TERRITORIES,
    LICENSE_FLAGS,
    REVENUE_CAP,
    TERRITORY_EXCLUDED,
    LICENSE_TERMS_PROVIDER,
    LicenseRefusal,
    apply_license_flags,
    consumer_license_code,
    narrow_to_source,
)
from foley.provenance import (  # noqa: E402
    ASSET_SOURCE_EXTRAS,
    PROVENANCE_FIELDS,
    RIGHTS_FIELDS,
    id_from_user_data,
    id_to_user_data,
    sound_rights,
)
from foley.sources.base import generated_license  # noqa: E402
from foley.stores import content_key  # noqa: E402

SR = 48_000


def _flac(freq: float, *, dur: float = 0.25) -> bytes:
    t = np.linspace(0.0, dur, int(SR * dur), endpoint=False)
    return encode((0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR)


def _freesound_cc0() -> SoundRecord:
    # Freesound-like and cacheable (a website download / a dataset copy). A Freesound
    # API pull is by-reference and refused: see test_by_reference_sound_is_refused.
    lic = apply_license_flags(
        LicenseRecord(
            source="freesound",
            source_id="12345",
            source_url="https://freesound.org/s/12345/",
            creator_name="alice",
            license_id="CC0-1.0",
            rights_verified=True,
        )
    )
    return SoundRecord(id="fs-12345", license=lic, caption="rain on window")


def _fsd50k_cc_by() -> SoundRecord:
    lic = apply_license_flags(
        LicenseRecord(
            source="fsd50k",
            source_id="222",
            source_url="https://freesound.org/s/222/",
            creator_name="amy",
            creator_url="https://freesound.org/people/amy/",
            license_id="CC-BY-4.0",
            acquisition_method=AcquisitionMethod.bulk,
            rights_verified=True,
        )
    )
    return SoundRecord(id="fsd-222", license=lic, tags=["door", "creak"])


def _stable_audio() -> SoundRecord:
    lic = generated_license(
        source="stable_audio",
        license_id="Stability-Community",
        generator_model="stable-audio-open-1.0",
        generation_prompt="a wooden door creak",
        generation_seed=7,
    )
    return SoundRecord(id="sa-7", license=lic, caption="a wooden door creak")


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    lib = SoundLibrary(
        sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder
    )
    for i, rec in enumerate((_freesound_cc0(), _fsd50k_cc_by(), _stable_audio())):
        lib.add(rec, data=_flac(300 + 100 * i))
    return lib


THREE = ("fs-12345", "fsd-222", "sa-7")


# ---------------------------------------------------------------------------
# bytes + the sha256 chain
# ---------------------------------------------------------------------------


def test_wav_export_keeps_the_samples_and_chains_both_hashes(library):
    data, _rights, prov = foley.export_sound("fsd-222", library=library)
    archived = library.audio("fsd-222")
    assert data[:4] == b"RIFF" and prov["format"] == "wav"
    assert prov["subtype"] == sf.info(io.BytesIO(archived)).subtype == "PCM_24"
    assert prov["sha256"] == content_key(data)
    assert (
        prov["archived_sha256"]
        == content_key(archived)
        == library["fsd-222"].content_sha256
    )
    assert prov["foley_id"] == "fsd-222"
    as_int = lambda b: sf.read(io.BytesIO(b), dtype="int32")[0]  # noqa: E731
    np.testing.assert_array_equal(as_int(data), as_int(archived))  # sample-exact


def test_exporting_the_archive_format_returns_the_archived_bytes(library):
    data, _rights, prov = foley.export_sound("fs-12345", "flac", library=library)
    assert data == library.audio("fs-12345")
    assert prov["sha256"] == prov["archived_sha256"]


def test_bytes_that_no_longer_match_their_record_are_refused(library):
    library.sounds[library["fs-12345"].content_sha256] = _flac(999)
    with pytest.raises(ValueError, match="changed since ingest"):
        foley.export_sound("fs-12345", library=library)


def test_by_reference_sound_is_refused(library):
    lic = apply_license_flags(
        LicenseRecord(source="freesound", license_id="CC0-1.0", rights_verified=True),
        overrides={"cache_bytes_ok": False},  # the Freesound API's terms
    )
    rec = SoundRecord(id="fs-api", license=lic, uri="https://freesound.org/s/9/")
    library.add(rec, data=_flac(500))
    with pytest.raises(LicenseRefusal, match="stored by reference") as err:
        foley.export_sound("fs-api", library=library)
    assert set(err.value.refused) == {"fs-api"}


# ---------------------------------------------------------------------------
# rights: Rights field names, consumer-classifiable codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sound_id", THREE)
def test_rights_use_exactly_the_rights_field_names(library, sound_id):
    _data, rights, _prov = foley.export_sound(sound_id, library=library)
    # only the Stability clip has a restriction (its cap); without one it is left out
    assert set(rights) | {"restrictions"} == set(RIGHTS_FIELDS)
    assert ("restrictions" in rights) == (sound_id == "sa-7")
    assert rights["cacheable"] is True
    assert all(v is None or v != "" for v in rights.values())


def test_freesound_cc0_rights(library):
    _data, rights, prov = foley.export_sound("fs-12345", library=library)
    assert rights["provider"] == "freesound" and rights["id"] == "12345"
    assert rights["license"] == "cc0-1.0"
    assert rights["author"] == "alice" and rights["title"] == "rain on window"
    assert rights["source_page_url"] == "https://freesound.org/s/12345/"
    assert prov["ai_disclosure"] is None


def test_fsd50k_cc_by_rights(library):
    _data, rights, prov = foley.export_sound("fsd-222", library=library)
    assert rights["license"] == "cc-by-4.0"
    assert rights["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert rights["author_url"] == "https://freesound.org/people/amy/"
    assert '"Door creak" by amy' in rights["attribution"]
    assert prov["flags"]["requires_attribution"] is True


def test_stable_audio_rights_carry_ai_disclosure_and_revenue_cap(library):
    _data, rights, prov = foley.export_sound("sa-7", library=library)
    # the terms' owner, under the name a consumer classifies its code by
    assert rights["provider"] == "stability-ai"
    assert rights["license"] == "stability-community"
    assert "AI-generated with stable-audio-open-1.0" in rights["attribution"]
    assert rights["author"] is None  # no creator: the source is not an author
    assert prov["source"] == "stable_audio"
    assert prov["flags"]["revenue_cap_usd"] == 1_000_000
    assert prov["flags"]["ai_training_ok"] is False
    ai = prov["ai_disclosure"]
    assert ai["is_ai_generated"] is True
    assert ai["provenance"]["generator_model"] == "stable-audio-open-1.0"
    assert ai["provenance"]["generation_seed"] == 7


def test_unverified_rights_export_as_unknown(library):
    lic = apply_license_flags(LicenseRecord(source="wikimedia", license_id="PDM-1.0"))
    library.add(SoundRecord(id="pdm", license=lic), data=_flac(600))
    _data, rights, prov = foley.export_sound("pdm", library=library)
    assert rights["license"] is None  # a Public Domain Mark is a claim, not a grant
    assert prov["license_id"] == "PDM-1.0" and prov["rights_verified"] is False


# ---------------------------------------------------------------------------
# the consumers' own models (skipped when absent; foley never imports them)
# ---------------------------------------------------------------------------


def test_the_provenance_field_names_are_lacings_and_ans():
    """foley's one copy of the downstream records' field names (PROVENANCE_FIELDS,
    which a titles file may not name) is pinned to each model that is installed."""
    lacing = pytest.importorskip("lacing")
    assert set(lacing.Rights.model_fields) == set(RIGHTS_FIELDS)
    assets = pytest.importorskip("an.ir.assets")
    fields = set(assets.AssetSource.model_fields)
    assert fields - set(RIGHTS_FIELDS) == set(ASSET_SOURCE_EXTRAS)
    assert set(PROVENANCE_FIELDS) == fields | set(RIGHTS_FIELDS)


@pytest.mark.parametrize("sound_id", THREE)
def test_rights_validate_as_lacing_rights(library, sound_id):
    lacing = pytest.importorskip("lacing")
    _data, rights, _prov = foley.export_sound(sound_id, library=library)
    assert set(lacing.Rights.model_fields) == set(RIGHTS_FIELDS)
    assert lacing.Rights(**rights).model_dump() == rights


def test_an_classifies_the_three_licences(library):
    assets = pytest.importorskip("an.ir.assets")

    def source(sound_id):
        _data, rights, prov = foley.export_sound(sound_id, library=library)
        return assets.AssetSource(**rights, sha256=prov["sha256"])

    assert assets.license_class(source("fs-12345")) == "free"
    assert assets.license_class(source("fsd-222")) == "attribution"
    stable = source("sa-7")
    assert assets.license_class(stable) == "free"
    assert "1,000,000" in assets.license_restriction(stable)


# ---------------------------------------------------------------------------
# hash check, sample format
# ---------------------------------------------------------------------------


def test_a_record_with_no_content_hash_is_refused(library, tmp_path):
    path = tmp_path / "mine.flac"
    path.write_bytes(_flac(700))
    lic = apply_license_flags(
        LicenseRecord(source="user", license_id="user-owned", rights_verified=True)
    )
    library.meta["mine"] = SoundRecord(id="mine", license=lic, uri=str(path))
    with pytest.raises(ValueError, match="names no content hash"):
        foley.export_sound("mine", library=library)


@pytest.mark.parametrize("fmt", ["wav", "flac"])
def test_a_float_source_exports_as_pcm_24_and_says_it_is_lossy(library, fmt):
    t = np.linspace(0.0, 0.25, SR // 4, endpoint=False)
    floats = encode((0.3 * np.sin(2 * np.pi * 440 * t)), SR, fmt="wav", subtype="FLOAT")
    library.add(SoundRecord(id="float", license=_freesound_cc0().license), data=floats)
    _data, _rights, prov = foley.export_sound("float", fmt, library=library)
    assert (prov["archived_subtype"], prov["subtype"]) == ("FLOAT", "PCM_24")
    assert prov["lossless"] is False


def test_a_pcm_export_is_lossless(library):
    _data, _rights, prov = foley.export_sound("fsd-222", library=library)
    assert prov["lossless"] is True and prov["archived_subtype"] == "PCM_24"


def test_provenance_carries_notice_territories_and_safety_flags(library):
    lic = apply_license_flags(
        LicenseRecord(
            source="hunyuan",
            license_id="Tencent-Hunyuan-Community",
            rights_verified=True,
            notice_text_required="made with Tencent Hunyuan",
            gen_ai_preference="no_ai",
            potential_trademark=True,
        )
    )
    library.add(SoundRecord(id="hy", license=lic), data=_flac(800))
    _data, _rights, prov = foley.export_sound("hy", library=library)
    assert prov["notice_text_required"] == "made with Tencent Hunyuan"
    assert prov["excluded_territories"] == ["EU", "GB", "GG", "GI", "IM", "JE", "KR"]
    assert prov["gen_ai_preference"] == "no_ai"
    assert prov["potential_trademark"] is True
    assert prov["contains_recognizable_voice"] is False


# ---------------------------------------------------------------------------
# an edit never exports wider than its lineage (#66 review)
# ---------------------------------------------------------------------------

#: The licences generators make clips under (the edit backends' and procedural).
GENERATOR_LICENSES = ("Stability-Community", "elevenlabs-paid-plan", "procedural-free")
#: Each consumer class's strictness (``an``'s ``private`` reads as strict as unknown).
AN_RANK = {"free": 0, "attribution": 1, "noncommercial": 2, "unknown": 3, "private": 3}


def _edit(generator_license: str, source_license: str) -> SoundRecord:
    out = apply_license_flags(
        LicenseRecord(source="g", license_id=generator_license, rights_verified=True)
    )
    src = apply_license_flags(
        LicenseRecord(source="s", license_id=source_license, rights_verified=True)
    )
    return SoundRecord(id="edit", license=narrow_to_source(out, src))


EDITS = [(g, s) for g in GENERATOR_LICENSES for s in sorted(LICENSE_FLAGS)]


@pytest.mark.parametrize("generator_license,source_license", EDITS)
def test_an_edit_exports_no_wider_than_its_source(generator_license, source_license):
    code = sound_rights(_edit(generator_license, source_license))["license"]
    if code is None:
        return
    by_code = {consumer_license_code(i): i for i in LICENSE_FLAGS}
    exported = LICENSE_FLAGS[by_code[code]]
    for lid in (generator_license, source_license):
        if not LICENSE_FLAGS[lid].commercial_ok:
            assert not exported.commercial_ok, (lid, code)
        if LICENSE_FLAGS[lid].requires_attribution:
            assert exported.requires_attribution, (lid, code)


@pytest.mark.parametrize(
    "generator_license,source_license,code",
    [
        ("Stability-Community", "CC0-1.0", "stability-community"),  # its cap is named
        ("Stability-Community", "Stability-Community", "stability-community"),
        # a source code would grant the standalone redistribution Stability's licence
        # bars (no restriction kind states it): unknown (fail-closed; #282)
        ("Stability-Community", "CC-BY-4.0", None),
        ("Stability-Community", "MIT", None),
        ("Stability-Community", "CC-BY-NC-4.0", None),
        ("Stability-Community", "Tencent-Hunyuan-Community", None),
        ("procedural-free", "CC-BY-NC-4.0", "cc-by-nc-4.0"),
        ("procedural-free", "CC-BY-4.0", "cc-by-4.0"),
    ],
)
def test_the_reviewed_fail_open_cases(generator_license, source_license, code):
    rights = sound_rights(_edit(generator_license, source_license))
    assert rights["license"] == code
    if code is None:
        assert rights["license_url"] is None


def test_an_edit_never_drops_a_revenue_cap():
    for generator_license, source_license in EDITS:
        own_cap = LICENSE_FLAGS[generator_license].revenue_cap_usd
        if not own_cap:
            continue
        rights = sound_rights(_edit(generator_license, source_license))
        stated = [r["usd"] for r in rights["restrictions"] if r["kind"] == "revenue_cap"]
        assert stated and min(stated) <= own_cap, (generator_license, source_license)


def test_an_classifies_no_edit_wider_than_its_lineage():
    assets = pytest.importorskip("an.ir.assets")

    def an_rank(provider, code):
        source = assets.AssetSource(provider=provider, license=code)
        return AN_RANK[assets.license_class(source)]

    for generator_license, source_license in EDITS:
        rights = sound_rights(_edit(generator_license, source_license))
        exported = an_rank(rights["provider"], rights["license"])
        # the source as an reads it alone; the generator's own licence only when an
        # knows it (an UNKNOWN ``procedural-free`` is an's gap, not a restriction)
        lineage = [(source_license, "s")]
        if (
            an_rank(rights_provider_of(generator_license), generator_license.lower())
            < 3
        ):
            lineage.append((generator_license, "g"))
        for lid, source in lineage:
            alone = an_rank(
                LICENSE_TERMS_PROVIDER.get(lid, source), consumer_license_code(lid)
            )
            assert exported >= alone, (generator_license, source_license, rights)


def rights_provider_of(license_id):
    return LICENSE_TERMS_PROVIDER.get(license_id, "g")


# ---------------------------------------------------------------------------
# every licence foley knows gives a Rights-shaped dict
# ---------------------------------------------------------------------------


def _rights_for(license_id: str) -> dict:
    lic = apply_license_flags(
        LicenseRecord(source="s", license_id=license_id, rights_verified=True)
    )
    return sound_rights(SoundRecord(id="x", license=lic))


@pytest.mark.parametrize("license_id", sorted(LICENSE_FLAGS))
def test_every_licence_gives_a_rights_shaped_dict(license_id):
    rights = _rights_for(license_id)
    restricted = bool(
        LICENSE_FLAGS[license_id].revenue_cap_usd
        or LICENSE_EXCLUDED_TERRITORIES.get(license_id)
    )
    assert set(rights) == set(RIGHTS_FIELDS) - (set() if restricted else {"restrictions"})
    assert isinstance(rights["provider"], str) and rights["provider"]
    assert isinstance(rights["cacheable"], bool)
    assert all(
        v is None or (isinstance(v, str) and v.strip())
        for k, v in rights.items()
        if k not in ("cacheable", "restrictions")
    )


def _capped(license_id="CC-BY-4.0", usd=5000, *lineage):
    return apply_license_flags(
        LicenseRecord(source="s", license_id=license_id, rights_verified=True,
                      derived_from_license_ids=list(lineage)),
        overrides={"revenue_cap_usd": usd},
    )  # fmt: skip


def test_a_revenue_cap_and_excluded_territories_travel_as_restrictions():
    """#282: what no licence code says is stated beside it, in lacing's shape."""
    assert _rights_for("Stability-Community")["restrictions"] == (
        {"kind": "revenue_cap", "terms": "stability-community", "usd": 1_000_000},
    )
    (tencent,) = _rights_for("Tencent-Hunyuan-Community")["restrictions"]
    assert tencent["kind"] == "territory_excluded"
    assert {"EU", "GB", "KR"} <= set(tencent["codes"])
    # a cap a narrowing set, which no code implies: the code is kept, the cap stated
    rights = sound_rights(SoundRecord(id="x", license=_capped()))
    assert rights["license"] == "cc-by-4.0"
    assert rights["restrictions"] == ({"kind": "revenue_cap", "terms": None, "usd": 5000},)


def test_a_stated_cap_never_reads_higher_than_a_licences_own():
    """A narrowing cap above Stability's is not stated: the licence's $1M is."""
    rights = sound_rights(SoundRecord(id="x", license=_capped("Stability-Community", 5_000_000)))
    assert [r["usd"] for r in rights["restrictions"]] == [1_000_000]


def test_a_stale_record_still_states_its_lineages_cap():
    """The gate reads the licences, not the stored flags (#288 review)."""
    from dataclasses import replace

    lic = apply_license_flags(
        LicenseRecord(source="s", license_id="Tencent-Hunyuan-Community",
                      rights_verified=True, derived_from_license_ids=["Stability-Community"])
    )  # fmt: skip
    stale = replace(lic, revenue_cap_usd=None)
    rights = sound_rights(SoundRecord(id="x", license=stale))
    caps = [r for r in rights.get("restrictions", ()) if r["kind"] == "revenue_cap"]
    assert rights["license"] is None or caps == [
        {"kind": "revenue_cap", "terms": "stability-community", "usd": 1_000_000}
    ]


@pytest.mark.parametrize(
    "own,source",
    [
        ("Tencent-Hunyuan-Community", "Stability-Community"),
        ("fal-partner-unverified", "Tencent-Hunyuan-Community"),
        ("research-only", "Tencent-Hunyuan-Community"),
    ],
)
def test_an_unknown_class_clip_over_an_unknown_class_source_keeps_its_own_code(own, source):
    """#282: with the source's cap and territories stated, these export the clip's own
    code (a tie between two UNKNOWN classes goes to the clip's own licence); before,
    the code alone could not carry them and the export was unknown. Every consumer
    still classes the code as unknown, and nothing of the source's is dropped."""
    lic = apply_license_flags(
        LicenseRecord(source="s", license_id=own, rights_verified=True,
                      derived_from_license_ids=[source])
    )  # fmt: skip
    rights = sound_rights(SoundRecord(id="x", license=lic))
    assert rights["license"] == consumer_license_code(own)
    stated = {r["terms"] for r in rights["restrictions"]}
    assert consumer_license_code(source) in stated


def test_the_restriction_kinds_are_lacings():
    restrictions = pytest.importorskip("lacing.restrictions")
    assert (REVENUE_CAP, TERRITORY_EXCLUDED) == (
        restrictions.REVENUE_CAP,
        restrictions.TERRITORY_EXCLUDED,
    )
    # and lacing's evaluator reads foley's cap as foley's own gate does
    (cap,) = _rights_for("Stability-Community")["restrictions"]
    rule = restrictions.Restriction(**cap)
    assert restrictions.restriction_breach(rule, restrictions.Use(revenue_usd=2_000_000))
    assert not restrictions.restriction_breach(rule, restrictions.Use(revenue_usd=10))


def test_every_licence_validates_as_lacing_rights():
    lacing = pytest.importorskip("lacing")
    for license_id in LICENSE_FLAGS:
        rights = _rights_for(license_id)
        assert lacing.Rights(**rights).model_dump() == rights, license_id


# ---------------------------------------------------------------------------
# UCS filename + bext / iXML (#231)
# ---------------------------------------------------------------------------


def _data_chunk(wav: bytes) -> bytes:
    from foley.embedded_metadata import iter_riff_chunks

    ((at, size),) = [
        (a, s) for c, a, s in iter_riff_chunks(io.BytesIO(wav)) if c == b"data"
    ]
    return wav[at : at + size]


@pytest.fixture
def door(library):
    lic = apply_license_flags(
        LicenseRecord(source="fsd50k", source_id="77", source_url="https://freesound.org/s/77/",
                      creator_name="amy", license_id="CC-BY-4.0", rights_verified=True)
    )  # fmt: skip
    rec = SoundRecord(id="door_77", license=lic, ucs_category="DOORWood",
                      caption="an old wooden door creaks open slowly", tags=["door", "creak"])  # fmt: skip
    library.add(rec, data=_flac(500))
    return rec


def test_a_wav_export_carries_its_metadata_and_a_ucs_filename(library, door):
    from foley.embedded_metadata import read_embedded_metadata
    from foley.index.taxonomy import parse_ucs_name

    data, rights, prov = foley.export_sound(door.id, library=library)
    name = parse_ucs_name(prov["filename"])
    # the caption cut at 25 characters, on a word boundary
    assert (
        prov["filename"]
        == "DOORWood_an old wooden door creaks_amy_fsd50k_door%5F77.wav"
    )
    assert (name.catid, name.category, name.subcategory) == (
        "DOORWood",
        "DOORS",
        "WOOD",
    )
    assert (name.creator_id, name.source_id, id_from_user_data(name.user_data)) == (
        "amy",
        "fsd50k",
        door.id,
    )
    meta = read_embedded_metadata(data)
    assert meta["caption"] == door.caption and meta["tags"] == door.tags
    assert [
        meta[k] for k in ("ucs_catid", "ucs_category", "ucs_subcategory", "fx_name")
    ] == [
        name.catid,
        name.category,
        name.subcategory,
        name.fx_name,
    ]
    assert [meta[k] for k in ("license", "license_url", "attribution")] == [
        rights["license"],
        rights["license_url"],
        rights["attribution"],
    ]
    assert meta["raw"]["bext"]["description"] == door.caption
    assert prov["embedded"] == ["ixml", "bext"] and prov["export_notes"] == []


def test_a_files_licence_states_the_restrictions_rights_carry():
    """#282: a file has no restrictions field, so its licence text never reads wider."""
    from foley.provenance import export_metadata

    record = SoundRecord(id="x", license=_capped())
    meta = export_metadata(record, sound_rights(record))
    assert meta["license"] == "cc-by-4.0; revenue cap USD 5000"
    text = export_metadata(record, _rights_for("Tencent-Hunyuan-Community"))["license"]
    assert text.startswith("tencent-hunyuan-community; not licensed in ")
    assert "KR" in text and "(tencent" not in text  # its own terms are not repeated


def test_embedding_keeps_the_samples_and_the_hash_names_the_bytes_returned(
    library, door
):
    data, _, prov = foley.export_sound(door.id, library=library)
    plain, _, plain_prov = foley.export_sound(
        door.id, library=library, embed_metadata=False
    )
    assert data != plain and _data_chunk(data) == _data_chunk(plain)
    assert prov["sha256"] == content_key(data) != plain_prov["sha256"]
    assert (
        prov["archived_sha256"] == plain_prov["archived_sha256"] == door.content_sha256
    )
    as_int = lambda b: sf.read(io.BytesIO(b), dtype="int32")[0]  # noqa: E731
    np.testing.assert_array_equal(as_int(data), as_int(library.audio(door.id)))
    assert plain_prov["embedded"] == [] and b"iXML" not in plain


def test_a_flac_export_gets_a_filename_but_no_chunks(library, door):
    data, _, prov = foley.export_sound(door.id, "flac", library=library)
    assert data == library.audio(door.id) and prov["sha256"] == prov["archived_sha256"]
    assert prov["filename"].endswith("_door%5F77.flac") and prov["embedded"] == []
    assert prov["export_notes"] == ["bext / iXML are written into WAV only, not flac"]


def test_a_sound_without_a_known_catid_has_no_filename_but_keeps_its_credit(library):
    from foley.embedded_metadata import read_embedded_metadata

    data, rights, prov = foley.export_sound("fsd-222", library=library)
    assert prov["filename"] is None and "ucs_category=None" in prov["export_notes"][0]
    meta = read_embedded_metadata(data)
    assert "ucs_catid" not in meta and meta["attribution"] == rights["attribution"]
    _, _, off = foley.export_sound("fsd-222", library=library, ucs_filename=False)
    assert off["filename"] is None


def _wav_with_ixml(ixml: bytes, *, data_size=None) -> bytes:
    """A PCM_16 WAV (exported as it is) carrying a source file's own iXML chunk."""
    import struct

    buf = io.BytesIO()
    sf.write(buf, np.zeros(480, dtype="int16"), SR, format="WAV", subtype="PCM_16")
    wav = buf.getvalue()
    if len(ixml) % 2:
        ixml += b" "
    wav += b"iXML" + struct.pack("<I", len(ixml)) + ixml
    wav = wav[:4] + struct.pack("<I", len(wav) - 8) + wav[8:]
    if data_size is not None:  # a streamed WAV: its data size never filled in
        at = wav.index(b"data") + 4
        wav = wav[:at] + struct.pack("<I", data_size) + wav[at + 4 :]
    return wav


def _unverified(sound_id: str) -> SoundRecord:
    lic = apply_license_flags(LicenseRecord(source="pack", license_id="CC-BY-NC-4.0"))
    return SoundRecord(id=sound_id, license=lic, caption="a vendor door")


def test_a_source_files_licence_fields_never_survive_beside_foleys(library):
    from foley.embedded_metadata import read_embedded_metadata

    vendor = (
        b'<?xml version="1.0"?><BWFXML><!-- vendor note --><USER>'
        b"<LICENSE>vendor-eula</LICENSE><LICENSE_URL>https://vendor/eula</LICENSE_URL>"
        b"<LIBRARY>Doors 2</LIBRARY></USER></BWFXML>"
    )
    library.add(_unverified("pack-1"), data=_wav_with_ixml(vendor))
    data, rights, prov = foley.export_sound("pack-1", library=library)
    assert rights["license"] is None and rights["license_url"] is None
    ixml = read_embedded_metadata(data)["raw"]["ixml"]
    assert "LICENSE" not in ixml and "LICENSE_URL" not in ixml
    assert ixml["LIBRARY"] == "Doors 2" and ixml["ATTRIBUTION"] == rights["attribution"]
    assert b"<!-- vendor note -->" in data  # the rest of the source iXML is kept
    assert prov["sha256"] == content_key(data)


def test_a_streamed_wav_is_exported_unembedded_with_a_note(library):
    library.add(
        _unverified("stream-1"), data=_wav_with_ixml(b"<x/>", data_size=0xFFFFFFFF)
    )
    data, _, prov = foley.export_sound("stream-1", library=library)
    assert data == library.audio("stream-1") and prov["embedded"] == []
    assert any(n.startswith("bext / iXML not written") for n in prov["export_notes"])
    assert prov["sha256"] == content_key(data)


def test_ids_that_clean_alike_get_distinct_filenames(library, door):
    from foley.index.taxonomy import parse_ucs_name
    from foley.provenance import export_ucs_filename

    ids = ["fs:1", "fs/1", "fs?1", "fs 1", "fs_1", "FS:1", "fs.1", "fs%3A1", "fé"]
    rights = sound_rights(door)
    names = [
        export_ucs_filename(SoundRecord(**{**vars(door), "id": i}), rights) for i in ids
    ]
    assert len({n.casefold() for n in names}) == len(ids)  # case-insensitive FS too
    assert [id_from_user_data(parse_ucs_name(n).user_data) for n in names] == ids
    assert all(id_from_user_data(id_to_user_data(i)) == i for i in ids)


def test_a_long_name_is_cut_to_the_filename_limit_keeping_the_id(library, door):
    from foley.index.taxonomy import UCS_NAME_MAX_BYTES, parse_ucs_name
    from foley.provenance import export_ucs_filename

    rights = {**sound_rights(door), "author": "é" * 300}
    name = export_ucs_filename(door, rights)
    assert len(name.encode()) <= UCS_NAME_MAX_BYTES
    assert id_from_user_data(parse_ucs_name(name).user_data) == door.id


def test_no_filename_note_when_none_was_asked_for(library):
    _, _, prov = foley.export_sound(
        "fsd-222", "flac", library=library, ucs_filename=False
    )
    assert prov["export_notes"] == ["bext / iXML are written into WAV only, not flac"]
