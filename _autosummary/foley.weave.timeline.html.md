# foley.weave.timeline

The sound-design timeline as an editable document — hydrate, edit, caption.

The timeline is the SSOT and the reproducible seed; [`foley.weave.render()`](foley.weave.html.md#foley.weave.render) is a
pure projection of it. This module owns the *document* operations, all pure and
stdlib-only (no numpy, no I/O):

* [`hydrate()`](#foley.weave.timeline.hydrate) — resolve each item’s symbolic anchor into a concrete
  [`Placement`](foley.base.html.md#foley.base.Placement) and fill processing/id defaults, **idempotently**
  > (`hydrate ∘ hydrate == hydrate`) and without clobbering a hand-set placement.
* Pure edit transforms ([`swap_clip()`](#foley.weave.timeline.swap_clip), [`nudge()`](#foley.weave.timeline.nudge), [`set_gain()`](#foley.weave.timeline.set_gain),
  [`toggle()`](#foley.weave.timeline.toggle), [`set_master()`](#foley.weave.timeline.set_master)) — each returns a NEW timeline, so an edit +
  > re-render reproduces exactly that change (the “editable, re-renderable” DoD).
* Accessibility **SDH captions** ([`to_webvtt()`](#foley.weave.timeline.to_webvtt) / [`to_srt()`](#foley.weave.timeline.to_srt)) — bracketed
  SFX labels (`[door creak]`) derived from the *items*, never from the narration
  transcript, so no speech text leaks into a shipped caption file.

### Module Attributes

| [`DISPLAY_WINDOW_S`](#foley.weave.timeline.DISPLAY_WINDOW_S)   | How long a one-shot's caption stays on screen (seconds) when the item has no resolved duration of its own.   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|

### Functions

| [`hydrate`](#foley.weave.timeline.hydrate)(timeline[, word_timeline])         | Resolve every item's anchor + fill processing/id, returning a NEW timeline.         |
|---------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`nudge`](#foley.weave.timeline.nudge)(timeline, item_id, delta_s)          | Shift an item's resolved onset by `delta_s` seconds — a NEW timeline.               |
| [`set_gain`](#foley.weave.timeline.set_gain)(timeline, item_id, gain_db)       | Set an item's processing gain (dB, voice-relative) — a NEW timeline.                |
| [`set_master`](#foley.weave.timeline.set_master)(timeline, master)               | Set the timeline's master profile (name or `MasterProfile`) — a NEW timeline.       |
| [`swap_clip`](#foley.weave.timeline.swap_clip)(timeline, item_id, new_clip_ref) | Swap an item's clip (keeping its placement/processing) — a NEW timeline.            |
| [`to_srt`](#foley.weave.timeline.to_srt)(timeline, \*[, window_s])           | Render the timeline's SFX cues as an SRT SDH caption file (report 06 / issue #8).   |
| [`to_webvtt`](#foley.weave.timeline.to_webvtt)(timeline, \*[, window_s])        | Render the timeline's SFX cues as a WebVTT SDH caption file (report 06 / issue #8). |
| [`toggle`](#foley.weave.timeline.toggle)(timeline, item_id, enabled)         | Non-destructively mute/unmute an item — a NEW timeline.                             |

### foley.weave.timeline.DISPLAY_WINDOW_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 2.0*

How long a one-shot’s caption stays on screen (seconds) when the item has no
resolved duration of its own.

### foley.weave.timeline.hydrate(timeline, word_timeline=None)

Resolve every item’s anchor + fill processing/id, returning a NEW timeline.

Idempotent: an item that already carries a [`Placement`](foley.base.html.md#foley.base.Placement) keeps
its symbolic anchor (a hand edit is never clobbered) but is re-resolved against
`word_timeline` so a re-recorded/re-aligned narration re-flows the SFX
(report 06 §6.1). `processing` falls back to the sparse `gain` and `id` to a
stable content hash. The resolved `word_timeline` is cached on the returned
timeline (the reproducible seed).

* **Parameters:**
  * **timeline** ([`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)) – The (sparse or partially-resolved) timeline.
  * **word_timeline** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)]) – The forced alignment; defaults to `timeline.word_timeline`.
* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)
* **Returns:**
  A hydrated copy with resolved placements, filled processing, stable ids.

### foley.weave.timeline.nudge(timeline, item_id, delta_s)

Shift an item’s resolved onset by `delta_s` seconds — a NEW timeline.

Resolves the item’s anchor against the timeline’s `word_timeline` first, then shifts
the resolved onset and pins the anchor to `absolute` so the manual offset survives a
re-hydrate. This means nudging a still-symbolic (not-yet-hydrated) item on a timeline
that carries alignment shifts from the item’s *true* resolved onset, not from 0. On a
pre-alignment timeline with no `word_timeline` a word/sentence anchor is genuinely
unresolvable, so there the shift is relative to 0 — hydrate/weave first for such items.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.timeline.set_gain(timeline, item_id, gain_db)

Set an item’s processing gain (dB, voice-relative) — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.timeline.set_master(timeline, master)

Set the timeline’s master profile (name or `MasterProfile`) — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.timeline.swap_clip(timeline, item_id, new_clip_ref)

Swap an item’s clip (keeping its placement/processing) — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.timeline.to_srt(timeline, , window_s=2.0)

Render the timeline’s SFX cues as an SRT SDH caption file (report 06 / issue #8).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.weave.timeline.to_webvtt(timeline, , window_s=2.0)

Render the timeline’s SFX cues as a WebVTT SDH caption file (report 06 / issue #8).

Each enabled, placed item becomes one `[bracketed]` cue at its resolved onset.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.weave.timeline.toggle(timeline, item_id, enabled)

Non-destructively mute/unmute an item — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)
