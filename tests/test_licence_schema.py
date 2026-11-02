"""Licence-schema additions (#77): what a source states about its terms.

The new :class:`~foley.base.LicenseRecord` fields (``license_basis`` and its
confidence, ``vendor_trains_on_output``, ``terms_notes``, ``vendor_watermark``) are
stated by the sources that know them, carried into export provenance and the credits
manifest, and never widen :func:`foley.keep`. Records stored before them still load.
"""

import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from foley.base import IntendedUse, LicenseRecord, SoundRecord  # noqa: E402
from foley.index.ingest import _restamped  # noqa: E402
from foley.licensing import (  # noqa: E402
    SOURCE_STATED_FIELDS,
    apply_license_flags,
    carry_lineage,
    excluded_territories,
    narrow_to_source,
    refusal_reason,
    restamped_license,
    stamp_source_terms,
)
from foley.provenance import credits_for  # noqa: E402
from foley.provenance.rights import sound_provenance  # noqa: E402
from foley.sources.base import source_stated_terms  # noqa: E402
from foley.sources.elevenlabs.adapter import ElevenLabsAdapter  # noqa: E402
from foley.sources.freesound.adapter import FreesoundAdapter  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY, discover_sources  # noqa: E402

from .test_fal import ReplayRunner, _adapter, _wav  # noqa: E402
from .test_generate import FakeResponse, FakeTransport  # noqa: E402
from .test_keyless_sources import _openverse  # noqa: E402

FREESOUND_UPF = "commercial use of the API is negotiated case by case with UPF"


def _verified(license_id, **kw):
    return apply_license_flags(
        LicenseRecord(source="s", license_id=license_id, rights_verified=True, **kw)
    )


# -- old records ---------------------------------------------------------------


def test_a_record_stored_before_the_fields_existed_loads_with_unknown_defaults():
    stored = LicenseRecord(source="freesound", license_id="CC0-1.0").to_dict()
    for name in SOURCE_STATED_FIELDS:
        stored.pop(name)
    rec = SoundRecord.from_dict({"id": "x", "license": stored}).license
    assert rec.license_basis is None and rec.license_basis_confidence is None
    assert rec.vendor_trains_on_output is None  # unknown, never "no"
    assert rec.terms_notes == [] and rec.vendor_watermark is None
    # a stored JSON null for the list reads as empty too
    null = LicenseRecord.from_json(json.dumps({**stored, "terms_notes": None}))
    assert null.terms_notes == []


def test_the_new_fields_round_trip_through_json():
    rec = stamp_source_terms(
        LicenseRecord(source="fal_sonilo"),
        {
            "license_basis": "vendor-tos",
            "license_basis_confidence": "unverified",
            "vendor_trains_on_output": True,
            "terms_notes": ["a note"],
            "vendor_watermark": {"present": True, "reported_by": "response"},
        },
    )
    assert LicenseRecord.from_json(rec.to_json()) == rec


# -- keep() is unchanged, or narrower ------------------------------------------


@pytest.mark.parametrize("license_id", ["CC0-1.0", "CC-BY-NC-4.0", "fal-partner-unverified"])
def test_stated_terms_never_change_what_keep_decides(license_id):
    use = IntendedUse(commercial=True, publish=True, can_attribute=True)
    bare = _verified(license_id)
    stated = stamp_source_terms(
        _verified(license_id),
        {
            "license_basis": "aggregator-label",
            "license_basis_confidence": "confirmed",
            "vendor_trains_on_output": False,
            "terms_notes": ["x"],
            "vendor_watermark": {"present": False, "reported_by": "config"},
        },
    )
    assert refusal_reason(stated, use) == refusal_reason(bare, use)
    assert stated.commercial_ok == bare.commercial_ok  # no flag touched


def test_a_territory_exclusion_in_the_lineage_now_gates_keep():
    # A record bounded by the Hunyuan licence (a restamp conflict, a narrowing) is
    # refused where that licence grants nothing: the table stays the SSOT.
    rec = _verified("CC0-1.0", derived_from_license_ids=["Tencent-Hunyuan-Community"])
    assert "EU" in excluded_territories(rec)
    assert "grants nothing" in refusal_reason(rec, IntendedUse(commercial=False, territory="FR"))
    assert refusal_reason(rec, IntendedUse(commercial=False, territory="US")) is None


