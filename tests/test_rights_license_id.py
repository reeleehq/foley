"""The exported licence code never implies more than a record's flags allow (#274).

``rights_license_id`` (the code ``foley.export_sound`` hands a consumer) is checked
against an oracle written out here, independently of
``foley.licensing.code_implies_at_most``: every licence id foley knows (its rows and
the share-alike ids), under every one-licence lineage, as a plain record and as the
conflict a restamp makes. Plus the issue's exact case: a CC BY-SA record restamped
from a CC BY-NC one exports CC BY-NC-SA, not CC BY-SA (which reads as commercial).
"""

import pytest

from foley.base import LicenseRecord
from foley.licensing import (
    LICENSE_EXCLUDED_TERRITORIES,
    LICENSE_FLAGS,
    SHARE_ALIKE_FLAGS,
    apply_license_flags,
    derived_license_ids,
    excluded_territories,
    is_share_alike,
    restamped_license,
    rights_license_id,
)

#: Every licence id a record can carry: the rows, and the share-alike ids (no row).
LICENSE_IDS = sorted({*LICENSE_FLAGS, *SHARE_ALIKE_FLAGS})
#: The permissions a code grants a consumer.
PERMISSIONS = (
    "commercial_ok",
    "embed_in_derivative_ok",
    "redistribute_standalone_ok",
    "modification_ok",
    "ai_training_ok",
)


def _grant(license_id):
    """What ``license_id`` tells a consumer: its row; a share-alike id, its family's."""
    if license_id in SHARE_ALIKE_FLAGS:
        return LICENSE_FLAGS[license_id.replace("-SA-", "-")]
    return LICENSE_FLAGS.get(license_id, LICENSE_FLAGS["unknown"])


def _record(license_id, *lineage):
    return apply_license_flags(
        LicenseRecord(
            source="s",
            license_id=license_id,
            rights_verified=True,
            derived_from_license_ids=list(lineage),
        )
    )


def _widenings(record):
    """What the exported code allows that ``record`` (or its chain) does not."""
    code = rights_license_id(record)
    if code is None:
        return []
    chain = [record.license_id, *derived_license_ids(record)]
    grants = [_grant(i) for i in chain]
    share_alike = any(is_share_alike(i) for i in chain)
    implied, wider = _grant(code), []
    for p in PERMISSIONS:
        # under share-alike the record's flags are foley's self-limit, not the licence's
        held = share_alike or getattr(record, p)
        if getattr(implied, p) and not (held and all(getattr(g, p) for g in grants)):
            wider.append(p)
    if not implied.requires_attribution and (
        record.requires_attribution or any(g.requires_attribution for g in grants)
    ):
        wider.append("requires_attribution")
    caps = (record.revenue_cap_usd, *(g.revenue_cap_usd for g in grants))
    caps = [c for c in caps if c is not None]
    if caps and (
        implied.revenue_cap_usd is None or implied.revenue_cap_usd > min(caps)
    ):
        wider.append("revenue_cap_usd")
    if not set(excluded_territories(record)) <= LICENSE_EXCLUDED_TERRITORIES.get(
        code, frozenset()
    ):
        wider.append("territories")
    if share_alike and not is_share_alike(code):
        wider.append("share-alike")
    return [f"{code}: {w}" for w in wider]


LINEAGES = [(), *((i,) for i in LICENSE_IDS)]


@pytest.mark.parametrize("license_id", LICENSE_IDS)
def test_no_exported_code_is_wider_than_the_records_flags(license_id):
    widened = {
        lineage: w
        for lineage in LINEAGES
        if (w := _widenings(_record(license_id, *lineage)))
    }
    assert not widened


@pytest.mark.parametrize("stored_id", LICENSE_IDS)
def test_no_restamp_exports_a_code_wider_than_its_flags(stored_id):
    stored = _record(stored_id)
    widened = {}
    for fresh_id in LICENSE_IDS:
        new, _note = restamped_license(stored, _record(fresh_id), widen=False)
        if new is not None and (w := _widenings(new)):
            widened[fresh_id] = w
    assert not widened


def test_a_share_alike_record_bounded_by_nc_exports_nc_sa():
    """The issue's case: the conflict path keeps CC BY-SA, bounded by CC BY-NC."""
    sa, nc = _record("CC-BY-SA-4.0"), _record("CC-BY-NC-4.0")
    bounded, note = restamped_license(sa, nc, widen=False)
    assert note.startswith("licences conflict")
    assert bounded.license_id == "CC-BY-SA-4.0"
    assert not bounded.commercial_ok
    assert rights_license_id(bounded) == "CC-BY-NC-SA-4.0"


def test_a_share_alike_code_with_no_exact_intersection_is_unknown():
    # BY-SA bounded by a licence that forbids standalone redistribution: no CC code
    # carries both, so the export reads as UNKNOWN (fail-closed).
    assert rights_license_id(_record("CC-BY-SA-4.0", "fal-partner-unverified")) is None
    assert rights_license_id(_record("CC-BY-SA-4.0", "elevenlabs-free-plan")) is None


def test_plain_records_keep_their_own_code():
    for license_id in ("CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-SA-3.0"):
        assert rights_license_id(_record(license_id)) == license_id
    assert rights_license_id(_record("CC-BY-SA-4.0", "CC-BY-SA-4.0")) == "CC-BY-SA-4.0"


def test_a_narrowing_the_flags_hold_but_the_code_drops_is_unknown():
    # the rights holder said no AI training: a CC0 code would read as allowing it
    lic = apply_license_flags(
        LicenseRecord(source="pack", license_id="CC0-1.0", rights_verified=True),
        overrides={"ai_training_ok": False},
    )
    assert rights_license_id(lic) is None
