"""WEAVE anchor heuristics + the symbolic-anchor bridge (pure, stdlib-only)."""

from foley.base import Anchor, Layer, Placement
from foley.weave.anchor import (
    nearest_word,
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
    assert nearest_word("door", WT)["word"] == "door"  # exact
    assert nearest_word("doors", WT)["word"] == "door"  # prefix/fuzzy
    assert nearest_word("zzzzz", WT) is None  # nothing close


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


def test_a_short_unrelated_word_never_claims_a_cue():
    """#257: 'thunder' is not 'The' (difflib 0.6), and 'a' is not 'apple'."""
    from foley.weave.anchor import nearest_word

    wt = [{"word": w, "start": i * 0.5, "end": (i + 1) * 0.5}
          for i, w in enumerate("The heavy door slammed. A rain fell.".split())]  # fmt: skip
    assert nearest_word("thunder", wt) is None
    assert nearest_word("apple", wt) is None
    assert nearest_word("slam", wt)["word"] == "slammed."  # an inflection still matches
    assert nearest_word("doors", wt)["word"] == "door"
    assert nearest_word("rainy", wt)["word"] == "rain"  # fuzzy, long enough
    gun = [{"word": w, "start": i * 0.5, "end": (i + 1) * 0.5}
           for i, w in enumerate("A gun went off. Heavy steps followed.".split())]  # fmt: skip
    assert nearest_word("gunshot", gun)["word"] == "gun"  # a compound cue's spoken stem
    assert nearest_word("footsteps", gun)["word"] == "steps"


def _words(text):
    return [{"word": w, "start": i * 0.5, "end": (i + 1) * 0.5}
            for i, w in enumerate(text.split())]  # fmt: skip


def test_match_word_says_how_it_matched():
    """#263: exact / stem / fuzzy / fallback, so a false match is visible, not silent."""
    from foley.base import MatchKind
    from foley.weave.anchor import match_word

    def kind(cue, text):
        w, k = match_word(cue, _words(text))
        return (w and w["word"]), k

    assert kind("door", "the door opened") == ("door", MatchKind.exact)
    assert kind("slam", "it slammed.") == ("slammed.", MatchKind.stem)
    assert kind("footsteps", "soft steps") == ("steps", MatchKind.stem)
    assert kind("carpet", "the car stopped") == ("car", MatchKind.stem)  # a stem, not a meaning
    # 'th|under' is no compound: no longer a stem, and only a fuzzy match is left
    assert kind("thunder", "he hid under the bed") == ("under", MatchKind.fuzzy)
    assert kind("hiss", "This is it") == ("This", MatchKind.fuzzy)
    assert kind("xylophone", "the door opened") == (None, MatchKind.fallback)
    assert kind(None, "the door opened") == (None, MatchKind.fallback)


def test_resolve_placement_records_the_match_kind():
    from foley.base import MatchKind
    from foley.weave.anchor import resolve_placement

    def resolved(placement, wt=WT):
        return resolve_placement(placement, wt)

    p = resolved(Placement(anchor=Anchor.word, ref="door", pre_roll=0.1))
    assert (p.onset, p.match_kind) == (0.4, MatchKind.exact)
    assert resolved(Placement(anchor=Anchor.absolute, onset=4.2)).match_kind is MatchKind.absolute
    no_words = resolved(Placement(anchor=Anchor.word, ref="door", onset=1.0), [])
    assert (no_words.onset, no_words.match_kind) == (1.0, MatchKind.fallback)
    stray = resolved(Placement(anchor=Anchor.word, ref="xylophone", onset=3.0))
    assert (stray.onset, stray.match_kind) == (3.0, MatchKind.fallback)
    bed = resolved(Placement(anchor=Anchor.sentence, ref=None))  # spans by design
    assert (bed.onset, bed.duration, bed.match_kind) == (0.0, 2.6, MatchKind.absolute)
    lost = resolved(Placement(anchor=Anchor.sentence, ref="xylophone"))
    assert (lost.onset, lost.duration, lost.match_kind) == (0.0, 2.6, MatchKind.fallback)
    cueless = resolved(Placement(anchor=Anchor.sentence, ref=None, onset=0.0), [])
    assert cueless.match_kind is MatchKind.absolute  # names no word, timings or not
    scene = resolved(Placement(anchor=Anchor.scene, ref="rain"))
    assert (scene.onset, scene.match_kind) == (2.0, MatchKind.exact)
    # resolve_anchor stays the (onset, duration) view of the same resolver
    assert resolve_anchor(Placement(anchor=Anchor.sentence, ref="door"), WT) == (0.0, 1.2)


def test_a_nudge_pins_the_match_kind_to_absolute_with_the_anchor():
    from foley.base import MatchKind, SoundDesignTimeline, TimelineItem
    from foley.weave.timeline import hydrate, nudge

    tl = hydrate(SoundDesignTimeline(items=[TimelineItem(clip_ref="a", onset="on 'doors'")]), WT)
    assert tl.items[0].placement.match_kind is MatchKind.stem
    moved = nudge(tl, "a", 0.2).items[0].placement
    assert (moved.anchor, moved.match_kind) == (Anchor.absolute, MatchKind.absolute)


def test_placement_match_kind_serialises_back_compatibly():
    from foley.base import MatchKind

    old = Placement.from_dict({"anchor": "word", "ref": "door", "onset": 0.5})
    assert old.match_kind is None  # a placement saved before #263 still loads
    p = Placement(anchor=Anchor.word, ref="door", onset=0.5, match_kind=MatchKind.fuzzy)
    assert Placement.from_json(p.to_json()) == p