def test_a_bad_stated_value_is_refused():
    with pytest.raises(ValueError, match="license_basis"):
        stamp_source_terms(LicenseRecord(source="s"), {"license_basis": "fal-label"})
    with pytest.raises(ValueError, match="not source-stated"):
        stamp_source_terms(LicenseRecord(source="s"), {"commercial_ok": True})
    with pytest.raises(ValueError, match="terms_notes"):
        stamp_source_terms(LicenseRecord(source="s"), {"terms_notes": "one string"})
    with pytest.raises(ValueError, match="vendor_watermark"):
        stamp_source_terms(LicenseRecord(source="s"), {"vendor_watermark": True})


def test_every_source_config_states_valid_terms():
    discover_sources()
    for name, entry in SOURCE_REGISTRY.items():
        stamp_source_terms(LicenseRecord(source=name), source_stated_terms(entry["config"]))


# -- each field from the source that knows it ----------------------------------


def test_freesound_stamps_the_api_terms_note_on_every_sound():
    adapter = FreesoundAdapter(api_key="t", http=lambda *a, **k: pytest.fail("no HTTP"))
    item = {"id": 7, "name": "door", "username": "ann", "tags": ["door"],
            "license": "https://creativecommons.org/publicdomain/zero/1.0/"}  # fmt: skip
    lic = adapter._candidate_from_item(item).sound.license
    assert any(FREESOUND_UPF in n for n in lic.terms_notes)
    assert lic.license_basis is None  # an uploader's per-sound CC licence


def test_openverse_marks_its_licences_as_an_aggregator_label():
    ad, _ = _openverse()
    lic = ad.search("door", license=None)[0].sound.license
    assert (lic.license_basis, lic.license_basis_confidence) == ("aggregator-label", "unverified")


def test_fal_partner_models_rest_on_unverified_vendor_terms_never_on_fals_label():
    for name in ("fal_elevenlabs", "fal_sonilo", "fal_mirelo"):
        adapter, _ = _adapter(name)
        lic = adapter.generate("a sigh", duration_s=1).candidate.sound.license
        assert lic.license_id == "fal-partner-unverified"
        assert (lic.license_basis, lic.license_basis_confidence) == ("vendor-tos", "unverified")
    adapter, _ = _adapter("fal_mmaudio")
    lic = adapter.generate("a sigh", duration_s=1).candidate.sound.license
    assert (lic.license_id, lic.license_basis) == ("CC-BY-NC-4.0", "model-licence")


def test_mirelo_and_elevenlabs_on_fal_reuse_their_output():
    for name in ("fal_mirelo", "fal_mirelo_v2a", "fal_elevenlabs"):
        assert source_stated_terms(SOURCE_REGISTRY[name]["config"])["vendor_trains_on_output"]
    adapter, _ = _adapter("fal_mirelo")
    lic = adapter.generate("a sabre", duration_s=1).candidate.sound.license
    assert lic.vendor_trains_on_output is True and "§7.4" in lic.terms_notes[0]
    assert lic.vendor_watermark["present"] is None  # stated, not known for this route
    assert "§7.5" in lic.vendor_watermark["statement"]
    adapter, _ = _adapter("fal_stable_audio_3")
    assert adapter.generate("x", duration_s=1).candidate.sound.license.vendor_trains_on_output is None


def test_elevenlabs_direct_states_its_sublicensing():
    transport = FakeTransport(FakeResponse(200, None, _wav()))
    adapter = ElevenLabsAdapter(api_key="k", http=transport, plan="elevenlabs-paid-plan")
    lic = adapter.generate("a clock", duration_s=1, output_format="mp3").candidate.sound.license
    assert lic.vendor_trains_on_output is True
    assert (lic.license_basis, lic.license_basis_confidence) == ("vendor-tos", "confirmed")
    assert "sublicense" in lic.terms_notes[0]


