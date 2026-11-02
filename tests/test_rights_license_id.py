"""The exported licence code never implies more than a record allows (#274).

``rights_license_id`` (the code ``foley.export_sound`` hands a consumer), with the
expected codes written out by hand: share-alike bounded by non-commercial at every
version and in both restamp orders, a narrowing the record's own flags hold, and the
issue's exact case (a CC BY-SA record restamped from a CC BY-NC one exported
``CC-BY-SA-4.0``, which reads as commercial). No CC licence satisfies both BY-SA and
BY-NC (BY-SA requires adaptations under BY-SA or a compatible licence), so such a
record exports UNKNOWN. AI use is not in a code: it travels in the provenance.
"""

import pytest

from foley.base import LicenseRecord, SoundRecord
from foley.licensing import (
    CC_VERSIONS,
    LICENSE_FLAGS,
    SHARE_ALIKE_FLAGS,
    apply_license_flags,
    code_implies_at_most,
    derived_license_ids,
    restamped_license,
    rights_license_id,
)
from foley.provenance.rights import sound_provenance, sound_rights


def _record(license_id, *lineage, overrides=None):
    return apply_license_flags(
        LicenseRecord(
            source="s",
            license_id=license_id,
            rights_verified=True,
            derived_from_license_ids=list(lineage),
        ),
        overrides=overrides,
    )


EXPECTED = [
    # (own licence, lineage, overrides, expected code)
    ("CC-BY-4.0", (), None, "CC-BY-4.0"),
    ("CC-BY-SA-4.0", (), None, "CC-BY-SA-4.0"),
    ("CC-BY-NC-SA-3.0", (), None, "CC-BY-NC-SA-3.0"),
    ("CC-BY-SA-4.0", ("CC-BY-SA-4.0",), None, "CC-BY-SA-4.0"),
    ("CC-BY-SA-4.0", ("CC0-1.0",), None, "CC-BY-SA-4.0"),
    ("CC-BY-SA-4.0", ("CC-BY-4.0",), None, "CC-BY-SA-4.0"),
    # share-alike bounded by non-commercial: no licence carries both
    *(("CC-BY-SA-" + v, ("CC-BY-NC-" + v,), None, None) for v in CC_VERSIONS),
    *(("CC-BY-NC-" + v, ("CC-BY-SA-" + v,), None, None) for v in CC_VERSIONS),
    ("CC-BY-SA-4.0", ("CC-BY-NC-3.0",), None, None),
    ("CC-BY-SA-4.0", ("CC-BY-NC-SA-4.0",), None, None),
    ("CC-BY-NC-SA-4.0", ("CC-BY-SA-4.0",), None, None),
    ("CC-BY-SA-4.0", ("CC-BY-SA-3.0",), None, None),  # another version's SA term
    ("CC-BY-SA-4.0", ("fal-partner-unverified",), None, None),
    ("CC-BY-SA-4.0", ("Stability-Community",), None, None),
    ("CC-BY-SA-4.0", ("Tencent-Hunyuan-Community",), None, None),
    # a narrowing the record's own flags hold, which the code would drop
    ("CC-BY-SA-4.0", (), {"revenue_cap_usd": 1000}, None),
    ("CC-BY-4.0", (), {"modification_ok": False}, None),
    ("CC-BY-4.0", (), {"redistribute_standalone_ok": False}, None),
    # a lineage restriction the winning code would drop
    ("Pixabay-Content", ("CC-BY-4.0",), None, None),  # no standalone redistribution
    ("owned-pack", ("CC-BY-NC-4.0",), None, None),
    ("Tencent-Hunyuan-Community", ("CC-BY-4.0",), None, None),  # attribution
    ("research-only", ("Tencent-Hunyuan-Community",), None, None),  # territories
    ("procedural-free", ("CC-BY-NC-4.0",), None, "CC-BY-NC-4.0"),
    ("elevenlabs-free-plan", ("CC-BY-4.0",), None, "elevenlabs-free-plan"),
    # AI use is not in a code (it travels in the provenance)
    ("CC0-1.0", (), {"ai_training_ok": False}, "CC0-1.0"),
    ("CC-BY-SA-4.0", (), {"ai_training_ok": False}, "CC-BY-SA-4.0"),
]


@pytest.mark.parametrize("own,lineage,overrides,code", EXPECTED)
def test_the_exported_code(own, lineage, overrides, code):
    record = _record(own, *lineage, overrides=overrides)
    assert rights_license_id(record) == code


@pytest.mark.parametrize(
    "stored_id,fresh_id",
    [("CC-BY-SA-4.0", "CC-BY-NC-4.0"), ("CC-BY-NC-4.0", "CC-BY-SA-4.0")],
)
def test_a_share_alike_nc_restamp_conflict_exports_unknown_either_way(
    stored_id, fresh_id
):
    bounded, note = restamped_license(
        _record(stored_id), _record(fresh_id), widen=False
    )
    assert note.startswith("licences conflict")
    assert bounded.license_id == stored_id
    assert derived_license_ids(bounded) == [fresh_id]
    assert rights_license_id(bounded) is None


def test_the_issues_case_exports_no_licence():
    """A verified CC BY-SA record restamped from a verified CC BY-NC one (#274)."""
    bounded, _note = restamped_license(
        _record("CC-BY-SA-4.0"), _record("CC-BY-NC-4.0"), widen=False
    )
    rights = sound_rights(SoundRecord(id="x", license=bounded))
    assert rights["license"] is None and rights["license_url"] is None


def test_an_ai_opt_out_travels_in_the_provenance():
    lic = apply_license_flags(
        LicenseRecord(
            source="s",
            license_id="CC0-1.0",
            rights_verified=True,
            ai_training_scope="none",
        ),
        overrides={"ai_training_ok": False},
    )
    prov = sound_provenance(
        SoundRecord(id="x", license=lic),
        archived_sha256="a",
        sha256="b",
        fmt="wav",
        subtype="PCM_24",
    )
    assert rights_license_id(lic) == "CC0-1.0"
    assert prov["flags"]["ai_training_ok"] is False
    assert prov["ai_training_scope"] == "none"


@pytest.mark.parametrize("own", sorted({*LICENSE_FLAGS, *SHARE_ALIKE_FLAGS}))
def test_every_exported_code_is_from_the_chain_and_passes_the_gate(own):
    for lineage in [(), *((i,) for i in sorted({*LICENSE_FLAGS, *SHARE_ALIKE_FLAGS}))]:
        record = _record(own, *lineage)
        code = rights_license_id(record)
        assert code is None or code in (own, *lineage), (own, lineage, code)
        assert code_implies_at_most(code, record), (own, lineage, code)
