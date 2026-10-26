"""Tests for the UCS/AudioSet taxonomy resolver (``foley.index.taxonomy``).

Pure stdlib — no optional dependencies. Covers the UCS-filename parse, the staged
resolver precedence (filename > keyword > audioset > none), word-boundary
matching (so "brainstorm" never resolves to rain), the fail-fast AudioSet-map
validation, and the open/closed JSON drop merge.
"""

import json

import pytest

from foley.base import SoundRecord
from foley.index.taxonomy import (
    KeywordResolver,
    load_audioset_ucs_map,
    load_ucs_table,
    parse_ucs_filename,
    resolve_catid,
)
from foley.index.taxonomy.ucs import parse_catid_token


# ---------------------------------------------------------------------------
# UCS filename parse
# ---------------------------------------------------------------------------


def test_parse_ucs_filename_valid():
    assert parse_ucs_filename("DOORWood_CreakOpen_JD_NYC.wav") == ("DOORS", "Wood")


def test_parse_ucs_filename_with_full_path():
    assert parse_ucs_filename("/lib/sfx/WEATHRain_Heavy_AB.flac") == ("WEATHER", "Rain")


def test_parse_ucs_filename_case_insensitive_catid():
    assert parse_ucs_filename("doorwood_x.wav") == ("DOORS", "Wood")


def test_parse_ucs_filename_non_conformant_returns_none():
    assert parse_ucs_filename("just-a-name.wav") == (None, None)
    assert parse_ucs_filename("nounderscore.wav") == (None, None)


def test_parse_ucs_filename_unknown_catid_fails_quiet():
    assert parse_ucs_filename("ZZZBogus_x.wav") == (None, None)


def test_parse_catid_token():
    assert parse_catid_token("DOORWood_x_y.wav") == "DOORWood"
    assert parse_catid_token("no-underscore.wav") is None


# ---------------------------------------------------------------------------
# resolver — staged precedence
# ---------------------------------------------------------------------------


def test_resolve_keyword_door():
    res = resolve_catid(caption="a heavy wooden door creaks open")
    assert res.catid == "DOORWood"
    assert res.source == "keyword"
    assert res  # truthy


def test_resolve_keyword_from_tags():
    res = resolve_catid(tags=["rain", "storm"])
    assert res.catid == "WEATHRain"


def test_resolve_word_boundary_no_false_positive():
    # 'rain' must not match inside 'brainstorm'
    res = resolve_catid(caption="a productive brainstorm session")
    assert res.catid is None
    assert not res


def test_resolve_filename_beats_keyword():
    res = resolve_catid(caption="rain everywhere", filename="DOORWood_x.wav")
    assert res.source == "filename"
    assert res.catid == "DOORWood"
    assert res.confidence == 1.0


def test_resolve_audioset_by_name():
    res = resolve_catid(audioset_labels=["Thunder"])
    assert res.catid == "WEATHThunder"
    assert res.source == "audioset"


def test_resolve_audioset_by_mid():
    res = resolve_catid(audioset_labels=["/m/06mb1"])  # rain MID in the seed map
    assert res.catid == "WEATHRain"
    assert res.source == "audioset"


def test_resolve_keyword_beats_audioset():
    res = resolve_catid(caption="wooden door", audioset_labels=["Thunder"])
    assert res.source == "keyword"
    assert res.catid == "DOORWood"


def test_resolve_none():
    res = resolve_catid(caption="an abstract concept with no sound word")
    assert res.catid is None
    assert res.source is None
    assert res.confidence == 0.0


def test_ambiguous_common_words_do_not_false_positive():
    # bare English words that happen to equal a subcategory/synonym token must not
    # single-token-match (they only count inside a multi-word phrase)
    assert resolve_catid(caption="let's take a coffee break").catid != "GLASBreak"
    assert resolve_catid(caption="he had a shot of espresso").catid != "GUNHandgun"
    assert resolve_catid(caption="the song was a big hit").catid != "IMPTGeneral"
    # ...but the real multi-word phrase still resolves
    assert resolve_catid(caption="the sound of glass break").catid == "GLASBreak"