def test_sonilo_reports_its_own_watermark_per_clip():
    marked = ({"audio": {"url": "u"}, "watermark": "sonilo-provenance"})
    adapter, _ = _adapter("fal_sonilo", runner=ReplayRunner(default=(_wav(), marked)))
    wm = adapter.generate("a sigh", duration_s=1).candidate.sound.license
    assert wm.vendor_watermark["present"] is True
    assert wm.vendor_watermark["reported_by"] == "response"
    assert wm.watermark is None  # foley's own AudioSeal entry stays separate
    # fal's schema lists no such field: an absent field is no report, so the
    # config's statement stands (never a false "not watermarked").
    for name in ("fal_sonilo", "fal_sonilo_v2a"):
        assert SOURCE_REGISTRY[name]["config"]["native_defaults"]["watermark_field"]
    unmarked = ReplayRunner(default=(_wav(), {"audio": {"url": "u"}}))
    adapter, _ = _adapter("fal_sonilo", runner=unmarked)
    wm = adapter.generate("a sigh", duration_s=1).candidate.sound.license.vendor_watermark
    assert wm["present"] is None and wm["reported_by"] == "config"


def test_a_local_generator_has_no_vendor_and_reuses_the_watermarked_capability():
    for name in ("stable_audio", "stable_audio_3", "pyfxr"):
        stated = source_stated_terms(SOURCE_REGISTRY[name]["config"])
        assert stated["vendor_trains_on_output"] is False
        assert stated["vendor_watermark"]["present"] is False  # capabilities['watermarked']


# -- carried downstream ----------------------------------------------------------


def _freesound_record(license_url="https://creativecommons.org/licenses/by/4.0/"):
    adapter = FreesoundAdapter(api_key="t", http=lambda *a, **k: pytest.fail("no HTTP"))
    item = {"id": 9, "name": "rain", "username": "bo", "license": license_url}
    return adapter._candidate_from_item(item).sound


def test_export_provenance_carries_every_stated_field():
    rec = _freesound_record()
    prov = sound_provenance(rec, archived_sha256="a", sha256="b", fmt="wav", subtype="PCM_16")
    for name in SOURCE_STATED_FIELDS:
        assert name in prov
    assert any(FREESOUND_UPF in n for n in prov["terms_notes"])
    json.dumps(prov)  # JSON-native


def test_terms_notes_reach_the_credits_manifest_but_not_the_published_credits():
    credits = credits_for([_freesound_record()])
    assert any(FREESOUND_UPF in n for n in credits.manifest["entries"][0]["terms_notes"])
    assert FREESOUND_UPF not in credits.markdown


def test_terms_notes_outlive_an_edit_and_a_restamp():
    source = stamp_source_terms(_verified("CC-BY-4.0"), {"terms_notes": ["src terms"]})
    out = narrow_to_source(_verified("Stability-Community"), source)
    assert out.terms_notes == ["src terms"]
    fresh = carry_lineage(_verified("user-owned"), source)
    assert fresh.terms_notes == ["src terms"]


# -- restamps: terms notes are not rights (review of PR #248) --------------------


def _legacy_freesound(license_id):
    """A Freesound record stored before #77: no terms notes."""
    rec = _freesound_record(license_id)
    rec.license.terms_notes = []
    return rec.license


def test_a_legacy_freesound_record_is_not_widened_and_gains_the_note():
    stored = _legacy_freesound("https://creativecommons.org/licenses/by/4.0/")
    fresh = _freesound_record("https://creativecommons.org/publicdomain/zero/1.0/").license
    new, note = restamped_license(stored, fresh, widen=False)
    assert note.startswith("not widened")  # not "licences conflict"
    assert new.license_id == "CC-BY-4.0" and new.derived_from_license_ids == []
    assert any(FREESOUND_UPF in n for n in new.terms_notes)
    assert stored.terms_notes == []  # pure


