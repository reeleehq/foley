"""Tests for the TASL provenance/credits generator (``foley.provenance.credits``, #9a).

Stdlib-only: credits reads the ``LicenseRecord`` SSOT and renders text, so these
tests build ``SoundRecord`` / ``LicenseRecord`` fixtures directly — no numpy,
audio codec, or CLAP. They cover per-source credit generation, the title/author
fallback ladders, dedup, CC0-vs-CC-BY required-marking, the modification notice,
the AI-disclosure line, ``attribution_text`` precedence, Markdown link
degradation, deterministic ``CREDITS.md`` / JSON snapshots, graceful degradation,
and the ``foley.credits`` façade.
"""

from __future__ import annotations

import json

import foley
from foley.base import AcquisitionMethod, Candidate, LicenseRecord, SoundRecord
from foley.licensing import apply_license_flags, license_meta
from foley.provenance import (
    CreditEntry,
    Credits,
    attribution_line,
    credit_entry,
    credits_for,
    render_credits_md,
)


# ---------------------------------------------------------------------------
# fixtures — one LicenseRecord/SoundRecord per source kind (flags DERIVED)
# ---------------------------------------------------------------------------


def _license(license_id, *, source, **kw):
    """A LicenseRecord with its flags derived from license_id (the SSOT path)."""
    lic = LicenseRecord(source=source, license_id=license_id, **kw)
    return apply_license_flags(lic)


def _sound(sound_id, license, *, caption=None, tags=(), ucs_category=None):
    return SoundRecord(
        id=sound_id, license=license, caption=caption, tags=list(tags), ucs_category=ucs_category
    )


def _freesound_cc0():
    lic = _license(
        "CC0-1.0", source="freesound", source_id="12345",
        source_url="https://freesound.org/s/12345/", creator_name="alice",
        license_url="http://creativecommons.org/publicdomain/zero/1.0/",
        acquisition_method=AcquisitionMethod.api, rights_verified=True,
    )
    return _sound("freesound:12345", lic, caption="rain on window", tags=["rain", "window"])


def _fsd50k_ccby():
    lic = _license(
        "CC-BY-4.0", source="fsd50k", source_id="222",
        source_url="https://freesound.org/s/222/", creator_name="amy",
        acquisition_method=AcquisitionMethod.bulk, rights_verified=True,
    )
    return _sound("cafe_a1b2", lic, tags=["door", "creak", "wood"])


def _user_owned():
    lic = _license("user-owned", source="user", rights_verified=True)
    return _sound("hash_deadbeef", lic, caption="my recording")


# ---------------------------------------------------------------------------
# 1. per-source credit_entry
# ---------------------------------------------------------------------------


def test_credit_entry_freesound_cc0():
    e = credit_entry(_freesound_cc0())
    assert e.title == "rain on window"
    assert e.author == "alice"
    assert e.license_id == "CC0-1.0"
    assert e.license_name == "CC0 1.0 Universal (Public Domain Dedication)"
    # the record's own license_url (from the adapter) wins over the table default
    assert e.license_url == "http://creativecommons.org/publicdomain/zero/1.0/"
    assert e.requires_attribution is False  # CC0 needs no attribution
    assert e.modified is False


def test_credit_entry_fsd50k_ccby_uses_license_meta_url():
    e = credit_entry(_fsd50k_ccby())
    assert e.author == "amy"
    # no per-record license_url -> falls back to the LICENSE_META canonical URL
    assert e.license_url == license_meta("CC-BY-4.0").url
    assert e.requires_attribution is True
    # no caption -> title synthesized from tags (sentence-cased)
    assert e.title == "Door creak wood"


def test_credit_entry_user_owned_degrades_author_and_url():
    e = credit_entry(_user_owned())
    assert e.author == "user"  # no creator/rights_holder -> source
    assert e.license_url is None  # user-owned has no canonical URL
    assert e.requires_attribution is False


# ---------------------------------------------------------------------------
# 2. title fallback ladder
# ---------------------------------------------------------------------------


def test_title_fallback_ladder():
    lic = _license("CC-BY-4.0", source="fsd50k", source_id="s9")
    assert credit_entry(_sound("i", lic, caption="  A Caption  ")).title == "A Caption"
    assert credit_entry(_sound("i", lic, tags=["boom", "impact"])).title == "Boom impact"
    assert credit_entry(_sound("i", lic, ucs_category="explosion")).title == "Explosion"
    assert credit_entry(_sound("i", lic)).title == "fsd50k sound s9"
    lic2 = _license("unknown", source="x")  # no source_id -> sound_id
    assert credit_entry(_sound("theid", lic2)).title == "theid"


# ---------------------------------------------------------------------------
# 3. author fallback ladder
# ---------------------------------------------------------------------------


