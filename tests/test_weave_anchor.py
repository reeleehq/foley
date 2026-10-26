"""WEAVE anchor heuristics + the symbolic-anchor bridge (pure, stdlib-only)."""

from foley.base import Anchor, Layer, Placement
from foley.weave.anchor import (
    _nearest_word,
    _segment_sentences,
    _snap_to_pause,
    parse_symbolic_anchor,
    resolve_anchor,
)

WT = [
    {"word": "the", "start": 0.0, "end": 0.2},
    {"word": "heavy", "start": 0.2, "end": 0.5},
    {"word": "door", "start": 0.5, "end": 0.8},
    {"word": "opened.", "start": 0.8, "end": 1.2},
    {"word": "rain", "start": 2.0, "end": 2.3},  # gap > 0.35 -> new sentence
    {"word": "fell", "start": 2.3, "end": 2.6},
]


def test_parse_word_anchor():
    p = parse_symbolic_anchor("on 'door'", layer=Layer.sfx_fg, loop=False)
    assert p.anchor is Anchor.word and p.ref == "door"


def test_parse_bed_is_sentence_span():
    p = parse_symbolic_anchor("on 'rain'", layer=Layer.ambience, loop=True)
    assert p.anchor is Anchor.sentence and p.ref == "rain"
    p2 = parse_symbolic_anchor(None, layer=Layer.ambience, loop=True)
    assert p2.anchor is Anchor.sentence and p2.ref is None


def test_parse_stinger_is_scene_boundary():
    p = parse_symbolic_anchor("on 'the reveal'", layer=Layer.stinger)
    assert p.anchor is Anchor.scene and p.ref == "the reveal"


def test_parse_none_oneshot_is_absolute():
    p = parse_symbolic_anchor(None, layer=Layer.sfx_fg, loop=False)
    assert p.anchor is Anchor.absolute


def test_parse_numeric_fallback():
    p = parse_symbolic_anchor("3.5")
    assert p.anchor is Anchor.absolute and p.onset == 3.5


def test_resolve_word_onset():
    p = parse_symbolic_anchor("on 'door'", layer=Layer.sfx_fg)
    onset, dur = resolve_anchor(p, WT)
    assert onset == 0.5 and dur is None


def test_resolve_word_preroll_clamped():
    onset, _ = resolve_anchor(Placement(anchor=Anchor.word, ref="door", pre_roll=0.3), WT)
    assert abs(onset - 0.2) < 1e-9
    onset2, _ = resolve_anchor(Placement(anchor=Anchor.word, ref="the", pre_roll=1.0), WT)
    assert onset2 == 0.0  # clamped at 0


def test_resolve_sentence_span_fills_duration():
    onset, dur = resolve_anchor(Placement(anchor=Anchor.sentence, ref="door"), WT)
    assert onset == 0.0 and abs(dur - 1.2) < 1e-9  # first sentence 0.0..1.2


def test_resolve_sentence_no_ref_is_whole():
    onset, dur = resolve_anchor(Placement(anchor=Anchor.sentence, ref=None), WT)
    assert onset == 0.0 and abs(dur - 2.6) < 1e-9  # whole narration span


def test_segment_sentences_splits_on_gap_and_punct():
    segs = _segment_sentences(WT)
    assert len(segs) == 2
    assert [w["word"] for w in segs[0]] == ["the", "heavy", "door", "opened."]
    assert [w["word"] for w in segs[1]] == ["rain", "fell"]


def test_nearest_word_exact_prefix_fuzzy():
    assert _nearest_word("door", WT)["word"] == "door"  # exact
    assert _nearest_word("doors", WT)["word"] == "door"  # prefix/fuzzy
    assert _nearest_word("zzzzz", WT) is None  # nothing close


def test_absolute_uses_stored_onset():
    onset, _ = resolve_anchor(Placement(anchor=Anchor.absolute, onset=4.2), WT)
    assert onset == 4.2


def test_empty_word_timeline_falls_back_to_stored_onset():
    onset, _ = resolve_anchor(Placement(anchor=Anchor.word, ref="door", onset=1.0), [])
    assert onset == 1.0


def test_snap_to_pause_moves_onset_into_gap():
    # a pause exists between "opened." (ends 1.2) and "rain" (starts 2.0): mid = 1.6
    snapped = _snap_to_pause(1.55, WT, radius_s=0.5)
    assert abs(snapped - 1.6) < 1e-9
    # no pause within radius -> unchanged
    assert _snap_to_pause(0.35, WT, radius_s=0.01) == 0.35