def test_a_matching_licence_only_gains_the_note_silently():
    url = "https://creativecommons.org/licenses/by/4.0/"
    stored, fresh = _legacy_freesound(url), _freesound_record(url).license
    new, note = restamped_license(stored, fresh, widen=False)
    assert note is None and new.license_id == "CC-BY-4.0"
    assert any(FREESOUND_UPF in n for n in new.terms_notes)
    assert restamped_license(new, fresh, widen=False) == (None, None)  # idempotent


def test_a_narrower_fresh_licence_replaces_with_no_terms_notes_complaint():
    stored = _legacy_freesound("https://creativecommons.org/publicdomain/zero/1.0/")
    fresh = _freesound_record("https://creativecommons.org/licenses/by/4.0/").license
    new, note = restamped_license(stored, fresh, widen=False)
    assert new.license_id == "CC-BY-4.0" and "terms_notes" not in note
    assert any(FREESOUND_UPF in n for n in new.terms_notes)


def test_a_restamp_keeps_the_facts_about_the_bytes_and_an_assertion_drops_the_basis():
    old = stamp_source_terms(_verified("fal-partner-unverified"), {
        "license_basis": "vendor-tos", "license_basis_confidence": "unverified",
        "vendor_trains_on_output": True,
        "vendor_watermark": {"present": True, "reported_by": "response"}})  # fmt: skip
    kept = carry_lineage(_verified("CC0-1.0"), old)
    assert kept.vendor_trains_on_output is True and kept.vendor_watermark["present"]
    asserted = _restamped(old, "user-owned")
    assert asserted.rights_verified and asserted.license_basis is None
    assert asserted.license_basis_confidence is None
    assert asserted.vendor_trains_on_output is True  # still a fact about the bytes


# -- restamps of a re-made sound (#271): fresh credits and lineage, never wider ----------


def test_a_remade_restamp_replaces_credits_and_lineage():
    stored = _verified("CC-BY-4.0", creator_name="Ann", transformations=[{"op": "a"}])
    fresh = _verified("CC-BY-4.0", creator_name="Carol", transformations=[{"op": "b"}])
    assert restamped_license(stored, fresh, widen=False) == (None, None)  # lineage kept
    new, note = restamped_license(stored, fresh, widen=False, remade=True)
    assert new.creator_name == "Carol" and new.transformations == [{"op": "b"}]
    assert "credits and lineage replaced" in note
    assert restamped_license(new, fresh, widen=False, remade=True) == (None, None)


def test_a_remade_restamp_never_drops_a_licence_bounding_the_sound():
    stored = _verified("CC0-1.0", derived_from_license_ids=["CC-BY-NC-4.0"])
    fresh = _verified("CC0-1.0", derived_from_license_ids=["CC-BY-4.0"])
    new, note = restamped_license(stored, fresh, widen=False, remade=True)
    assert new is None and note.startswith("not widened") and "drops CC-BY-NC-4.0" in note
    narrower, _ = restamped_license(fresh, stored, widen=False, remade=True)
    assert narrower.derived_from_license_ids == ["CC-BY-NC-4.0"]  # CC-BY no longer bounds


def test_a_licence_id_swap_the_flags_cannot_show_is_not_widened():
    ncsa = _verified("CC-BY-NC-SA-4.0")
    sa = _verified("CC-BY-SA-4.0")
    for remade in (False, True):
        new, note = restamped_license(ncsa, sa, widen=False, remade=remade)
        assert new is None and note.startswith("not widened") and "commercial" in note
        narrower, _ = restamped_license(sa, ncsa, widen=False, remade=remade)
        assert narrower.license_id == "CC-BY-NC-SA-4.0"


def test_a_restamp_never_undiscloses_ai_provenance():
    stored = _verified("CC-BY-4.0", is_ai_generated=True, disclosure_recommended=True,
                       generator_model="m", c2pa_manifest_ref="c2pa://x")  # fmt: skip
    fresh = _verified("CC-BY-4.0", creator_name="Carol", attribution_text="by Carol")
    for remade in (False, True):
        new, _ = restamped_license(stored, fresh, widen=False, remade=remade)
        assert new.is_ai_generated and new.disclosure_recommended
        assert (new.generator_model, new.c2pa_manifest_ref) == ("m", "c2pa://x")
