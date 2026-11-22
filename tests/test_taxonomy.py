"""Tests for the UCS/AudioSet taxonomy resolver (``foley.index.taxonomy``).

Pure stdlib — no optional dependencies. Covers the UCS-filename parse, the staged
resolver precedence (filename > keyword > audioset > none), word-boundary
matching (so "brainstorm" never resolves to rain), the fail-fast AudioSet-map
validation, and the open/closed JSON drop merge.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from foley.base import SoundRecord
from foley.index.taxonomy import (
    DEFAULT_MATCH_POLICY,
    KeywordResolver,
    MatchPolicy,
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
    assert parse_ucs_filename("RAIN_Heavy_JD_NYC.wav") == ("RAIN", "GENERAL")
    assert parse_ucs_filename("rain_loop.wav") == (None, None)
    assert parse_ucs_filename("mix_final.wav") == (None, None)


@pytest.mark.parametrize(
    "name",
    ["RAW_01.wav", "MIX_final.wav", "REF_track_v2.wav", "TEST_tone.wav", "IR_hall.wav",
     "PROD_meeting_notes.wav", "ADR_line12.wav", "ASSET_logo.wav", "WIP_draft.wav",
     "RAIN_02.wav", "WIND_01.wav", "STORM_2024.wav"],
)  # fmt: skip
def test_an_all_capitals_catid_needs_every_mandatory_block(name):
    """RAW, MIX, REF are UCS CatIDs (ARCHIVED), and also how ordinary names start."""
    assert parse_ucs_filename(name) == (None, None)


def test_an_ordinary_name_never_beats_a_declared_catid():
    assert resolve_catid(filename="RAW_take3.wav", catid="DOORWood").catid == "DOORWood"
    assert resolve_catid(filename="MIX_final_JD_NYC.wav").catid == "MIX"  # every block
    # a mixed-case CatID stays lenient: one block after it is enough
    assert parse_ucs_filename("DOORWOOD_x.wav") == ("DOORS", "WOOD")


def test_a_legacy_catid_finds_its_real_row():
    """A record stamped by the pre-master seed (WEATHRain) still finds RAIN."""
    from foley.index.taxonomy import LEGACY_CATIDS, default_ucs_table, format_ucs_name

    table = default_ucs_table()
    assert table.get("WEATHRain").catid == "RAIN" and "GLASBreak" in table
    assert all(table.get(old).catid == new for old, new in LEGACY_CATIDS.items())
    assert format_ucs_name(catid="WEATHRain", fx_name="Heavy", creator_id="JD",
                           source_id="NYC") == "RAIN_Heavy_JD_NYC"  # fmt: skip
    assert "IMPTGeneral" not in table  # UCS has no generic impact row
    assert "WEATHRain" not in load_ucs_table(legacy_catids={})


def test_an_empty_table_is_refused():
    with pytest.raises(ValueError, match="include_seed"):
        load_ucs_table(master=None, include_seed=False)


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
    # in one field, 'engine car' and 'glass break' are phrases...
    assert "engine car" in resolve_catid(caption="engine car was parked").matched_terms
    assert resolve_catid(caption="glass break room").catid == "GLASBrk"
    # ...split between a tag and the caption, they are not
    res = resolve_catid(tags=["engine"], caption="car was parked")
    assert "engine car" not in res.matched_terms
    res2 = resolve_catid(tags=["glass"], caption="break room where staff relax")
    assert "glass break" not in res2.matched_terms and res2.catid == "GLASMisc"


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
    # "doors"/"creaking"/"drips" reach DOORS, "door creak", drip; "wooden door" is a phrase
    assert resolve_catid(caption="old wooden doors creaking").catid == "DOORWood"
    assert resolve_catid(caption="water drips into a sink").catid == "WATRDrip"
    assert resolve_catid(caption="wall clock ticks").catid == "CLOCKTick"


@pytest.mark.parametrize(
    "word, base",
    [("rattling", "rattle"), ("screens", "screen"), ("creaking", "creak"),
     ("dripping", "drip"), ("cries", "cry"), ("buzzes", "buzz"), ("door", "door")],
)  # fmt: skip
def test_an_inflection_meets_its_vocabulary_word(word, base):
    from foley.index.taxonomy import default_ucs_table
    from foley.index.taxonomy.resolver import term_index

    index = term_index(default_ucs_table())
    assert index.lemmas(word) == index.lemmas(base) != frozenset()


@pytest.mark.parametrize(
    "word, other",
    [("golden", "gold"), ("chicken", "chick"), ("scraping", "scrap"), ("news", "new"),
     ("thing", "the"), ("tired", "tire")],
)  # fmt: skip
def test_no_word_is_conflated_with_a_different_word(word, other):
    """Inflections are listed for the vocabulary, never stripped from the query."""
    from foley.index.taxonomy import default_ucs_table
    from foley.index.taxonomy.resolver import term_index

    index = term_index(default_ucs_table())
    assert not index.lemmas(word) & index.lemmas(other)


def test_the_term_index_is_built_once_per_table():
    from foley.index.taxonomy import default_ucs_table
    from foley.index.taxonomy.resolver import term_index

    table = default_ucs_table()
    assert term_index(table) is term_index(table)
    assert not hasattr(table, "term_index")  # the table stays plain data


def test_a_phrase_matches_across_function_words():
    res = resolve_catid(caption="steady rain on a window")  # seed: "rain on window"
    assert res.catid == "RAIN" and "rain on window" in res.matched_terms


def test_archived_bookkeeping_rows_are_never_keyword_picks():
    # TMARK / SCNE / WIP are UCS CatIDs for production bookkeeping, not sounds
    caption = "a work in progress test tone"
    everything = replace(DEFAULT_MATCH_POLICY, skip_categories=frozenset())
    assert resolve_catid(caption=caption, policy=everything).catid == "WIP"  # it would win
    res = resolve_catid(caption=caption)
    assert res.category != "ARCHIVED" and res.confidence <= DEFAULT_MATCH_POLICY.weak_confidence
    assert resolve_catid(filename="WIP_draft_JD_X.wav").catid == "WIP"  # names still do


def test_the_match_policy_is_the_one_seam():
    open_words = replace(DEFAULT_MATCH_POLICY, ambiguous_words=frozenset())
    assert resolve_catid(caption="a quiet afternoon").catid is None
    assert resolve_catid(caption="a quiet afternoon", policy=open_words).catid == "CRWDQuiet"
    no_stops = replace(DEFAULT_MATCH_POLICY, stop_words=frozenset())
    assert "rain on window" in resolve_catid(caption="rain on a window").matched_terms
    assert "rain on window" not in resolve_catid(caption="rain on a window",
                                                 policy=no_stops).matched_terms  # fmt: skip
    logo = SoundRecord(id="s", caption="trademarked logo")
    assert KeywordResolver().resolve(logo).catid is None  # TMARK is ARCHIVED
    everything = replace(DEFAULT_MATCH_POLICY, skip_categories=frozenset())
    assert KeywordResolver(policy=everything).resolve(logo).catid == "TMARK"
    loud = replace(DEFAULT_MATCH_POLICY, weak_confidence=0.3)
    assert resolve_catid(caption="glass", policy=loud).confidence == 0.3


def test_a_policy_with_bands_out_of_order_is_refused():
    with pytest.raises(ValueError, match="descend"):
        MatchPolicy(strong_confidence=0.5, single_confidence=0.7)
    with pytest.raises(ValueError, match="kind_weights"):
        MatchPolicy(kind_weights={"synonym": 1.0})


# ---------------------------------------------------------------------------
# the probe set: pinned outcomes and bands
# ---------------------------------------------------------------------------

STRONG, SINGLE, WEAK = (DEFAULT_MATCH_POLICY.strong_confidence,
                        DEFAULT_MATCH_POLICY.single_confidence,
                        DEFAULT_MATCH_POLICY.weak_confidence)  # fmt: skip

# caption -> (CatID, band)
PROBE_POSITIVES = {
    "a heavy wooden door creaks open": ("DOORWood", STRONG),
    "heavy rainfall outside": ("RAIN", SINGLE),
    "steady rain on a window": ("RAIN", STRONG),
    "distant thunder rumble storm": ("THUN", STRONG),
    "the sound of glass break": ("GLASBrk", STRONG),
    "glass shattering on the floor": ("GLASBrk", STRONG),
    "a dog barked in the distance": ("ANMLDog", STRONG),
    "a cat meows": ("ANMLCat", STRONG),
    "a doorknob turning": ("DOORHdwr", SINGLE),
    "car horn honk": ("VEHHorn", STRONG),
    "footsteps on gravel": ("FEETHmn", STRONG),
    "a crackling fire": ("FIREBurn", STRONG),  # the seed's phrase
    "water splash": ("WATRSplsh", STRONG),
    "ocean waves crash on rocks": ("WATRWave", STRONG),
    "church bell tolls": ("BELLLrg", STRONG),
    "wall clock ticks": ("CLOCKTick", STRONG),
    "crowd applause": ("CRWDApls", STRONG),
    "a whisper": ("VOXWhsp", STRONG),
    "jet plane overhead": ("AEROJet", STRONG),
    "train horn": ("TRNHorn", STRONG),
    "page turn": ("PAPRHndl", STRONG),
    "old telephone rings": ("COMTelph", STRONG),
    "a gust of wind blowing past": ("WINDGust", STRONG),
    "water drips into a sink": ("WATRDrip", STRONG),
    "wind howling": ("WINDTonl", STRONG),
    "glass door": ("DOORGlas", STRONG),
    "metal door": ("DOORMetl", STRONG),
    "wind up toy": ("TOYMech", STRONG),
    # a category's own name lands on its generic row, at the weak band
    "glass": ("GLASMisc", WEAK),
    "chains rattling": ("CHAINMisc", WEAK),
    "the wind picked up": ("WIND", WEAK),
    "vehicles": ("VEHMisc", WEAK),
}

#: Ordinary sentences: nothing, or nothing above the weak band.
PROBE_NEGATIVES = [
    "a productive brainstorm session", "let's take a coffee break",
    "he had a shot of espresso", "a quiet afternoon", "she opened the letter and smiled",
    "he thought about his mother", "the meeting ran long", "a weather report on tv tonight",
    "they talked about the release date", "the price went up", "the price went up a little",
    "she felt a little blue", "a long day at work", "he signed the contract",
    "he was tired", "the evening news report", "turn left at the light", "take a break",
    "a cup of coffee", "the phone rang", "we drove to work", "it was a good day",
]  # fmt: skip


@pytest.mark.parametrize("caption", PROBE_POSITIVES)
def test_probe_positive(caption):
    catid, band = PROBE_POSITIVES[caption]
    res = resolve_catid(caption=caption)
    assert (res.catid, res.confidence) == (catid, band), res.matched_terms


@pytest.mark.parametrize("caption", PROBE_NEGATIVES)
def test_probe_negative_stays_at_most_weak(caption):
    res = resolve_catid(caption=caption)
    assert res.confidence <= WEAK, (res.catid, res.matched_terms)


def test_a_lone_synonym_is_banded_by_how_many_rows_share_it():
    # one word, one row lists it -> single; many rows share it -> weak
    assert resolve_catid(caption="a doorknob").confidence == SINGLE
    assert resolve_catid(caption="a coffee").confidence == WEAK


def test_a_weak_keyword_match_yields_to_an_audioset_hit():
    res = resolve_catid(caption="a weather report", audioset_labels=["Thunder"])
    assert (res.source, res.catid) == ("audioset", "THUN")


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