def test_multiword_phrase_does_not_straddle_field_boundary():
    # 'engine' (a tag) + 'car ...' (caption) must NOT match the phrase 'engine car'
    # across the field boundary; neither word matches alone, so nothing resolves.
    res = resolve_catid(tags=["engine"], caption="car was parked")
    assert res.catid is None
    # and the straddling phrase never appears among the matched terms
    res2 = resolve_catid(tags=["glass"], caption="break room where staff relax")
    assert "glass break" not in res2.matched_terms


def test_category_only_match_is_weak_confidence():
    # only the category name 'weather' brushes -> weak band, below a strong hit
    weak = resolve_catid(caption="a weather report on tv tonight")
    strong = resolve_catid(caption="heavy rainfall outside")
    assert weak.catid == "WEATHRain"  # category coincidence still resolves...
    assert weak.confidence == 0.4  # ...but at the weak band
    assert strong.confidence > weak.confidence


def test_doorbell_is_not_misfiled_to_telephony():
    # the wrong doorbell->COMMPhone seed row was removed; leave it unresolved
    res = resolve_catid(audioset_labels=["doorbell"])
    assert res.catid is None


def test_resolve_is_deterministic():
    a = resolve_catid(caption="rain and thunder and wind together")
    b = resolve_catid(caption="rain and thunder and wind together")
    assert a == b


def test_confident_row_has_higher_confidence_than_approx():
    confident = resolve_catid(caption="wooden door")  # DOORWood is confident
    approx = resolve_catid(caption="a doorknob turning")  # DOORKnob is approx
    assert confident.confidence > approx.confidence


# ---------------------------------------------------------------------------
# KeywordResolver wraps a SoundRecord
# ---------------------------------------------------------------------------


def test_keyword_resolver_over_record():
    rec = SoundRecord(id="s1", caption="distant thunder rumble", tags=["storm"])
    res = KeywordResolver().resolve(rec)
    assert res.catid == "WEATHThunder"


def test_keyword_resolver_uses_record_uri_as_filename():
    rec = SoundRecord(id="s1", uri="DOORWood_creak.wav", caption="something rainy")
    res = KeywordResolver().resolve(rec)
    assert res.source == "filename" and res.catid == "DOORWood"


# ---------------------------------------------------------------------------
# loaders — validation + open/closed JSON drop
# ---------------------------------------------------------------------------


def test_audioset_map_targets_are_all_valid_catids():
    # the seed map loads clean iff every target CatID exists in the UCS table
    amap = load_audioset_ucs_map()
    table = load_ucs_table()
    assert all(catid in table for catid in amap.by_name.values())


def test_audioset_map_rejects_unknown_catid(tmp_path):
    bad = [{"name": "gizmo", "catid": "NOPEBogus"}]
    (tmp_path / "audioset_ucs.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="unknown CatID"):
        load_audioset_ucs_map(data_dir=tmp_path)


def test_ucs_table_merges_json_drop_over_seed(tmp_path):
    # a JSON drop overrides a seed row and adds a new one (open/closed)
    drop = [
        {"catid": "DOORWood", "category": "DOORS", "subcategory": "Wood",
         "synonyms": ["portal"], "confident": True},
        {"catid": "SPACEHum", "category": "SPACE", "subcategory": "Hum",
         "synonyms": ["space hum", "sci-fi drone"], "confident": True},
    ]
    (tmp_path / "ucs_full.json").write_text(json.dumps(drop))
    table = load_ucs_table(data_dir=tmp_path)
    assert "SPACEHum" in table
    res = resolve_catid(caption="a sci-fi drone hum", table=table,
                        audioset_map=load_audioset_ucs_map(table=table))
    assert res.catid == "SPACEHum"
