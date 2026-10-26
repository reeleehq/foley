"""WEAVE timeline document ops — hydrate, edit transforms, SDH captions (pure, stdlib)."""

from dataclasses import replace

from foley.base import Anchor, Layer, Placement, SoundDesignTimeline, TimelineItem
from foley.weave.timeline import (
    hydrate,
    nudge,
    set_gain,
    set_master,
    swap_clip,
    to_srt,
    to_webvtt,
    toggle,
)

WT = [
    {"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
    for i, w in enumerate(["the", "door", "opened", "then", "rain", "fell"])
]


def _tl():
    return SoundDesignTimeline(
        items=[
            TimelineItem(
                clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg,
                event={"query": "door creak"},
            ),
            TimelineItem(
                clip_ref="rain", onset=None, gain=-18.0, layer=Layer.ambience, loop=True,
                event={"query": "rain"},
            ),
        ],
        word_timeline=WT,
    )


def test_hydrate_resolves_and_is_idempotent():
    h = hydrate(_tl(), WT)
    door = next(i for i in h.items if i.clip_ref == "door")
    assert door.placement is not None and door.placement.anchor is Anchor.word
    assert door.placement.onset == 0.5  # "door" at 0.5s
    assert door.processing.gain_db == -6.0  # from the sparse gain
    assert door.id is not None
    assert hydrate(h, WT) == h  # hydrate ∘ hydrate == hydrate


def test_hydrate_does_not_clobber_preset_placement():
    tl = _tl()
    tl.items[0] = replace(tl.items[0], placement=Placement(anchor=Anchor.absolute, onset=5.0))
    h = hydrate(tl, WT)
    door = next(i for i in h.items if i.clip_ref == "door")
    assert door.placement.anchor is Anchor.absolute and door.placement.onset == 5.0


def test_cue_ids_are_stable_across_hydrations():
    ids1 = [i.id for i in hydrate(_tl(), WT).items]
    ids2 = [i.id for i in hydrate(_tl(), WT).items]
    assert ids1 == ids2 and all(ids1)


def test_edit_transforms_are_pure_new_timelines():
    h = hydrate(_tl(), WT)
    door_id = next(i.id for i in h.items if i.clip_ref == "door")
    swapped = swap_clip(h, door_id, "creak2")
    assert swapped is not h
    assert next(i for i in swapped.items if i.id == door_id).clip_ref == "creak2"
    assert next(i for i in h.items if i.id == door_id).clip_ref == "door"  # original intact

    nudged = nudge(h, door_id, 0.25)
    assert next(i for i in nudged.items if i.id == door_id).placement.onset == 0.75

    gained = set_gain(h, door_id, -3.0)
    assert next(i for i in gained.items if i.id == door_id).processing.gain_db == -3.0

    muted = toggle(h, door_id, False)
    assert next(i for i in muted.items if i.id == door_id).enabled is False

    assert set_master(h, "streaming").master.target_lufs == -14.0


def test_nudge_survives_rehydrate():
    h = hydrate(_tl(), WT)
    door_id = next(i.id for i in h.items if i.clip_ref == "door")
    nudged = nudge(h, door_id, 0.25)
    rehydrated = hydrate(nudged, WT)
    assert next(i for i in rehydrated.items if i.id == door_id).placement.onset == 0.75


def test_sdh_captions_format_and_no_narration_leak():
    h = hydrate(_tl(), WT)
    vtt = to_webvtt(h)
    srt = to_srt(h)
    assert vtt.startswith("WEBVTT")
    assert "[door creak]" in vtt and "[rain]" in vtt
    assert srt.startswith("1\n") and "-->" in srt
    # narration-only words never appear in a shipped caption file (no speech leak)
    for w in ("opened", "then", "fell"):
        assert w not in vtt and w not in srt


def test_disabled_items_are_not_captioned():
    h = hydrate(_tl(), WT)
    door_id = next(i.id for i in h.items if i.clip_ref == "door")
    vtt = to_webvtt(toggle(h, door_id, False))
    assert "[door creak]" not in vtt and "[rain]" in vtt
