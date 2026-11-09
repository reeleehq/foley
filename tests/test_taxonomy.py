"""Tests for the UCS/AudioSet taxonomy resolver (``foley.index.taxonomy``).

Pure stdlib — no optional dependencies. Covers the UCS-filename parse, the staged
resolver precedence (filename > keyword > audioset > none), word-boundary
matching (so "brainstorm" never resolves to rain), the fail-fast AudioSet-map
validation, and the open/closed JSON drop merge.
"""

import json
from pathlib import Path

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
    assert parse_ucs_filename("DOORWood_CreakOpen_JD_NYC.wav") == ("DOORS", "WOOD")


def test_parse_ucs_filename_with_full_path():
    assert parse_ucs_filename("/lib/sfx/RAINConc_Heavy_AB.flac") == ("RAIN", "CONCRETE")


def test_parse_ucs_filename_case_insensitive_catid():
    assert parse_ucs_filename("doorwood_x.wav") == ("DOORS", "WOOD")


def test_an_all_capitals_catid_is_case_sensitive():
    # RAIN, WIND, MIX are UCS CatIDs; in lower case they are words in a plain name
    assert parse_ucs_filename("RAIN_Heavy_AB.wav") == ("RAIN", "GENERAL")
    assert parse_ucs_filename("rain_loop.wav") == (None, None)
    assert parse_ucs_filename("mix_final.wav") == (None, None)


def test_parse_ucs_filename_non_conformant_returns_none():
    assert parse_ucs_filename("just-a-name.wav") == (None, None)
    assert parse_ucs_filename("nounderscore.wav") == (None, None)


def test_parse_ucs_filename_unknown_catid_fails_quiet():
    assert parse_ucs_filename("ZZZBogus_x.wav") == (None, None)


def test_parse_catid_token():
    assert parse_catid_token("DOORWood_x_y.wav") == "DOORWood"
    assert parse_catid_token("no-underscore.wav") is None


def test_parse_ucs_name_reads_every_block():
    from foley.index.taxonomy import UcsName, parse_ucs_name

    full = parse_ucs_name("/packs/doorwood-Gate_BOOM-Creak Open_JD_NYC_48k_take 2.wav")
    assert full == UcsName(
        catid="DOORWood", category="DOORS", subcategory="WOOD",
        fx_name="Creak Open", creator_id="JD", source_id="NYC",
        user_category="Gate", vendor_category="BOOM", user_data="48k_take 2",
    )  # fmt: skip
    plain = parse_ucs_name("RAINConc_Heavy_AB_Field.flac")
    assert (plain.fx_name, plain.vendor_category, plain.user_category) == ("Heavy", None, None)
    assert parse_ucs_name("DOORWood_.wav").fx_name is None  # empty block: absent
    # a hyphen inside an FX name is not a vendor separator; spaces are stripped
    for fx in ("Hand-Held Creak", "Sci-Fi Door", "Door Open - Slow"):
        n = parse_ucs_name(f"DOORWood_{fx}_JD_NYC.wav")
        assert (n.vendor_category, n.fx_name) == (None, fx)
    n = parse_ucs_name("DOORWood_BOOM - Creak_JD_NYC.wav")
    assert (n.vendor_category, n.fx_name) == ("BOOM", "Creak")
    # a dot that is not an extension stays in the name; only the extension goes
    n = parse_ucs_name("DOORWood_Creak 5.1_JD_NYC")
    assert (n.fx_name, n.creator_id, n.source_id) == ("Creak 5.1", "JD", "NYC")
    assert parse_ucs_name("DOORWood_Creak 5.1").fx_name == "Creak 5.1"  # .1 is no extension
    # a caller with its own vendor convention injects the predicate
    n = parse_ucs_name("DOORWood_Sci-Fi Door_JD_NYC.wav", is_vendor_tag=lambda p: True)
    assert (n.vendor_category, n.fx_name) == ("Sci", "Fi Door")
    assert parse_ucs_name("just-a-name.wav") is None
    # the category pair still comes out of a CatID with a UserCategory attached
    assert parse_ucs_filename("DOORWood-Gate_Creak_JD_NYC.wav") == ("DOORS", "WOOD")


# ---------------------------------------------------------------------------
# resolver — staged precedence
# ---------------------------------------------------------------------------


