"""Tests for foley's SSOT data models (``foley.base``) and license policy
(``foley.licensing``).

Stdlib-only — no optional (audio) dependencies. Covers:

    * construction of every model with fail-closed defaults,
    * enum identity / str-equality,
    * JSON round-trips (to_dict/from_dict/to_json/from_json) including nested
      ``LicenseRecord`` and enum coercion, unknown-key tolerance, and the nested
      ``Candidate`` decode path,
    * ``derive_license_flags`` for representative license ids + invariant #2,
    * ``apply_license_flags`` population,
    * the fail-closed ``keep()`` truth table,
    * that the affordance registries are well-formed.
"""

import json

import pytest

from foley.base import (
    SCHEMA_VERSION,
    AcquisitionMethod,
    Affordance,
    Candidate,
    CandidateOrigin,
    GENERATION_AFFORDANCES,
    IntendedUse,
    Layer,
    LicenseRecord,
    QUERY_AFFORDANCES,
    Salience,
    SoundEvent,
    SoundRecord,
    StorageMode,
    Verdict,
    VerifyLevel,
)
from foley.licensing import (
    LICENSE_FLAGS,
    UNKNOWN_LICENSE_FLAGS,
    apply_license_flags,
    derive_license_flags,
    keep,
    keep_sound,
)


# ---------------------------------------------------------------------------
# Construction + defaults
# ---------------------------------------------------------------------------


def test_license_record_defaults_are_fail_closed():
    lic = LicenseRecord(source="user")
    # rights unknown until verified
    assert lic.rights_verified is False
    # copyright / operational flags default fail-closed
    assert lic.commercial_ok is False
    assert lic.redistribute_standalone_ok is False
    assert lic.cache_bytes_ok is False
    assert lic.modification_ok is False
    assert lic.ai_training_ok is False
    # embed is the one "normal case" default
    assert lic.embed_in_derivative_ok is True
    assert lic.license_id == "unknown"
    assert lic.acquisition_method == AcquisitionMethod.user
    assert lic.schema_version == SCHEMA_VERSION


def test_sound_record_defaults():
    rec = SoundRecord(id="s1")
    assert rec.id == "s1"
    assert rec.hash_algo == "sha256"
    # storage defaults to by-reference (no bytes held until license permits)
    assert rec.storage_mode == StorageMode.by_reference
    # default nested license is a fail-closed user record
    assert isinstance(rec.license, LicenseRecord)
    assert rec.license.source == "user"
    assert rec.license.commercial_ok is False
    assert rec.tags == [] and rec.audioset_labels == []
    assert rec.schema_version == SCHEMA_VERSION


def test_sound_event_defaults():
    ev = SoundEvent(query="distant thunder")
    assert ev.query == "distant thunder"
    assert ev.layer == Layer.sfx_fg
    assert ev.diegetic is True
    assert ev.salience == Salience.medium
    assert ev.audioset == []


def test_verdict_construction():
    v = Verdict(match=True, confidence=0.87)
    assert v.match is True
    assert v.confidence == 0.87
    assert v.reason == ""
    assert v.level == VerifyLevel.clap


def test_candidate_defaults():
    cand = Candidate(sound=SoundRecord(id="s1"))
    assert cand.origin == CandidateOrigin.retrieved
    assert cand.event is None
    assert cand.verdict is None
    assert cand.license_ok is None


def test_intended_use_defaults():
    use = IntendedUse()
    assert use.commercial is True
    assert use.publish is True
    assert use.redistribute_standalone is False
    assert use.will_train is False
    assert use.can_attribute is True
    assert use.revenue_usd == 0
    assert use.allow_voice_or_trademark is False


# ---------------------------------------------------------------------------
# Enum identity / str equality
# ---------------------------------------------------------------------------


