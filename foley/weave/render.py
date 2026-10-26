"""The render — a PURE, deterministic projection of the timeline into audio (report 06 §6.4).

``render(timeline, library)`` is a pure function of ``(narration, timeline, library,
master)``: it aligns (once, cached), resolves each item's anchor, mixes each layer
bus (per-item DSP via the :class:`~foley.weave.protocols.ApplyStrategy` seam), ducks
the ambience/music beds under speech, sums the buses, and masters to the timeline's
:class:`~foley.base.MasterProfile`. Re-running after an edit reproduces exactly that
change and nothing else.

An opt-in :class:`RenderCache` memoises each layer's *pre-duck* bus by a content hash
of its items, so an incremental re-render recomputes only the changed layer(s) yet is
**byte-identical** to a full render (ducking and mastering are always recomputed
deterministically). The two shipped :class:`ApplyStrategy` impls are
:class:`FullRender` (default, full DSP) and :class:`PlaceOnly` (dry declicked
placement); ``diff-preview`` / ``transition`` are reserved behind the same seam.

This module also owns the timeline **export adapters**: a pure-stdlib CMX3600
:func:`to_edl` (always available) and a lazy :func:`to_otio` (``foley[weave]``);
:func:`export` prefers OTIO and falls back to EDL so export always succeeds.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..base import Layer, SoundDesignTimeline
from ..level import REFERENCE_PEAK_CEILING_DBFS, reference_gain_db
from .align import _default_aligner, aligner_name
from .master import MasterReport, master
from .mix import (
    LAYER_GAIN_DB,
    apply_distance,
    constant_power_pan,
    db_to_lin,
    declick,
    fit_duration,
    overlay,
    reverb_send,
    speech_duck_gain,
)
from .timeline import hydrate

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

    from ..base import TimelineItem
    from .protocols import Aligner, ApplyStrategy

#: The non-voice layers the render mixes, in sum order (voice is the 0 dB anchor).
RENDER_LAYERS: "tuple[Layer, ...]" = (
    Layer.sfx_fg,
    Layer.ambience,
    Layer.stinger,
    Layer.music,
)
#: Layers ducked under speech (report 06 §3.2).
DUCKED_LAYERS: "tuple[Layer, ...]" = (Layer.ambience, Layer.music)
#: Nominal clip length (seconds) used for EDL source-out when a clip's true length
#: is unknown at export time.
EDL_NOMINAL_CLIP_S: float = 1.0
EDL_FPS: int = 25  # EBU frame rate for CMX3600 timecodes


class RenderCache(dict):
    """Per-layer render memo (``bus_hash -> stereo bus array``) for incremental re-render."""


@dataclass
class RenderResult:
    """The output of :func:`render`: the mastered mix + the hydrated (re-renderable) timeline."""

    audio: "ndarray"  # mastered stereo (frames, 2) float32
    sr: int
    timeline: (
        SoundDesignTimeline  # hydrated, word_timeline cached (the reproducible seed)
    )
    master_report: MasterReport
    buses: dict = field(default_factory=dict)  # runtime-only {Layer: pre-duck bus}
    #: Where the word timings came from: ``"cached"`` (the timeline already had them),
    #: the aligner that produced them (``"fake"``, ``"whisperx"``, a class name), or
    #: ``None`` when nothing was aligned (no transcript).
    alignment: Optional[str] = None


# ---------------------------------------------------------------------------
# ApplyStrategy implementations (the per-item placement seam, report 10 §4.2)
# ---------------------------------------------------------------------------


class FullRender:
    """Default :class:`ApplyStrategy` — the full per-item DSP chain (report 06 §3-4).

    ``fit-duration`` (loop/trim) → ``level`` (measured loudness to the reference,
    :func:`foley.level.reference_gain_db`, on what will be heard) → distance → reverb send → constant-power pan →
    declick → gain (base layer level + item ``gain_db``) → overlay at the resolved
    onset. Levelling first means the layer gains act on clips of equal loudness, whatever
    level each was generated or recorded at (#111); ``level_clips=False`` renders the
    clips as stored.
    """

    def __init__(self, *, level_clips: bool = True):
        self.level_clips = level_clips

    @property
    def cache_key(self) -> str:
        """What distinguishes this strategy's output in :class:`RenderCache` keys."""
        return f"{type(self).__name__}(level_clips={self.level_clips})"

    def apply(
        self, item: "TimelineItem", bus: "ndarray", clip: "ndarray", *, sample_rate: int
    ) -> "ndarray":
        p = item.processing
        pl = item.placement
        clip = fit_duration(clip, sample_rate, duration=pl.duration, loop=pl.loop)
        layer_gain_db = LAYER_GAIN_DB.get(item.layer, 0.0)
        if (
            self.level_clips
        ):  # on what will be heard (looped/trimmed), peak after layer gain
            ceiling = REFERENCE_PEAK_CEILING_DBFS - layer_gain_db
            gain = reference_gain_db(clip, sample_rate, peak_ceiling_dbfs=ceiling)
            clip = clip * db_to_lin(gain)
        clip = apply_distance(clip, sample_rate, p.distance)
        clip = reverb_send(clip, sample_rate, p.reverb_send)
        stereo = constant_power_pan(clip, p.pan)
        stereo = declick(stereo, sample_rate, fade_in=p.fade_in, fade_out=p.fade_out)
        gain = db_to_lin(layer_gain_db + p.gain_db)
        stereo = stereo * gain
        return overlay(bus, stereo, int(pl.onset * sample_rate))


class PlaceOnly:
    """Dry :class:`ApplyStrategy` — declicked placement, no gain/pan/distance/reverb.

    The fast preview / DSP-free fallback path: fit-duration → declick → overlay at the
    resolved onset, at unity gain.
    """

    def apply(
        self, item: "TimelineItem", bus: "ndarray", clip: "ndarray", *, sample_rate: int
    ) -> "ndarray":
        pl = item.placement
        clip = fit_duration(clip, sample_rate, duration=pl.duration, loop=pl.loop)
        clip = declick(clip, sample_rate)
        return overlay(bus, clip, int(pl.onset * sample_rate))


# ---------------------------------------------------------------------------
# render()
# ---------------------------------------------------------------------------


def load_clip_mono(library, ref: str, *, sr: int) -> "ndarray":
    """Load ``ref`` from ``library`` as a mono working array at ``sr``.

    Accepts a :class:`foley.index.SoundLibrary` (via ``.array``) or a plain mapping
    yielding an ndarray, raw bytes, or a ``(samples, orig_sr)`` tuple — so the render
    is testable with a trivial dict library. Shared by :func:`render` and the WEAVE
    façade's narration-binding view, so it carries no underscore.
    """
    from ..audio import WORKING_SAMPLE_RATE, load, to_working

    if hasattr(library, "array"):
        return library.array(ref, sr=sr, mono=True)
    item = library[ref]
    target = WORKING_SAMPLE_RATE if sr is None else sr
    if isinstance(item, tuple) and len(item) == 2:
        samples, orig = item
        return to_working(samples, orig, mono=True, target_sr=target)
    if isinstance(item, (bytes, bytearray)):
        samples, orig = load(bytes(item))
        return to_working(samples, orig, mono=True, target_sr=target)
    return to_working(item, target, mono=True, target_sr=target)  # assume array at sr


def _silence(n: int) -> "ndarray":
    """A stereo ``(n, 2)`` float32 silence bus."""
    import numpy as np

    return np.zeros((n, 2), dtype="float32")


def _speech_spans(word_timeline: "list[dict]") -> "list[tuple[float, float]]":
    """Speech spans ``[(start, end), ...]`` for ducking, from the word timeline."""
    return [
        (float(w.get("start", 0.0)), float(w.get("end", w.get("start", 0.0))))
        for w in word_timeline
    ]


def _bus_hash(items: "list[TimelineItem]", n: int, sr: int, strategy) -> str:
    """A stable content hash of a layer's items (for :class:`RenderCache`).

    Covers everything that affects the *pre-duck* bus: the strategy, sample rate,
    bus length, and each item's clip + resolved placement + processing.
    """
    parts = [getattr(strategy, "cache_key", type(strategy).__name__), str(sr), str(n)]
    for it in items:
        pl, p = it.placement, it.processing
        parts.append(
            "|".join(
                str(x)
                for x in (
                    it.clip_ref,
                    it.layer,
                    pl.onset,
                    pl.duration,
                    pl.loop,
                    p.gain_db,
                    p.pan,
                    p.distance,
                    p.reverb_send,
                    p.fade_in,
                    p.fade_out,
                )
            )
        )
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def render(
    timeline: SoundDesignTimeline,
    library,
    *,
    sr: int = 48_000,
    transcript: Optional[str] = None,
    aligner: "Optional[Aligner]" = None,
    apply_strategy: "Optional[ApplyStrategy]" = None,
    cache: Optional[RenderCache] = None,
) -> RenderResult:
    """Render ``timeline`` against ``library`` into a mastered mix (PURE, deterministic).

    Args:
        timeline: The sound-design timeline (sparse or hydrated). ``narration_ref``
            must resolve in ``library``; ``master`` carries the loudness target.
        library: A :class:`foley.index.SoundLibrary` (or a mapping of ref → audio).
        sr: Working/render sample rate in Hz.
        transcript: Narration transcript for alignment when ``timeline.word_timeline``
            is empty (else alignment is skipped — the cached timeline is the seed).
        aligner: The :class:`~foley.weave.protocols.Aligner` (default: WhisperX if
            ``foley[align]`` installed, else the deterministic fake).
        apply_strategy: The per-item :class:`~foley.weave.protocols.ApplyStrategy`
            (default :class:`FullRender`).
        cache: An optional :class:`RenderCache` for byte-identical incremental
            re-render (only changed layers recompute).

    Returns:
        A :class:`RenderResult` — the mastered stereo mix, the hydrated timeline (with
        ``word_timeline`` cached), and the :class:`~foley.weave.master.MasterReport`.
    """
    strategy = apply_strategy or FullRender()
    voice_mono = load_clip_mono(library, timeline.narration_ref, sr=sr)
    n = int(voice_mono.shape[0])

    wt = list(timeline.word_timeline)
    alignment = "cached" if wt else None
    if not wt and transcript:
        used = aligner if aligner is not None else _default_aligner()
        wt = used.word_timeline(voice_mono, sr, transcript=transcript)
        alignment = aligner_name(used)
    tl = hydrate(timeline, wt)

    # group enabled non-voice items by layer, then render (or reuse) each bus
    by_layer: "dict[Layer, list[TimelineItem]]" = {layer: [] for layer in RENDER_LAYERS}
    for it in tl.items:
        if it.enabled and it.layer in by_layer:
            by_layer[it.layer].append(it)

    buses: "dict[Layer, ndarray]" = {}
    for layer in RENDER_LAYERS:
        items = by_layer[layer]
        key = _bus_hash(items, n, sr, strategy)
        if cache is not None and key in cache:
            buses[layer] = cache[key]
            continue
        bus = _silence(n)
        for it in items:
            clip = load_clip_mono(library, it.clip_ref, sr=sr)
            bus = strategy.apply(it, bus, clip, sample_rate=sr)
        if cache is not None:
            cache[key] = bus
        buses[layer] = bus

    # duck the beds under speech (post-cache, so always recomputed → byte-identical)
    from ..audio import ensure_channels

    mix = ensure_channels(voice_mono, channels=2).astype("float32", copy=True)
    duck_env = None
    for layer in RENDER_LAYERS:
        bus = buses[layer]
        if layer in DUCKED_LAYERS:
            if duck_env is None:
                duck_env = speech_duck_gain(n, sr, _speech_spans(wt))
            bus = bus * duck_env[:, None]
        mix = mix + bus

    mastered, report = master(mix, sr, tl.master)
    return RenderResult(
        audio=mastered.astype("float32", copy=False),
        sr=sr,
        timeline=tl,
        master_report=report,
        buses=buses,
        alignment=alignment,
    )


# ---------------------------------------------------------------------------
# Export adapters — CMX3600 EDL (pure) + OTIO (lazy foley[weave])
# ---------------------------------------------------------------------------


def _tc(seconds: float, *, fps: int = EDL_FPS) -> str:
    """Format ``seconds`` as an ``HH:MM:SS:FF`` CMX3600 timecode."""
    seconds = max(0.0, seconds)
    total_frames = int(round(seconds * fps))
    frames = total_frames % fps
    s = total_frames // fps
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}:{frames:02d}"