def test_resolve_keyword_door():
    res = resolve_catid(caption="a heavy wooden door creaks open")
    assert res.catid == "DOORWood"
    assert res.source == "keyword"
    assert res  # truthy


def test_resolve_keyword_from_tags():
    res = resolve_catid(tags=["rain", "downpour"])
    assert res.catid == "RAIN"


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
    assert res.catid == "THUN"
    assert res.source == "audioset"


def test_resolve_audioset_by_mid():
    res = resolve_catid(audioset_labels=["/m/06mb1"])  # rain MID in the seed map
    assert res.catid == "RAIN"
    assert res.source == "audioset"


def test_resolve_keyword_beats_audioset():
    res = resolve_catid(caption="wooden door", audioset_labels=["Thunder"])
    assert res.source == "keyword"
    assert res.catid == "DOORWood"


def test_resolve_none():
    res = resolve_catid(caption="he thought about it for a while")
    assert res.catid is None
    assert res.source is None
    assert res.confidence == 0.0


def test_ambiguous_common_words_do_not_false_positive():
    # bare English words that happen to equal a subcategory/synonym token must not
    # single-token-match (they only count inside a multi-word phrase)
    assert resolve_catid(caption="let's take a coffee break").catid != "GLASBrk"
    assert resolve_catid(caption="he had a shot of espresso").catid is None
    assert resolve_catid(caption="a quiet afternoon").catid is None  # not CRWDQuiet
    assert resolve_catid(caption="the price went up a little").catid is None
    # ...but the real multi-word phrase still resolves
    assert resolve_catid(caption="the sound of glass break").catid == "GLASBrk"
    assert resolve_catid(caption="quiet room tone").catid == "AMBRoom"


def test_multiword_phrase_does_not_straddle_field_boundary():
    # 'engine' (a tag) + 'car ...' (caption) must NOT match the phrase 'engine car'
    res = resolve_catid(tags=["engine"], caption="car was parked")
    assert "engine car" not in res.matched_terms
    res2 = resolve_catid(tags=["glass"], caption="break room where staff relax")
    assert "glass break" not in res2.matched_terms and res2.catid != "GLASBrk"


def test_category_only_match_is_weak_confidence():
    # only the category name 'weather' brushes -> weak band, below a strong hit
    weak = resolve_catid(caption="a weather report on tv tonight")
    strong = resolve_catid(caption="heavy rainfall outside")
    assert weak.catid == "WTHR"  # the category's generic (MISC) row...
    assert weak.confidence == 0.4  # ...but at the weak band
    assert strong.confidence > weak.confidence


def test_doorbell_is_filed_under_bells_not_telephony():
    res = resolve_catid(audioset_labels=["doorbell"])
    assert res.catid == "BELLDoor"


def test_resolve_is_deterministic():
    a = resolve_catid(caption="rain and thunder and wind together")
    b = resolve_catid(caption="rain and thunder and wind together")
    assert a == b


def test_confident_row_has_higher_confidence_than_approx(tmp_path):
    # every master row is confident; a house drop may add an unverified one
    drop = [{"catid": "ZZZHum", "category": "ZZZ", "subcategory": "HUM",
             "synonyms": ["gizmo hum"], "confident": False}]  # fmt: skip
    (tmp_path / "ucs_full.json").write_text(json.dumps(drop))
    table = load_ucs_table(data_dir=tmp_path)
    confident = resolve_catid(caption="wooden door", table=table)
    approx = resolve_catid(caption="a gizmo hum", table=table)
    assert approx.catid == "ZZZHum"
    assert confident.confidence > approx.confidence


def test_inflections_meet_their_base_form():
    # "doors"/"creaks"/"wooden"/"drips" reach DOORS, creak, WOOD, drip
    assert resolve_catid(caption="old wooden doors creaking").catid == "DOORWood"
    assert resolve_catid(caption="water drips into a sink").catid == "WATRDrip"
    assert resolve_catid(caption="wall clock ticks").catid == "CLOCKTick"


def test_a_phrase_matches_across_function_words():
    res = resolve_catid(caption="steady rain on a window")  # seed: "rain on window"
    assert res.catid == "RAIN" and "rain on window" in res.matched_terms


def test_archived_bookkeeping_rows_are_never_keyword_picks():
    # TMARK / SCNE / WIP are UCS CatIDs for production bookkeeping, not sounds
    assert resolve_catid(caption="a work in progress test tone").catid not in {
        "WIP", "TEST", "TMARK"}  # fmt: skip
    assert resolve_catid(filename="WIP_draft_JD_X.wav").catid == "WIP"  # names still do