def test_enums_are_str_backed():
    assert StorageMode.by_value == "by_value"
    assert isinstance(Layer.sfx_fg, str)
    assert AcquisitionMethod.api == "api"
    assert CandidateOrigin.generated == "generated"
    assert VerifyLevel.judge == "judge"
    # coercion from string round-trips to the member
    assert StorageMode("by_reference") is StorageMode.by_reference


# ---------------------------------------------------------------------------
# JSON round-trips
# ---------------------------------------------------------------------------


def _rich_sound_record() -> SoundRecord:
    """A SoundRecord with a non-default nested license (enum acquisition_method,
    populated flags) and a non-default storage_mode enum."""
    lic = LicenseRecord(
        source="freesound",
        source_id="12345",
        acquisition_method=AcquisitionMethod.api,
        license_id="CC0-1.0",
        commercial_ok=True,
        redistribute_standalone_ok=True,
        cache_bytes_ok=False,
        rights_verified=True,
        transformations=["trim", "normalize"],
    )
    return SoundRecord(
        id="sound-42",
        content_sha256="deadbeef",
        uri="deadbeef",
        storage_mode=StorageMode.by_value,
        license=lic,
        caption="a wooden door creak",
        tags=["door", "creak"],
        duration_s=2.5,
        sample_rate=48_000,
        channels=1,
    )


def test_sound_record_dict_roundtrip():
    rec = _rich_sound_record()
    restored = SoundRecord.from_dict(rec.to_dict())
    assert restored == rec
    # nested license survives as an equal dataclass, with its enum intact
    assert isinstance(restored.license, LicenseRecord)
    assert restored.license.acquisition_method == AcquisitionMethod.api
    assert restored.storage_mode == StorageMode.by_value


def test_sound_record_json_roundtrip():
    rec = _rich_sound_record()
    restored = SoundRecord.from_json(rec.to_json())
    assert restored == rec


def test_json_serializes_enums_as_strings():
    rec = _rich_sound_record()
    payload = json.loads(rec.to_json())
    # enum -> its .value string, with NO custom encoder
    assert payload["storage_mode"] == "by_value"
    assert payload["license"]["acquisition_method"] == "api"


def test_from_dict_ignores_unknown_keys():
    rec = SoundRecord(id="s1")
    d = rec.to_dict()
    d["totally_unknown_future_field"] = 1
    restored = SoundRecord.from_dict(d)
    assert restored == rec


def test_from_dict_missing_keys_fall_back_to_defaults():
    # a minimal dict (only the required id) reconstructs with all defaults
    restored = SoundRecord.from_dict({"id": "s9"})
    assert restored == SoundRecord(id="s9")


def test_candidate_nested_roundtrip():
    cand = Candidate(
        sound=_rich_sound_record(),
        origin=CandidateOrigin.retrieved,
        event=SoundEvent(query="door creak", layer=Layer.sfx_fg, salience=Salience.high),
        clap_score=0.72,
        verdict=Verdict(match=True, confidence=0.9, level=VerifyLevel.listen),
        license_ok=True,
    )
    restored = Candidate.from_dict(cand.to_dict())
    assert restored == cand
    # nested dataclasses decoded to the right types (not left as dicts)
    assert isinstance(restored.sound, SoundRecord)
    assert isinstance(restored.event, SoundEvent)
    assert isinstance(restored.verdict, Verdict)
    assert restored.event.salience == Salience.high
    assert restored.verdict.level == VerifyLevel.listen


def test_license_record_roundtrip_via_json():
    lic = LicenseRecord(
        source="stable_audio",
        license_id="Stability-Community",
        acquisition_method=AcquisitionMethod.generated,
        is_ai_generated=True,
        generation_seed=7,
        generation_params={"steps": 50},
        watermark={"present": True, "method": "audioseal"},
        revenue_cap_usd=1_000_000,
    )
    assert LicenseRecord.from_json(lic.to_json()) == lic


# ---------------------------------------------------------------------------
# derive_license_flags — representative ids + invariant #2
# ---------------------------------------------------------------------------