def to_edl(timeline: SoundDesignTimeline, *, title: str = "foley SFX") -> str:
    """Export ``timeline`` as a pure-stdlib CMX3600 EDL (deterministic, pinned ids).

    A lightweight interchange for DAWs; each enabled, placed item is one event with
    its clip name as the source comment. Always available (no dependency).
    """
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    event = 0
    placed = [it for it in timeline.items if it.enabled and it.placement is not None]
    placed.sort(key=lambda it: float(it.placement.onset))
    for it in placed:
        event += 1
        onset = float(it.placement.onset)
        dur = float(it.placement.duration or EDL_NOMINAL_CLIP_S)
        rec_in, rec_out = _tc(onset), _tc(onset + dur)
        src_out = _tc(dur)
        lines.append(
            f"{event:03d}  AX       AA     C        "
            f"{_tc(0.0)} {src_out} {rec_in} {rec_out}"
        )
        lines.append(f"* FROM CLIP NAME: {it.clip_ref}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _opentimelineio_available() -> bool:
    """True iff ``opentimelineio`` (the ``foley[weave]`` extra) is importable."""
    import importlib.util

    return importlib.util.find_spec("opentimelineio") is not None


def to_otio(timeline: SoundDesignTimeline, *, rate: int = EDL_FPS) -> str:
    """Export ``timeline`` as an OpenTimelineIO JSON string (lazy ``foley[weave]``).

    One or more **parallel** tracks per non-voice layer: each enabled, placed item is a
    clip with an external media reference (by clip_ref), positioned at its resolved onset
    via a leading gap. Because a single OTIO track is sequential, two same-layer clips that
    overlap (or fall within a one-shot's nominal window) would otherwise be pushed late —
    so overlapping clips spill onto sibling sub-tracks, keeping every clip at its true
    onset. Non-destructive, minimal-viable fidelity (tracks/clips/onsets; effects/markers
    are a later slice).

    Raises:
        RuntimeError: If ``opentimelineio`` is not installed.
    """
    if not _opentimelineio_available():
        raise RuntimeError(
            "OTIO export needs the 'foley[weave]' extra (opentimelineio); "
            "use to_edl() for the dependency-free CMX3600 export."
        )
    import opentimelineio as otio  # lazy: foley[weave]

    def _gap(seconds: float):
        return otio.schema.Gap(
            source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(0, rate),
                otio.opentime.RationalTime(round(seconds * rate), rate),
            )
        )

    def _clip(it, dur: float):
        return otio.schema.Clip(
            name=it.clip_ref,
            media_reference=otio.schema.ExternalReference(target_url=it.clip_ref),
            source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(0, rate),
                otio.opentime.RationalTime(round(dur * rate), rate),
            ),
        )

    tl = otio.schema.Timeline(name="foley SFX")
    by_layer: "dict[Layer, list[TimelineItem]]" = {layer: [] for layer in RENDER_LAYERS}
    for it in timeline.items:
        if it.enabled and it.placement is not None and it.layer in by_layer:
            by_layer[it.layer].append(it)
    for layer in RENDER_LAYERS:
        items = sorted(by_layer[layer], key=lambda it: float(it.placement.onset))
        if not items:
            continue
        # Greedily pack clips into parallel sub-tracks so no two overlap on one track
        # (a single OTIO Track is sequential — an overlapping clip would be pushed late).
        # Each clip lands at its TRUE onset via a leading gap; a clip that would overlap
        # every existing sub-track spills onto a new one.
        subtracks: "list[list]" = []  # each entry: [track, playhead_seconds]
        for it in items:
            onset = float(it.placement.onset)
            dur = float(it.placement.duration or EDL_NOMINAL_CLIP_S)
            slot = next((s for s in subtracks if onset >= s[1] - 1e-9), None)
            if slot is None:
                name = (
                    layer.value
                    if not subtracks
                    else f"{layer.value} ({len(subtracks) + 1})"
                )
                slot = [
                    otio.schema.Track(name=name, kind=otio.schema.TrackKind.Audio),
                    0.0,
                ]
                subtracks.append(slot)
            track, playhead = slot
            if onset > playhead:
                track.append(_gap(onset - playhead))
            track.append(_clip(it, dur))
            slot[1] = onset + dur
        for track, _ in subtracks:
            tl.tracks.append(track)
    return otio.adapters.write_to_string(tl, "otio_json")


def export(timeline: SoundDesignTimeline, *, fmt: str = "auto") -> "tuple[str, str]":
    """Export ``timeline`` as ``(format, text)`` — OTIO when available, else EDL.

    Args:
        timeline: The timeline to export.
        fmt: ``'auto'`` (OTIO if installed, else EDL), ``'otio'``, or ``'edl'``.

    Returns:
        ``(format_name, serialized_text)`` — export always succeeds (EDL is the
        dependency-free fallback).
    """
    if fmt == "edl":
        return "edl", to_edl(timeline)
    if fmt == "otio" or (fmt == "auto" and _opentimelineio_available()):
        try:
            return "otio", to_otio(timeline)
        except RuntimeError:
            if fmt == "otio":
                raise
    return "edl", to_edl(timeline)