def test_author_fallback_ladder():
    base = dict(source="freesound", license_id="CC-BY-4.0")
    assert credit_entry(_sound("i", _license(creator_name="bob", **base))).author == "bob"
    assert credit_entry(_sound("i", _license(rights_holder="Acme", **base))).author == "Acme"
    assert credit_entry(_sound("i", _license(**base))).author == "freesound"


# ---------------------------------------------------------------------------
# 4. dedup + ordering
# ---------------------------------------------------------------------------


def test_dedup_first_writer_wins_stable_order():
    a, b = _freesound_cc0(), _fsd50k_ccby()
    c = credits_for([b, a, b, a])  # duplicates
    assert [e.sound_id for e in c] == ["cafe_a1b2", "freesound:12345"]  # appearance order


def test_sort_by_author_and_title():
    a, b = _freesound_cc0(), _fsd50k_ccby()  # authors alice, amy
    assert [e.author for e in credits_for([b, a], sort="author")] == ["alice", "amy"]
    assert [e.title for e in credits_for([a, b], sort="title")][0] == "Door creak wood"


# ---------------------------------------------------------------------------
# 5. CC0 vs CC-BY required marking + only_required
# ---------------------------------------------------------------------------


def test_only_required_drops_courtesy_credits():
    a, b = _freesound_cc0(), _fsd50k_ccby()  # CC0 (courtesy) + CC-BY (required)
    assert len(credits_for([a, b])) == 2  # default: credit everything
    req = credits_for([a, b], only_required=True)
    assert [e.sound_id for e in req] == ["cafe_a1b2"]  # only the CC-BY


# ---------------------------------------------------------------------------
# 6. modification notice
# ---------------------------------------------------------------------------


def test_modification_notice():
    lic = _license("CC-BY-4.0", source="fsd50k", creator_name="amy", transformations=["trim", "loudness"])
    e = credit_entry(_sound("i", lic, caption="thunder"))
    assert e.modified is True
    assert " (modified)" in attribution_line(e, fmt="plain")
    assert " (modified)" in attribution_line(e, fmt="markdown")
    # no transformations -> no notice
    e2 = credit_entry(_freesound_cc0())
    assert "(modified)" not in attribution_line(e2, fmt="markdown")


# ---------------------------------------------------------------------------
# 7. AI-disclosure line
# ---------------------------------------------------------------------------


def test_ai_disclosure_segment():
    def line(**gen):
        lic = _license("ElevenLabs-SFX", source="ElevenLabs", **gen)
        return attribution_line(_sound("g", lic, caption="whoosh"), fmt="markdown")

    assert " · AI-generated with eleven_v2" in line(is_ai_generated=True, generator_model="eleven_v2")
    assert line(is_ai_generated=True).endswith(" · AI-generated")  # model None
    assert "— disclosure recommended" in line(
        is_ai_generated=True, generator_model="m", disclosure_recommended=True
    )
    assert "AI-generated" not in line(is_ai_generated=False)


# ---------------------------------------------------------------------------
# 8. attribution_text precedence (verbatim)
# ---------------------------------------------------------------------------


def test_attribution_text_wins_verbatim():
    lic = _license("CC-BY-4.0", source="freesound", creator_name="amy")
    lic.attribution_text = "Custom credit, all rights per notice."
    e = credit_entry(_sound("i", lic, caption="ignored"))
    assert attribution_line(e, fmt="markdown") == "Custom credit, all rights per notice."
    assert attribution_line(e, fmt="plain") == "Custom credit, all rights per notice."


def test_attribution_text_still_gets_foley_owned_mod_and_ai_tail():
    # The source line can't know foley later modified / AI-generated the sound, so
    # the (modified) notice + AI-disclosure segment MUST still be appended (CC-BY
    # legally requires indicating modifications).
    lic = _license(
        "CC-BY-4.0", source="freesound", creator_name="amy",
        transformations=["trim", "fade"], is_ai_generated=True, generator_model="m",
    )
    lic.attribution_text = '"Rain" by amy / CC BY 4.0'
    line = attribution_line(credit_entry(_sound("i", lic)), fmt="markdown")
    assert line == '"Rain" by amy / CC BY 4.0 (modified) · AI-generated with m'


def test_title_ignores_leading_falsy_tags():
    lic = _license("CC-BY-4.0", source="fsd50k", source_id="s9")
    assert credit_entry(_sound("i", lic, tags=["", " ", "boom"])).title == "Boom"


# ---------------------------------------------------------------------------
# 9. Markdown link degradation
# ---------------------------------------------------------------------------


def test_markdown_degrades_without_urls():
    lic = _license("user-owned", source="user")  # no source_url/creator_url/license_url
    line = attribution_line(_sound("i", lic, caption="my clip"), fmt="markdown")
    assert line == '"my clip" by user — licensed under User-owned / original work'
    assert "](" not in line  # no markdown links at all


# ---------------------------------------------------------------------------
# 10. CREDITS.md + JSON snapshot determinism
# ---------------------------------------------------------------------------