def test_license_flags_cc0():
    f = derive_license_flags("CC0-1.0")
    assert f.commercial_ok is True
    assert f.redistribute_standalone_ok is True
    assert f.cache_bytes_ok is True
    assert f.ai_training_ok is True
    assert f.requires_attribution is False


def test_license_flags_cc_by_requires_attribution():
    assert derive_license_flags("CC-BY-4.0").requires_attribution is True


def test_license_flags_cc_by_nc_not_commercial():
    assert derive_license_flags("CC-BY-NC-4.0").commercial_ok is False


def test_license_flags_stability_revenue_cap():
    assert LICENSE_FLAGS["Stability-Community"].revenue_cap_usd == 1_000_000


def test_unknown_license_id_is_fail_closed():
    f = derive_license_flags("Proprietary-acme")
    assert f is UNKNOWN_LICENSE_FLAGS
    assert f.commercial_ok is False
    assert f.embed_in_derivative_ok is False
    assert f.redistribute_standalone_ok is False
    assert f.cache_bytes_ok is False
    assert f.revenue_cap_usd is None


def test_invariant_2_cache_vs_redistribute_are_distinct():
    # Freesound CC0: redistributable (copyright) but NOT cacheable (TOS).
    f = derive_license_flags("CC0-1.0", overrides={"cache_bytes_ok": False})
    assert f.redistribute_standalone_ok is True
    assert f.cache_bytes_ok is False


def test_derive_flags_rejects_unknown_override():
    with pytest.raises(ValueError):
        derive_license_flags("CC0-1.0", overrides={"bogus": 1})


# ---------------------------------------------------------------------------
# apply_license_flags
# ---------------------------------------------------------------------------


def test_apply_license_flags_populates_all_eight_and_leaves_verified():
    rec = LicenseRecord(source="freesound", license_id="CC0-1.0")
    assert rec.rights_verified is False
    returned = apply_license_flags(rec, overrides={"cache_bytes_ok": False})
    assert returned is rec  # mutates in place
    assert rec.commercial_ok is True
    assert rec.embed_in_derivative_ok is True
    assert rec.redistribute_standalone_ok is True
    assert rec.cache_bytes_ok is False  # override wins
    assert rec.modification_ok is True
    assert rec.ai_training_ok is True
    assert rec.requires_attribution is False
    assert rec.revenue_cap_usd is None
    # verification untouched by policy derivation
    assert rec.rights_verified is False


# ---------------------------------------------------------------------------
# keep() — fail-closed truth table
# ---------------------------------------------------------------------------


def _verified_cc0() -> LicenseRecord:
    rec = LicenseRecord(source="user", license_id="CC0-1.0", rights_verified=True)
    return apply_license_flags(rec)


def test_keep_rejects_unverified_rights():
    rec = apply_license_flags(LicenseRecord(source="user", license_id="CC0-1.0"))
    # flags say commercial_ok etc. are True, but rights_verified is False
    assert rec.commercial_ok is True
    assert keep(rec, IntendedUse()) is False


def test_keep_passes_verified_cc0_default_use():
    assert keep(_verified_cc0(), IntendedUse()) is True


def test_keep_rejects_commercial_when_not_commercial_ok():
    rec = apply_license_flags(
        LicenseRecord(source="user", license_id="CC-BY-NC-4.0", rights_verified=True)
    )
    assert keep(rec, IntendedUse(commercial=True)) is False
    # non-commercial intent passes (embed_in_derivative_ok is True for NC)
    assert keep(rec, IntendedUse(commercial=False)) is True


def test_keep_rejects_standalone_redistribution_when_not_allowed():
    rec = apply_license_flags(
        LicenseRecord(source="user", license_id="Sonniss-GDC", rights_verified=True)
    )
    assert rec.redistribute_standalone_ok is False
    assert keep(rec, IntendedUse(redistribute_standalone=True)) is False
    # CC0 allows standalone redistribution
    assert keep(_verified_cc0(), IntendedUse(redistribute_standalone=True)) is True


