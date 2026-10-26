"""WEAVE data-model growth in base.py — additive, back-compatible, round-trippable."""

import pytest

from foley.base import (
    MASTER_PROFILES,
    Anchor,
    Layer,
    MasterProfile,
    Placement,
    Processing,
    SoundDesignTimeline,
    TimelineItem,
    resolve_master,
)


def test_resolve_master_dispatch():
    assert resolve_master("podcast").target_lufs == -16.0
    assert resolve_master("streaming").target_lufs == -14.0
    assert resolve_master("broadcast_ebu").target_lufs == -23.0
    assert resolve_master("broadcast_atsc").true_peak_db == -2.0
    assert resolve_master(None).target_lufs == -16.0
    mp = MasterProfile(target_lufs=-9.0)
    assert resolve_master(mp) is mp
    with pytest.raises(ValueError):
        resolve_master("nope")


def test_old_sparse_json_rehydrates_at_defaults():
    """A pre-#8 sparse timeline JSON rehydrates with every WEAVE field at its default."""
    old = {
        "items": [
            {"clip_ref": "door", "onset": "on 'door'", "gain": -6.0, "layer": "sfx_fg", "loop": False}
        ],
        "run_manifest_ref": "r1",
        "transcript_ref": "narration",
        "schema_version": 1,
    }
    tl = SoundDesignTimeline.from_dict(old)
    it = tl.items[0]
    assert it.placement is None and it.processing is None
    assert it.id is None and it.event is None and it.enabled is True
    assert tl.word_timeline == [] and tl.narration_ref is None
    assert isinstance(tl.master, MasterProfile) and tl.master.target_lufs == -16.0


def test_grown_round_trip_and_nested_coercion():
    tl = SoundDesignTimeline(
        items=[
            TimelineItem(
                clip_ref="x",
                id="c1",
                placement=Placement(anchor=Anchor.word, ref="door", onset=1.5, pre_roll=0.2),
                processing=Processing(gain_db=-6.0, pan=-0.3, reverb_send=0.4),
            )
        ],
        word_timeline=[{"word": "door", "start": 1.5, "end": 1.7}],
        master=MASTER_PROFILES["streaming"],
        narration_ref="nar",
    )
    rt = SoundDesignTimeline.from_dict(tl.to_dict())
    assert rt == tl
    assert isinstance(rt.items[0].placement, Placement)
    assert rt.items[0].placement.anchor is Anchor.word
    assert isinstance(rt.items[0].processing, Processing)
    assert isinstance(rt.master, MasterProfile) and rt.master.target_lufs == -14.0


def test_processing_identity_defaults_are_noop():
    p = Processing()
    assert (p.gain_db, p.pan, p.distance, p.reverb_send) == (0.0, 0.0, 0.0, 0.0)
    assert p.duck_bed is False


def test_master_profiles_values():
    assert MASTER_PROFILES["podcast"].target_lufs == -16.0
    assert MASTER_PROFILES["broadcast_atsc"].true_peak_db == -2.0
    assert set(MASTER_PROFILES) == {"podcast", "streaming", "broadcast_ebu", "broadcast_atsc"}


def test_timeline_item_keeps_sparse_fields():
    """The five sparse flat fields are unchanged (plan()/place_in_timeline keep working)."""
    it = TimelineItem(clip_ref="a", onset="on 'x'", gain=-3.0, layer=Layer.ambience, loop=True)
    assert it.onset == "on 'x'" and it.gain == -3.0 and it.loop is True
    assert it.placement is None and it.processing is None  # unresolved by default