def test_the_stop_lists_are_seams():
    assert resolve_catid(caption="a quiet afternoon", ambiguous_words=frozenset()).catid
    logo = SoundRecord(id="s", caption="trademarked logo")
    assert KeywordResolver().resolve(logo).catid is None  # TMARK is ARCHIVED
    assert KeywordResolver(skip_categories=frozenset()).resolve(logo).catid == "TMARK"


# ---------------------------------------------------------------------------
# KeywordResolver wraps a SoundRecord
# ---------------------------------------------------------------------------


def test_keyword_resolver_over_record():
    rec = SoundRecord(id="s1", caption="distant thunder rumble", tags=["storm"])
    res = KeywordResolver().resolve(rec)
    assert res.catid == "THUN"


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


def test_ucs_table_merges_json_drop_over_the_master(tmp_path):
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


def test_the_ucs_master_ships_whole_and_is_the_default():
    """#227/#237: the v8.2.1 master (753 rows, 82 categories) ships and is the default."""
    import json

    from foley.index.taxonomy import default_ucs_table, load_ucs_master, parse_ucs_name
    from foley.index.taxonomy.ucs import UCS_MASTER_FILE

    master = load_ucs_master()
    assert len(master) == 753 and len({r.category for r in master}) == 82
    assert json.loads(UCS_MASTER_FILE.read_text("utf-8"))["version"] == "8.2.1"
    row = master.get("AIRBlow")
    assert (row.category, row.subcategory, row.confident) == ("AIR", "BLOW", True)
    raw = json.loads(UCS_MASTER_FILE.read_text("utf-8"))["rows"]
    assert all(s == s.lower() for r in raw for s in r["synonyms"])  # as shipped
    assert row.explanation and "sauté" in master.get("FOODCook").synonyms  # repaired
    assert "WOODHndl" in master and "WOODHandl" not in master  # the 8.2.1 fix
    name = parse_ucs_name("RAINConc_Heavy on pavement_JD_NYC.wav", table=master)
    assert name is not None and name.category == "RAIN"
    default = default_ucs_table()
    assert len(default) == 753 and all(r.catid in default for r in master)  # #237
    assert set(master.get("RAIN").synonyms) < set(default.get("RAIN").synonyms)  # + seed
    assert load_ucs_table(master=None).get("RAIN").synonyms  # the offline fallback


def test_the_seed_rows_are_real_master_rows():
    from foley.index.taxonomy import load_ucs_master
    from foley.index.taxonomy.seed import SEED_AUDIOSET_UCS_MAP, SEED_UCS_TABLE

    master = load_ucs_master()
    for d in SEED_UCS_TABLE:
        row = master.by_catid[d["catid"]]  # exact case: a real CatID
        assert (d["category"], d["subcategory"]) == (row.category, row.subcategory)
    assert all(d["catid"] in master.by_catid for d in SEED_AUDIOSET_UCS_MAP)


def test_the_ucs_build_tool_reads_the_master_layout(tmp_path):
    """tools/build_ucs_table.py: title rows and blanks skipped, synonyms split, mojibake undone."""
    import importlib.util

    tool = Path(__file__).resolve().parents[1] / "tools" / "build_ucs_table.py"
    spec = importlib.util.spec_from_file_location("build_ucs_table", tool)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.unmojibake("saut‚àö¬©") == "sauté" and build.unmojibake("café") == "café"

    openpyxl = pytest.importorskip("openpyxl")  # a dev-only dependency of the tool

    wb = openpyxl.Workbook()
    ws = wb.active
    for row in (
        [None, "UCS v8.2.1 Category List"],
        ["a note"],
        list(build.HEADER) + ["Synonyms - Comma Separated"],
        ["FOOD", "COOKING", "FOODCook", "FOOD", "Cooking.", "Fry, saut‚àö¬©, fry"],
        [None, None, None],
    ):
        ws.append(row)
    wb.save(tmp_path / "ucs.xlsx")
    assert build.read_rows(tmp_path / "ucs.xlsx") == [
        {"catid": "FOODCook", "category": "FOOD", "subcategory": "COOKING",
         "explanation": "Cooking.", "synonyms": ["fry", "sauté"], "confident": True}
    ]  # fmt: skip