def test_keep_rejects_training_when_not_allowed():
    rec = apply_license_flags(
        LicenseRecord(source="user", license_id="CC-BY-NC-4.0", rights_verified=True)
    )
    assert rec.ai_training_ok is False
    assert keep(rec, IntendedUse(will_train=True)) is False
    assert keep(_verified_cc0(), IntendedUse(will_train=True)) is True


def test_keep_enforces_revenue_cap():
    rec = apply_license_flags(
        LicenseRecord(
            source="stable_audio", license_id="Stability-Community", rights_verified=True
        )
    )
    assert rec.revenue_cap_usd == 1_000_000
    # at/above cap => reject
    assert keep(rec, IntendedUse(revenue_usd=1_000_000)) is False
    assert keep(rec, IntendedUse(revenue_usd=2_000_000)) is False
    # below cap => allowed
    assert keep(rec, IntendedUse(revenue_usd=999_999)) is True


def test_keep_enforces_attribution_requirement():
    rec = apply_license_flags(
        LicenseRecord(source="user", license_id="CC-BY-4.0", rights_verified=True)
    )
    assert rec.requires_attribution is True
    assert keep(rec, IntendedUse(can_attribute=False)) is False
    assert keep(rec, IntendedUse(can_attribute=True)) is True


def test_keep_publish_branch_is_the_deciding_factor():
    # Isolate the publish / embed_in_derivative_ok gate: an "unknown" license is
    # verified but NOT embeddable in a derivative. With non-commercial intent the
    # commercial gate is bypassed, so ONLY the publish branch can reject — proving
    # keep() actually enforces embed_in_derivative_ok (a legal gate previously
    # untested in isolation).
    rec = apply_license_flags(
        LicenseRecord(source="user", license_id="unknown", rights_verified=True)
    )
    assert rec.embed_in_derivative_ok is False  # the flag under test
    assert rec.commercial_ok is False
    # publish=True is the sole unmet requirement => reject
    assert keep(rec, IntendedUse(commercial=False, publish=True)) is False
    # drop the publish intent and the SAME record passes => the publish branch
    # was the deciding factor, nothing else.
    assert keep(rec, IntendedUse(commercial=False, publish=False)) is True


def test_keep_blocks_voice_or_trademark_unless_allowed():
    rec = _verified_cc0()
    rec.contains_recognizable_voice = True
    assert keep(rec, IntendedUse()) is False
    assert keep(rec, IntendedUse(allow_voice_or_trademark=True)) is True

    rec2 = _verified_cc0()
    rec2.potential_trademark = True
    assert keep(rec2, IntendedUse()) is False
    assert keep(rec2, IntendedUse(allow_voice_or_trademark=True)) is True


def test_keep_sound_uses_nested_license():
    rec = SoundRecord(id="s1", license=_verified_cc0())
    assert keep_sound(rec, IntendedUse()) is True
    rec.license.rights_verified = False
    assert keep_sound(rec, IntendedUse()) is False


# ---------------------------------------------------------------------------
# Affordance registries are well-formed
# ---------------------------------------------------------------------------


def test_query_affordances_well_formed():
    assert QUERY_AFFORDANCES
    for name, aff in QUERY_AFFORDANCES.items():
        assert isinstance(aff, Affordance)
        assert aff.name == name
        assert aff.stage == "query"
    assert QUERY_AFFORDANCES["k"].default == 10


def test_generation_affordances_well_formed():
    assert GENERATION_AFFORDANCES
    for name, aff in GENERATION_AFFORDANCES.items():
        assert isinstance(aff, Affordance)
        assert aff.name == name
        assert aff.stage == "generate"
    assert GENERATION_AFFORDANCES["duration"].stage == "generate"
