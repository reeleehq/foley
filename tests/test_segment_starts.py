"""``score(segment_starts=)`` and :class:`foley.weave.SegmentedAligner` (#256 item 3)."""

import os
import sys

import pytest

np = pytest.importorskip("numpy")

import foley  # noqa: E402
from foley.weave import FakeAligner, SegmentedAligner  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SR = 1_000

# A test timeline: a short line, a long pause, then a second line late in the file.
SEGMENTS = ["The door slammed.", "Thunder rolled far away."]
STARTS = [0.0, 8.0]
DURATION = 10.0
TRUE_ONSETS = {"The": 0.0, "door": 0.5, "slammed.": 1.0, "Thunder": 8.0, "rolled": 8.5}


def _audio(seconds=DURATION):
    return np.zeros(int(seconds * SR), dtype="float32")


def _onset_errors(word_timeline):
    by_word = {w["word"]: w["start"] for w in word_timeline}
    return {w: abs(by_word[w] - t) for w, t in TRUE_ONSETS.items()}


def test_fake_places_each_segments_words_within_its_span():
    wt = SegmentedAligner(STARTS, SEGMENTS, base=FakeAligner()).word_timeline(
        _audio(), SR, transcript=" ".join(SEGMENTS)
    )
    assert [w["word"] for w in wt] == " ".join(SEGMENTS).split()  # transcript order
    first, second = wt[:3], wt[3:]
    assert all(0.0 <= w["start"] < w["end"] <= 8.0 for w in first)
    assert all(
        8.0 <= w["start"] < w["end"] <= DURATION for w in second
    )  # last → audio end
    assert second[0]["start"] == 8.0


def test_segmented_placement_beats_the_whole_file_spread():
    transcript = " ".join(SEGMENTS)
    whole = FakeAligner().word_timeline(_audio(), SR, transcript=transcript)
    split = SegmentedAligner(STARTS, SEGMENTS, base=FakeAligner()).word_timeline(
        _audio(), SR, transcript=transcript
    )
    split_err, whole_err = _onset_errors(split), _onset_errors(whole)
    assert sum(split_err.values()) < sum(whole_err.values())
    assert (
        split_err["Thunder"] == 0.0 < 3.0 < whole_err["Thunder"]
    )  # the late cue lands


class _SliceRecorder:
    """A real-aligner-like fake: aligns what it is given, in slice-relative seconds."""

    name = "recorder"

    def __init__(self):
        self.calls = []

    def word_timeline(self, audio, sample_rate, *, transcript=None, language="en"):
        self.calls.append((audio.shape[0], transcript, language))
        return [
            {"word": w, "start": 0.1 * i, "end": 0.1 * i + 0.05, "score": 0.9}
            for i, w in enumerate(transcript.split())
        ]


def test_a_real_aligner_gets_slices_and_its_timings_are_offset():
    rec = _SliceRecorder()
    seg = SegmentedAligner([0.5, 3.0], ["one two", "three"], base=rec)
    wt = seg.word_timeline(_audio(5.0), SR, transcript="one two three", language="fr")
    assert rec.calls == [(2_500, "one two", "fr"), (2_000, "three", "fr")]
    assert [(w["word"], w["start"], w["end"]) for w in wt] == [
        ("one", 0.5, 0.55),
        ("two", 0.6, 0.65),
        ("three", 3.0, 3.05),
    ]
    assert wt[0]["score"] == 0.9  # the aligner's extra fields survive
    assert seg.name == "recorder"  # weave's alignment notes see the real aligner


def test_language_is_left_to_the_base_aligner_when_unset():
    rec = _SliceRecorder()
    SegmentedAligner([0.0], ["hi"], base=rec).word_timeline(
        _audio(1.0), SR, transcript="hi"
    )
    assert rec.calls[0][2] == "en"  # the base's own default


def test_an_empty_segment_is_skipped_and_may_share_a_start():
    rec = _SliceRecorder()
    wt = SegmentedAligner([0.0, 2.0, 2.0], ["a b", "", "c"], base=rec).word_timeline(
        _audio(4.0), SR, transcript="a b c"
    )
    assert [c[1] for c in rec.calls] == ["a b", "c"]
    assert wt[-1]["start"] == 2.0


@pytest.mark.parametrize(
    "starts, match",
    [
        ([0.0], "1 value.*2 segment"),
        ([0.0, 1.0, 2.0], "3 value.*2 segment"),
        ([2.0, 1.0], "non-decreasing"),
        ([-1.0, 1.0], ">= 0"),
        ([0.0, float("nan")], "finite"),
    ],
)
def test_bad_starts_are_refused_at_construction(starts, match):
    with pytest.raises(ValueError, match=match):
        SegmentedAligner(starts, SEGMENTS)


def test_starts_must_fit_the_audio():
    seg = SegmentedAligner([0.0, 12.0], SEGMENTS, base=FakeAligner())
    with pytest.raises(ValueError, match="past the end"):
        seg.word_timeline(_audio(), SR, transcript=" ".join(SEGMENTS))
    tie = SegmentedAligner([0.0, 0.0], SEGMENTS, base=FakeAligner())
    with pytest.raises(ValueError, match="segment 0 has 3 word.*no audio"):
        tie.word_timeline(_audio(), SR, transcript=" ".join(SEGMENTS))


def test_a_transcript_that_does_not_split_is_refused():
    with pytest.raises(ValueError, match="5 word.*segments have 7"):
        SegmentedAligner(STARTS, SEGMENTS).split("one two three four five")


# --- through foley.score ------------------------------------------------------


@pytest.fixture
def _obs_to_memory():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


def _find_spy(monkeypatch):
    calls = []

    def spy(context, **kw):
        calls.append(kw)
        return []

    monkeypatch.setattr(foley, "find", spy)
    return calls


def test_score_refuses_bad_segment_starts_before_any_find(monkeypatch, _obs_to_memory):
    calls = _find_spy(monkeypatch)
    with pytest.raises(ValueError, match="1 value"):
        foley.score(SEGMENTS, audio="nar", segment_starts=[0.0])
    with pytest.raises(ValueError, match="transcript has 2 word"):
        foley.score(
            SEGMENTS, audio="nar", segment_starts=STARTS, transcript="two words"
        )
    assert calls == []


def test_score_weaves_with_segment_starts_wrapping_the_given_aligner(_obs_to_memory):
    from test_mcp import FakeLibrary  # 2 s of narration under "nar"

    rec = _SliceRecorder()
    res = foley.score(
        ["A door creak.", "Distant thunder."],
        audio="nar",
        library=FakeLibrary(),
        segment_starts=[0.0, 1.5],
        aligner=rec,
        allow_generate=False,
    )
    assert [c[1] for c in rec.calls] == ["A door creak.", "Distant thunder."]
    wt = res.weave.timeline.word_timeline
    assert [w["start"] for w in wt if w["word"] == "Distant"] == [1.5]
