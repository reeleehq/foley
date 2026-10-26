"""WEAVE render — purity/determinism, incremental cache, strategies, exports."""

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyloudnorm")

from foley.audio import WORKING_SAMPLE_RATE, to_working  # noqa: E402
from foley.base import Layer, SoundDesignTimeline, TimelineItem  # noqa: E402
from foley.weave.align import FakeAligner  # noqa: E402
from foley.weave.render import (  # noqa: E402
    FullRender,
    PlaceOnly,
    RenderCache,
    RenderResult,
    export,
    render,
    to_edl,
)

SR = 48000
TRANSCRIPT = "the door opened wide"


class _Lib:
    def __init__(self):
        rng = np.random.default_rng(1)
        voice = (0.1 * rng.standard_normal(2 * SR)).astype("float32")
        door = (0.5 * np.sin(2 * np.pi * 300 * np.arange(int(0.2 * SR)) / SR)).astype("float32")
        rain = (0.15 * rng.standard_normal(SR)).astype("float32")
        self.arrays = {"nar": (voice, SR), "door": (door, SR), "rain": (rain, SR)}

    def array(self, ref, *, sr=None, mono=True):
        s, o = self.arrays[ref]
        return to_working(s, o, mono=mono, target_sr=WORKING_SAMPLE_RATE if sr is None else sr)


def _tl():
    return SoundDesignTimeline(
        narration_ref="nar",
        items=[
            TimelineItem(clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg),
            TimelineItem(clip_ref="rain", onset=None, gain=-18.0, layer=Layer.ambience, loop=True),
        ],
    )


def _render(**kw):
    return render(_tl(), _Lib(), sr=SR, transcript=TRANSCRIPT, aligner=FakeAligner(), **kw)


def test_render_is_deterministic_and_pure():
    r1, r2 = _render(), _render()
    assert isinstance(r1, RenderResult)
    assert r1.audio.shape == (2 * SR, 2) and r1.audio.dtype == np.float32
    assert np.array_equal(r1.audio, r2.audio)
    # word_timeline cached on the returned (hydrated) timeline = the reproducible seed
    assert len(r1.timeline.word_timeline) == len(TRANSCRIPT.split())


def test_incremental_cache_is_byte_identical():
    full = _render()
    cache = RenderCache()
    warm = _render(cache=cache)  # cold cache: computes + stores
    assert np.array_equal(warm.audio, full.audio)
    assert len(cache) >= 1
    again = _render(cache=cache)  # warm cache: reuses buses
    assert np.array_equal(again.audio, full.audio)


def test_cache_invalidates_when_an_item_changes():
    """A warm cache must NOT serve a stale bus after an item edit (proves _bus_hash coverage)."""
    lib = _Lib()
    cache = RenderCache()
    r1 = render(_tl(), lib, sr=SR, transcript=TRANSCRIPT, aligner=FakeAligner(), cache=cache)
    tl2 = _tl()
    tl2.items[0] = replace(tl2.items[0], gain=-30.0)  # change the door's level
    r2 = render(tl2, lib, sr=SR, transcript=TRANSCRIPT, aligner=FakeAligner(), cache=cache)
    # the edited render differs from the cached original (cache correctly invalidated) ...
    assert not np.array_equal(r1.audio, r2.audio)
    # ... and matches a fresh full render of the edited timeline (correct, not stale)
    r2_full = render(tl2, lib, sr=SR, transcript=TRANSCRIPT, aligner=FakeAligner())
    assert np.array_equal(r2.audio, r2_full.audio)


def test_place_only_differs_from_full_render():
    full = _render(apply_strategy=FullRender())
    place = _render(apply_strategy=PlaceOnly())
    assert not np.array_equal(full.audio, place.audio)


def test_default_strategy_is_full_render():
    assert np.array_equal(_render().audio, _render(apply_strategy=FullRender()).audio)


def test_render_without_transcript_uses_absolute_anchors():
    # no transcript -> no alignment -> word anchors fall back, render still succeeds
    r = render(_tl(), _Lib(), sr=SR, aligner=FakeAligner())
    assert r.audio.shape == (2 * SR, 2)
    assert r.timeline.word_timeline == []


def test_edl_export_is_pinned_and_pure():
    tl = _render().timeline
    edl = to_edl(tl)
    assert edl.startswith("TITLE: foley SFX")
    assert "* FROM CLIP NAME: door" in edl and "* FROM CLIP NAME: rain" in edl
    fmt, text = export(tl, fmt="edl")
    assert fmt == "edl" and "door" in text


def test_otio_export_optional():
    tl = _render().timeline
    pytest.importorskip("opentimelineio")
    from foley.weave.render import to_otio

    s = to_otio(tl)
    assert "door" in s and "rain" in s