def test_credits_md_snapshot():
    c = credits_for([_freesound_cc0(), _fsd50k_ccby()])
    expected = (
        "## Credits\n"
        "\n"
        '- "[rain on window](https://freesound.org/s/12345/)" by alice — licensed under '
        "[CC0 1.0 Universal (Public Domain Dedication)]"
        "(http://creativecommons.org/publicdomain/zero/1.0/)\n"
        '- "[Door creak wood](https://freesound.org/s/222/)" by amy — licensed under '
        "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)\n"
    )
    assert c.markdown == expected
    # determinism: identical inputs -> byte-identical output
    assert c.markdown == credits_for([_freesound_cc0(), _fsd50k_ccby()]).markdown


def test_empty_credits_md():
    c = credits_for([])
    assert c.markdown == "## Credits\n\n_No third-party sounds._\n"
    assert len(c) == 0


def test_manifest_shape_and_determinism():
    c = credits_for([_freesound_cc0()])
    m = c.manifest
    assert set(m) == {"entries", "title", "schema_version"}
    assert m["entries"][0]["requires_attribution"] is False
    assert m == json.loads(c.to_json())  # manifest == to_dict, JSON-safe
    # #9b pass-throughs, None today
    assert m["entries"][0]["watermark"] is None
    assert m["entries"][0]["c2pa_manifest_ref"] is None


def test_license_meta_covers_every_flags_row():
    # Drift guard: every keep()-permitted license_id must have a display row, else a
    # known license would render "Unknown / unverified license" in a published CREDITS.md.
    from foley.licensing import LICENSE_FLAGS, LICENSE_META

    assert set(LICENSE_META) == set(LICENSE_FLAGS)


def test_watermark_c2pa_pass_through_zero_render_change():
    # Forward-compat for #6/#9b: populated watermark / c2pa_manifest_ref flow into
    # the manifest verbatim, with ZERO change to the human-readable line.
    base = _license("CC0-1.0", source="freesound", creator_name="alice")
    marked = _license("CC0-1.0", source="freesound", creator_name="alice")
    marked.watermark = {"present": True, "method": "audioseal", "version": "1"}
    marked.c2pa_manifest_ref = "cr://abc123"

    entry = credits_for([_sound("s", marked, caption="rain")]).manifest["entries"][0]
    assert entry["watermark"] == {"present": True, "method": "audioseal", "version": "1"}
    assert entry["c2pa_manifest_ref"] == "cr://abc123"
    # the rendered line is byte-identical with vs without the pass-through fields
    line_of = lambda lic: attribution_line(credit_entry(_sound("s", lic, caption="rain")))
    assert line_of(marked) == line_of(base)


def test_invalid_fmt_and_sort_raise():
    import pytest

    with pytest.raises(ValueError, match="fmt"):
        attribution_line(credit_entry(_freesound_cc0()), fmt="xml")
    with pytest.raises(ValueError, match="sort"):
        credits_for([], sort="bogus")


# ---------------------------------------------------------------------------
# 11. graceful degradation + input coercion + round-trip
# ---------------------------------------------------------------------------


def test_bare_license_record_input():
    lic = _license("unknown", source="user")  # everything else None
    e = credit_entry(lic)  # a bare LicenseRecord
    assert e.sound_id == "unknown"  # content_sha256/source_id both None
    assert e.title == "unknown"
    assert e.license_name == "Unknown / unverified license"
    assert attribution_line(e)  # does not crash


def test_candidate_input_unwraps_to_sound():
    cand = Candidate(sound=_freesound_cc0())
    assert credit_entry(cand).sound_id == "freesound:12345"


def test_bad_input_type_raises():
    import pytest

    with pytest.raises(TypeError):
        credit_entry(42)


def test_credits_round_trips_through_json():
    c = credits_for([_freesound_cc0(), _fsd50k_ccby()])
    rt = Credits.from_json(c.to_json())
    assert all(isinstance(e, CreditEntry) for e in rt.entries)
    assert rt.to_dict() == c.to_dict()


# ---------------------------------------------------------------------------
# 12. foley.credits facade
# ---------------------------------------------------------------------------


def test_facade_returns_credits_and_is_exported():
    c = foley.credits([_freesound_cc0()])
    assert isinstance(c, Credits) and len(c) == 1
    for name in ("credits", "provenance", "Credits", "credits_for", "attribution_line"):
        assert name in foley.__all__


def test_facade_write_to_writes_both_artifacts(tmp_path):
    foley.credits([_freesound_cc0(), _fsd50k_ccby()], write_to=tmp_path)
    md = (tmp_path / "CREDITS.md").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "credits.json").read_text(encoding="utf-8"))
    assert md.startswith("## Credits")
    assert len(manifest["entries"]) == 2


def test_render_credits_md_heading_level_override():
    c = credits_for([_freesound_cc0()])
    assert render_credits_md(c, title="Sound credits", heading_level=3).startswith("### Sound credits")
