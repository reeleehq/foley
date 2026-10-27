# foley.weave

WEAVE — the compositor façade: narration + timeline → a finished, editable mix.

`weave()` is the headline WEAVE entrypoint (report 06 §7, issue #8): it resolves the
master profile, binds the narration, opens a `foley.obs.run('weave')` scope, and
drives the PURE `render()` pipeline
(**align → anchor → mix → master → render**), then wraps the result with credits, SDH
captions, and a **fail-safe provenance re-assertion** over the mastered mix. It returns
a [`WeaveResult`](#foley.weave.WeaveResult): the mastered audio, the hydrated re-renderable
[`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline) (the reproducible seed), a
[`Credits`](foley.provenance.html.md#foley.provenance.Credits), WebVTT + SRT SDH captions, the master report, and
the run-artifact join.

Discipline (mirrors the rest of foley): the whole package is import-time dol-only
(numpy / mixing.loudness / whisperx / opentimelineio / audioseal / c2pa are all
function-local), the aligner and per-item strategy are injectable DI seams with
deterministic defaults, and provenance re-assertion never raises — the C2PA
content-credential sidecar is always emitted; the AudioSeal watermark and the (deferred)
signed + embedded C2PA manifest are best-effort no-ops when their extras/cert are absent.

### Module Attributes

| [`NARRATION_REF`](#foley.weave.NARRATION_REF)   | The synthetic library key WEAVE binds raw narration audio under (when the caller passes audio rather than a ref already in the library).   |
|------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`weave`](#foley.weave.weave)(narration, timeline, \*[, master, ...])   | Weave the chosen sounds under `narration` into a mastered, editable mix.                                                     |
|--------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| [`render`](#foley.weave.render)(timeline, library, \*[, sr, ...])        | Render `timeline` against `library` into a mastered mix (PURE, deterministic).                                               |
| [`hydrate`](#foley.weave.hydrate)(timeline[, word_timeline])              | Resolve every item's anchor + fill processing/id, returning a NEW timeline.                                                  |
| [`parse_symbolic_anchor`](#foley.weave.parse_symbolic_anchor)(onset, \*[, layer, loop]) | Parse SELECT's sparse symbolic `onset` string into a resolved-later `Placement`.                                             |
| [`resolve_anchor`](#foley.weave.resolve_anchor)(placement, word_timeline, \*)    | Resolve a `Placement` to a concrete `(onset_seconds, duration_seconds)`.                                                     |
| [`swap_clip`](#foley.weave.swap_clip)(timeline, item_id, new_clip_ref)      | Swap an item's clip (keeping its placement/processing) — a NEW timeline.                                                     |
| [`nudge`](#foley.weave.nudge)(timeline, item_id, delta_s)               | Shift an item's resolved onset by `delta_s` seconds — a NEW timeline.                                                        |
| [`set_gain`](#foley.weave.set_gain)(timeline, item_id, gain_db)            | Set an item's processing gain (dB, voice-relative) — a NEW timeline.                                                         |
| [`toggle`](#foley.weave.toggle)(timeline, item_id, enabled)              | Non-destructively mute/unmute an item — a NEW timeline.                                                                      |
| [`set_master`](#foley.weave.set_master)(timeline, master)                    | Set the timeline's master profile (name or [`MasterProfile`](#foley.weave.MasterProfile)) — a NEW timeline. |
| [`to_webvtt`](#foley.weave.to_webvtt)(timeline, \*[, window_s])             | Render the timeline's SFX cues as a WebVTT SDH caption file (report 06 / issue #8).                                          |
| [`to_srt`](#foley.weave.to_srt)(timeline, \*[, window_s])                | Render the timeline's SFX cues as an SRT SDH caption file (report 06 / issue #8).                                            |
| [`to_edl`](#foley.weave.to_edl)(timeline, \*[, title])                   | Export `timeline` as a pure-stdlib CMX3600 EDL (deterministic, pinned ids).                                                  |
| [`to_otio`](#foley.weave.to_otio)(timeline, \*[, rate])                   | Export `timeline` as an OpenTimelineIO JSON string (lazy `foley[weave]`).                                                    |
| [`export`](#foley.weave.export)(timeline, \*[, fmt])                     | Export `timeline` as `(format, text)` — OTIO when available, else EDL.                                                       |
| [`reassert_provenance`](#foley.weave.reassert_provenance)(audio, sample_rate, ...)    | Re-assert provenance over the mastered mix — watermark + C2PA sidecar (fail-safe).                                           |
| [`check_requirements`](#foley.weave.check_requirements)(\*[, names, verbose])        | Report which optional WEAVE system binaries are available (`shutil.which`).                                                  |
| [`verify_and_setup`](#foley.weave.verify_and_setup)(\*[, names])                   | Check the optional system deps and return a per-dep status + guidance report.                                                |

### Classes

| [`WeaveResult`](#foley.weave.WeaveResult)(audio, sr, timeline, credits, ...)   | The output of [`weave()`](#foley.weave.weave) — the v1 Definition-of-Done deliverable.                    |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| [`RenderResult`](#foley.weave.RenderResult)(audio, sr, timeline, master_report) | The output of [`render()`](#foley.weave.render): the mastered mix + the hydrated (re-renderable) timeline. |
| [`RenderCache`](#foley.weave.RenderCache)                                      | Per-layer render memo (`bus_hash -> stereo bus array`) for incremental re-render.                                                  |
| [`FullRender`](#foley.weave.FullRender)(\*[, level_clips])                    | Default [`ApplyStrategy`](#foley.weave.ApplyStrategy) — the full per-item DSP chain (report 06 §3-4).             |
| [`PlaceOnly`](#foley.weave.PlaceOnly)()                                      | Dry [`ApplyStrategy`](#foley.weave.ApplyStrategy) — declicked placement, no gain/pan/distance/reverb.             |
| [`Aligner`](#foley.weave.Aligner)(\*args, \*\*kwargs)                      | Narration audio + its transcript → word-level timestamps (forced alignment).                                                       |
| [`ApplyStrategy`](#foley.weave.ApplyStrategy)(\*args, \*\*kwargs)                | How ONE hydrated item's clip is placed onto its layer bus (report 10 §4.2).                                                        |
| [`FakeAligner`](#foley.weave.FakeAligner)()                                    | Deterministic, torch-free [`Aligner`](#foley.weave.Aligner) — evenly spaces the transcript's words.         |
| [`WhisperXAligner`](#foley.weave.WhisperXAligner)(\*[, model_size, device, ...])   | The real ≈±50 ms [`Aligner`](#foley.weave.Aligner) (`foley[align]`) — faster-whisper ASR + wav2vec2 CTC.    |
| [`MasterProfile`](#foley.weave.MasterProfile)([target_lufs, true_peak_db, ...])  | Loudness master target — the delivery spec as data, not code (report 06 §5.2).                                                     |
| [`MasterReport`](#foley.weave.MasterReport)(target_lufs, input_lufs, ...)       | What the master stage did — a JSON-serialisable audit row for the run-artifact.                                                    |

### *class* foley.weave.Aligner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Narration audio + its transcript → word-level timestamps (forced alignment).

Returns a `word_timeline`: a list of `{'word': str, 'start': float, 'end':
float}` dicts (seconds), the raw material the anchor heuristics (report 06
§2.4) turn into sample onsets. The default is the deterministic,
torch-free [`FakeAligner`](foley.weave.align.html.md#foley.weave.align.FakeAligner) (evenly spaces the
transcript’s words across the clip); [`WhisperXAligner`](foley.weave.align.html.md#foley.weave.align.WhisperXAligner)
is the real ≈±50 ms impl behind `foley[align]`.

### *class* foley.weave.ApplyStrategy(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

How ONE hydrated item’s clip is placed onto its layer bus (report 10 §4.2).

The seam that lets the render swap placement policy without touching the
render loop: the default [`FullRender`](#foley.weave.FullRender) applies the
full per-item DSP chain (fit-duration → gain/pan/distance/reverb → declick →
overlay), while [`PlaceOnly`](#foley.weave.PlaceOnly) does a dry declicked
overlay (fast preview / DSP-free fallback). `item` is already anchor-resolved
(`item.placement.onset` is in seconds); `bus` and `clip` are stereo
`float32` working arrays at `sample_rate`. A strategy with settings that change
its output should expose them as a `cache_key` string: the [`RenderCache`](#foley.weave.RenderCache)
keys on it (default: the class name).

### *class* foley.weave.FakeAligner

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic, torch-free [`Aligner`](#foley.weave.Aligner) — evenly spaces the transcript’s words.

The hermetic default: given a transcript, it returns one `{'word','start','end'}`
per whitespace token, spread uniformly across the clip’s duration (or at
`WORDS_PER_SECOND` when the audio is empty). No transcript → an empty
`word_timeline` (the render then falls back to absolute anchors).

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Return an evenly-spaced word timeline for `transcript` over `audio`’s duration.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### *class* foley.weave.FullRender(, level_clips=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Default [`ApplyStrategy`](#foley.weave.ApplyStrategy) — the full per-item DSP chain (report 06 §3-4).

`fit-duration` (loop/trim) → `level` (measured loudness to the reference,
[`foley.level.reference_gain_db()`](foley.level.html.md#foley.level.reference_gain_db), on what will be heard) → distance → reverb send → constant-power pan →
declick → gain (base layer level + item `gain_db`) → overlay at the resolved
onset. Levelling first means the layer gains act on clips of equal loudness, whatever
level each was generated or recorded at (#111); `level_clips=False` renders the
clips as stored.

#### *property* cache_key *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

What distinguishes this strategy’s output in [`RenderCache`](#foley.weave.RenderCache) keys.

### *class* foley.weave.MasterProfile(target_lufs=-16.0, true_peak_db=-1.0, lra=11.0, max_limiting_db=6.0)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

Loudness master target — the delivery spec as data, not code (report 06 §5.2).

#### max_limiting_db *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 6.0*

How far (dB) the master’s loudness stage lets the *sample* peak run over
`true_peak_db` for the default lookahead limiter to take back (it may take
off a little more, the inter-sample overshoot of those peaks). 0 restores a
static, whole-program master. Transient foley (a door slam under narration)
needs a few dB to reach the target at all (foley#91).

### *class* foley.weave.MasterReport(target_lufs, input_lufs, output_lufs, true_peak_dbtp, true_peak_ceiling_db, gain_db, limited, engine)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the master stage did — a JSON-serialisable audit row for the run-artifact.

#### to_dict()

Return the plain-dict form (for `WeaveResult.master_report` / obs).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.weave.NARRATION_REF *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= '_\_foley_narration_\_'*

The synthetic library key WEAVE binds raw narration audio under (when the caller
passes audio rather than a ref already in the library).

### *class* foley.weave.PlaceOnly

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Dry [`ApplyStrategy`](#foley.weave.ApplyStrategy) — declicked placement, no gain/pan/distance/reverb.

The fast preview / DSP-free fallback path: fit-duration → declick → overlay at the
resolved onset, at unity gain.

### *class* foley.weave.RenderCache

Bases: [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

Per-layer render memo (`bus_hash -> stereo bus array`) for incremental re-render.

### *class* foley.weave.RenderResult(audio, sr, timeline, master_report, buses=dict(), alignment=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The output of [`render()`](#foley.weave.render): the mastered mix + the hydrated (re-renderable) timeline.

#### alignment *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

`"cached"` (the timeline already had them),
the aligner that produced them (`"fake"`, `"whisperx"`, a class name), or
`None` when nothing was aligned (no transcript).

* **Type:**
  Where the word timings came from

### *class* foley.weave.WeaveResult(audio, sr, timeline, credits, captions_vtt, captions_srt, master_report, run_manifest_ref=None, content_credential=None, watermark=None, notes=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The output of [`weave()`](#foley.weave.weave) — the v1 Definition-of-Done deliverable.

A mastered mix + an editable, re-renderable timeline + credits + SDH captions + a
reproducible run-artifact join, plus the fail-safe provenance re-assertion.

#### notes *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)*

What the caller should know about how the mix was made, e.g. that word timings
are estimates because no forced aligner is installed (#65).

### *class* foley.weave.WhisperXAligner(, model_size='small', device='cpu', batch_size=16)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The real ≈±50 ms [`Aligner`](#foley.weave.Aligner) (`foley[align]`) — faster-whisper ASR + wav2vec2 CTC.

Lazy-imports `whisperx` inside [`word_timeline()`](#foley.weave.WhisperXAligner.word_timeline) so `import foley.weave`
stays dol-only. Transcribes (if no transcript) then force-aligns at 16 kHz mono.

* **Parameters:**
  * **model_size** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – faster-whisper model name (`tiny`/`base`/`small`/…).
  * **device** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'cpu'` or `'cuda'`.
  * **batch_size** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Transcription batch size.

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Force-align `audio` to its transcript, returning word-level timestamps.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.check_requirements(, names=None, verbose=False)

Report which optional WEAVE system binaries are available (`shutil.which`).

* **Parameters:**
  * **names** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Which requirements to check (default: all of `REQUIREMENTS`).
  * **verbose** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, print an install hint for each missing binary.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
* **Returns:**
  `{name: is_available}`. All-absent is fine — WEAVE degrades to its
  in-process path; the report just tells the user what each binary would unlock.

### foley.weave.export(timeline, , fmt='auto')

Export `timeline` as `(format, text)` — OTIO when available, else EDL.

* **Parameters:**
  * **timeline** ([`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)) – The timeline to export.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'auto'` (OTIO if installed, else EDL), `'otio'`, or `'edl'`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  `(format_name, serialized_text)` — export always succeeds (EDL is the
  dependency-free fallback).

### foley.weave.hydrate(timeline, word_timeline=None)

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

### foley.weave.nudge(timeline, item_id, delta_s)

Shift an item’s resolved onset by `delta_s` seconds — a NEW timeline.

Resolves the item’s anchor against the timeline’s `word_timeline` first, then shifts
the resolved onset and pins the anchor to `absolute` so the manual offset survives a
re-hydrate. This means nudging a still-symbolic (not-yet-hydrated) item on a timeline
that carries alignment shifts from the item’s *true* resolved onset, not from 0. On a
pre-alignment timeline with no `word_timeline` a word/sentence anchor is genuinely
unresolvable, so there the shift is relative to 0 — hydrate/weave first for such items.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.parse_symbolic_anchor(onset, , layer=Layer.sfx_fg, loop=False)

Parse SELECT’s sparse symbolic `onset` string into a resolved-later `Placement`.

The anchor *type* follows the item’s role (report 06 §2.4): beds
(`loop` / `ambience` / `music`) span a **sentence**, stingers land on a
**scene** boundary, and everything else is a **word** anchor; the `ref` is the
quoted phrase the sound lands on. A `None` onset means “no cue”: beds span from
the start, one-shots sit at `absolute` 0. A bare number (defensive — SELECT is
told never to emit one) is read as an absolute offset in seconds.

* **Parameters:**
  * **onset** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The symbolic anchor string (e.g. `"on 'pushed open'"`) or `None`.
  * **layer** ([`Layer`](foley.base.html.md#foley.base.Layer)) – The item’s mix layer (selects span/boundary vs word anchoring).
  * **loop** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the item is a looping bed (span-anchored).
* **Return type:**
  [`Placement`](foley.base.html.md#foley.base.Placement)
* **Returns:**
  A `Placement` whose `onset` (seconds) is resolved later by
  [`resolve_anchor()`](#foley.weave.resolve_anchor) against the `word_timeline`.

### foley.weave.reassert_provenance(audio, sample_rate, records, , asset_id, watermark=None, watermarker=None, sign_cert=None, provenance_store=None)

Re-assert provenance over the mastered mix — watermark + C2PA sidecar (fail-safe).

Watermarks the final mix when it carries AI-generated audio (or when
`watermark=True`), always writes a mix-level C2PA content-credential sidecar,
and best-effort signs+embeds it. Never raises: any failure degrades to
sidecar-only, so weaving is never blocked by provenance.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  `{'audio', 'watermark', 'content_credential'}` — `audio` is the
  (possibly watermarked) mix, `watermark` the AudioSeal meta or `None`,
  `content_credential` the sidecar dict (always present unless credential
  construction itself failed).

### foley.weave.render(timeline, library, , sr=48000, transcript=None, aligner=None, apply_strategy=None, cache=None)

Render `timeline` against `library` into a mastered mix (PURE, deterministic).

* **Parameters:**
  * **timeline** ([`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)) – The sound-design timeline (sparse or hydrated). `narration_ref`
    must resolve in `library`; `master` carries the loudness target.
  * **library** – A [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (or a mapping of ref → audio).
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Working/render sample rate in Hz.
  * **transcript** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Narration transcript for alignment when `timeline.word_timeline`
    is empty (else alignment is skipped — the cached timeline is the seed).
  * **aligner** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Aligner`](foley.weave.protocols.html.md#foley.weave.protocols.Aligner)]) – The [`Aligner`](foley.weave.protocols.html.md#foley.weave.protocols.Aligner) (default: WhisperX if
    `foley[align]` installed, else the deterministic fake).
  * **apply_strategy** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ApplyStrategy`](foley.weave.protocols.html.md#foley.weave.protocols.ApplyStrategy)]) – The per-item [`ApplyStrategy`](foley.weave.protocols.html.md#foley.weave.protocols.ApplyStrategy)
    (default [`FullRender`](#foley.weave.FullRender)).
  * **cache** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`RenderCache`](#foley.weave.RenderCache)]) – An optional [`RenderCache`](#foley.weave.RenderCache) for byte-identical incremental
    re-render (only changed layers recompute).
* **Return type:**
  [`RenderResult`](#foley.weave.RenderResult)
* **Returns:**
  A [`RenderResult`](#foley.weave.RenderResult) — the mastered stereo mix, the hydrated timeline (with
  `word_timeline` cached), and the [`MasterReport`](foley.weave.master.html.md#foley.weave.master.MasterReport).

### foley.weave.resolve_anchor(placement, word_timeline, , snap_pauses=False)

Resolve a `Placement` to a concrete `(onset_seconds, duration_seconds)`.

Dispatches on `placement.anchor` (report 06 §2.4): `absolute` uses the
stored offset; `word` fires on the trigger word; `sentence` spans its
sentence (filling `duration` when unset — beds loop to fill it); `scene` /
`paragraph` land on the boundary. `pre_roll` is then subtracted (clamped at
0), and — when `snap_pauses` — the onset snaps to the nearest inter-word gap.

* **Parameters:**
  * **placement** ([`Placement`](foley.base.html.md#foley.base.Placement)) – The symbolic placement to resolve.
  * **word_timeline** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The forced-aligned `[{'word','start','end'}, ...]`.
  * **snap_pauses** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, snap the resolved onset to the nearest pause.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `(onset_seconds, duration_seconds_or_None)`. `duration` is filled only
  for a span anchor whose `placement.duration` was unset.

### foley.weave.set_gain(timeline, item_id, gain_db)

Set an item’s processing gain (dB, voice-relative) — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.set_master(timeline, master)

Set the timeline’s master profile (name or [`MasterProfile`](#foley.weave.MasterProfile)) — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.swap_clip(timeline, item_id, new_clip_ref)

Swap an item’s clip (keeping its placement/processing) — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.to_edl(timeline, , title='foley SFX')

Export `timeline` as a pure-stdlib CMX3600 EDL (deterministic, pinned ids).

A lightweight interchange for DAWs; each enabled, placed item is one event with
its clip name as the source comment. Always available (no dependency).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.weave.to_otio(timeline, , rate=25)

Export `timeline` as an OpenTimelineIO JSON string (lazy `foley[weave]`).

One or more **parallel** tracks per non-voice layer: each enabled, placed item is a
clip with an external media reference (by clip_ref), positioned at its resolved onset
via a leading gap. Because a single OTIO track is sequential, two same-layer clips that
overlap (or fall within a one-shot’s nominal window) would otherwise be pushed late —
so overlapping clips spill onto sibling sub-tracks, keeping every clip at its true
onset. Non-destructive, minimal-viable fidelity (tracks/clips/onsets; effects/markers
are a later slice).

* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If `opentimelineio` is not installed.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.weave.to_srt(timeline, , window_s=2.0)

Render the timeline’s SFX cues as an SRT SDH caption file (report 06 / issue #8).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.weave.to_webvtt(timeline, , window_s=2.0)

Render the timeline’s SFX cues as a WebVTT SDH caption file (report 06 / issue #8).

Each enabled, placed item becomes one `[bracketed]` cue at its resolved onset.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.weave.toggle(timeline, item_id, enabled)

Non-destructively mute/unmute an item — a NEW timeline.

* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.weave.verify_and_setup(, names=None)

Check the optional system deps and return a per-dep status + guidance report.

Does **not** run installers (system-binary installs need the user’s consent and
sudo). Surfaces the exact per-platform command so the user can opt in.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  `{name: {'available': bool, 'purpose': str, 'install': str, 'url': str}}`.

### foley.weave.weave(narration, timeline, , master='podcast', library=None, transcript=None, aligner=None, apply_strategy=None, sr=48000, cache=None, watermark=None, watermarker=None, sign_cert=None, export_captions=True, provenance_store=None)

Weave the chosen sounds under `narration` into a mastered, editable mix.

The headline WEAVE façade (v1 DoD): `foley.weave(narration, timeline)` →
align → anchor → mix → master → render, plus credits, SDH captions, and a
reproducible run-artifact. Works out of the box with deterministic defaults
(a fake aligner + pure-numpy DSP + in-process mastering); every model / seam is
an optional keyword.

* **Parameters:**
  * **narration** – The voice audio — a path / bytes / file-like / working ndarray, or
    a ref already keyed in `library`.
  * **timeline** ([`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)) – The (sparse) [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline) from
    [`foley.plan()`](foley.html.md#foley.plan); WEAVE resolves anchors and fills processing.
  * **master** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile)]) – A [`MASTER_PROFILES`](foley.base.html.md#foley.base.MASTER_PROFILES) name (`'podcast'` default) or a
    [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile).
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (or a mapping) holding the clips.
  * **transcript** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The narration transcript, for forced alignment (skipped when the
    timeline already carries a `word_timeline`).
  * **aligner** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Aligner`](foley.weave.protocols.html.md#foley.weave.protocols.Aligner)]) – The forced-alignment seam (default: WhisperX if installed, else fake).
  * **apply_strategy** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ApplyStrategy`](foley.weave.protocols.html.md#foley.weave.protocols.ApplyStrategy)]) – The per-item placement seam (default [`FullRender`](#foley.weave.FullRender)).
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Working/render sample rate in Hz.
  * **cache** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`RenderCache`](#foley.weave.RenderCache)]) – An optional [`RenderCache`](#foley.weave.RenderCache) for incremental re-render.
  * **watermark** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – `True` force a watermark, `False` never, `None` (default) auto —
    watermark iff the mix contains AI-generated audio and AudioSeal is installed.
  * **watermarker** – An injected watermarker (the DI seam; tests pass a fake).
  * **sign_cert** – A ready `c2pa.Signer` for the signed+embedded C2PA path (build one
    with [`foley.provenance.make_c2pa_signer()`](foley.provenance.html.md#foley.provenance.make_c2pa_signer)); omit for the sidecar only.
  * **export_captions** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True` (default), emit WebVTT + SRT SDH captions.
  * **provenance_store** – An optional `MutableMapping` to persist the C2PA sidecar.
* **Return type:**
  [`WeaveResult`](#foley.weave.WeaveResult)
* **Returns:**
  A [`WeaveResult`](#foley.weave.WeaveResult).

### Modules

| [`align`](foley.weave.align.html.md#module-foley.weave.align)               | Forced-alignment adapters — the `Aligner` seam's fake default + WhisperX real impl.          |
|-----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`anchor`](foley.weave.anchor.html.md#module-foley.weave.anchor)             | Symbolic-anchor → sample-onset heuristics — the SELECT→WEAVE timing bridge (report 06 §2.4). |
| [`master`](foley.weave.master.html.md#module-foley.weave.master)             | Mastering — loudness-normalize + true-peak-limit the finished mix (report 06 §5).            |
| [`mix`](foley.weave.mix.html.md#module-foley.weave.mix)                   | Pure-numpy mixing DSP — making a clip sit under the voice (report 06 §3).                    |
| [`protocols`](foley.weave.protocols.html.md#module-foley.weave.protocols)       | The structural DI seams of the WEAVE stage — `Aligner` / `ApplyStrategy`.                    |
| [`reaction`](foley.weave.reaction.html.md#module-foley.weave.reaction)         | Audience-reaction timing — a crowd answers an event, it does not coincide with it.           |
| [`requirements`](foley.weave.requirements.html.md#module-foley.weave.requirements) | System-dependency onboarding for WEAVE's optional upgrade paths (accompy-style).             |
| [`timeline`](foley.weave.timeline.html.md#module-foley.weave.timeline)         | The sound-design timeline as an editable document — hydrate, edit, caption.                  |
