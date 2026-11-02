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

| [`weave`](#foley.weave.weave)(narration, timeline, \*[, master, ...])    | Weave the chosen sounds under `narration` into a mastered, editable mix.                                                     |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| [`render`](#foley.weave.render)(timeline, library, \*[, sr, ...])         | Render `timeline` against `library` into a mastered mix (PURE, deterministic).                                               |
| [`hydrate`](#foley.weave.hydrate)(timeline[, word_timeline])               | Resolve every item's anchor + fill processing/id, returning a NEW timeline.                                                  |
| [`parse_symbolic_anchor`](#foley.weave.parse_symbolic_anchor)(onset, \*[, layer, loop])  | Parse SELECT's sparse symbolic `onset` string into a resolved-later `Placement`.                                             |
| [`resolve_anchor`](#foley.weave.resolve_anchor)(placement, word_timeline, \*)     | Resolve a `Placement` to a concrete `(onset_seconds, duration_seconds)`.                                                     |
| [`swap_clip`](#foley.weave.swap_clip)(timeline, item_id, new_clip_ref)       | Swap an item's clip (keeping its placement/processing) — a NEW timeline.                                                     |
| [`nudge`](#foley.weave.nudge)(timeline, item_id, delta_s)                | Shift an item's resolved onset by `delta_s` seconds — a NEW timeline.                                                        |
| [`set_gain`](#foley.weave.set_gain)(timeline, item_id, gain_db)             | Set an item's processing gain (dB, voice-relative) — a NEW timeline.                                                         |
| [`toggle`](#foley.weave.toggle)(timeline, item_id, enabled)               | Non-destructively mute/unmute an item — a NEW timeline.                                                                      |
| [`set_master`](#foley.weave.set_master)(timeline, master)                     | Set the timeline's master profile (name or [`MasterProfile`](#foley.weave.MasterProfile)) — a NEW timeline. |
| [`to_webvtt`](#foley.weave.to_webvtt)(timeline, \*[, window_s])              | Render the timeline's SFX cues as a WebVTT SDH caption file (report 06 / issue #8).                                          |
| [`to_srt`](#foley.weave.to_srt)(timeline, \*[, window_s])                 | Render the timeline's SFX cues as an SRT SDH caption file (report 06 / issue #8).                                            |
| [`to_edl`](#foley.weave.to_edl)(timeline, \*[, title])                    | Export `timeline` as a pure-stdlib CMX3600 EDL (deterministic, pinned ids).                                                  |
| [`to_otio`](#foley.weave.to_otio)(timeline, \*[, rate])                    | Export `timeline` as an OpenTimelineIO JSON string (lazy `foley[weave]`).                                                    |
| [`export`](#foley.weave.export)(timeline, \*[, fmt])                      | Export `timeline` as `(format, text)` — OTIO when available, else EDL.                                                       |
| [`reassert_provenance`](#foley.weave.reassert_provenance)(audio, sample_rate, ...)     | Re-assert provenance over the mastered mix — watermark + C2PA sidecar (fail-safe).                                           |
| [`check_requirements`](#foley.weave.check_requirements)(\*[, names, verbose])         | Report which optional WEAVE system binaries are available (`shutil.which`).                                                  |
| [`verify_and_setup`](#foley.weave.verify_and_setup)(\*[, names])                    | Check the optional system deps and return a per-dep status + guidance report.                                                |
| [`broadcast_bed`](#foley.weave.broadcast_bed)(lines, \*[, bed, bed_prompt, ...]) | Speech lines heard through a radio/TV/PA/phone over a bed, looped for a scene (#108).                                        |

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
| [`MFAAligner`](#foley.weave.MFAAligner)(\*[, mfa, models, extra_args, ...])   | Montreal Forced Aligner (`mfa align_one`) behind the [`Aligner`](#foley.weave.Aligner) seam.                |
| [`AeneasAligner`](#foley.weave.AeneasAligner)(\*[, python, languages, ...])      | aeneas (TTS + DTW) behind the [`Aligner`](#foley.weave.Aligner) seam, one fragment per word.                |
| [`MasterProfile`](#foley.weave.MasterProfile)([target_lufs, true_peak_db, ...])  | Loudness master target — the delivery spec as data, not code (report 06 §5.2).                                                     |
| [`MasterReport`](#foley.weave.MasterReport)(target_lufs, input_lufs, ...)       | What the master stage did — a JSON-serialisable audit row for the run-artifact.                                                    |
| [`BroadcastBed`](#foley.weave.BroadcastBed)(audio, sr, license, sources, ...)   | A rendered broadcast bed: the audio and the rights of everything in it.                                                            |
| [`TreatmentPreset`](#foley.weave.TreatmentPreset)(name, highpass_hz, ...[, ...])   | A diegetic-source colouring: band-pass -> RMS compressor -> make-up -> limiter.                                                    |

### Exceptions

| [`BroadcastRefusal`](#foley.weave.BroadcastRefusal)   | A source whose rights do not allow it into a broadcast bed (refused, fail-closed).   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------|

### *class* foley.weave.AeneasAligner(\*, python='/opt/hostedtoolcache/Python/3.12.15/x64/bin/python', languages=None, timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

aeneas (TTS + DTW) behind the [`Aligner`](#foley.weave.Aligner) seam, one fragment per word.

Light and language-broad (anything espeak speaks), coarser than MFA at word
level, and AGPL-licensed: foley runs it as a separate program and never imports
it. aeneas pins old dependencies, so it often lives in its own virtualenv;
point `python` at that interpreter.

* **Parameters:**
  * **python** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A Python interpreter with `aeneas` installed (default: this one).
  * **languages** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – foley language code → aeneas task language (default
    `AENEAS_LANGUAGES`).
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Align `transcript` to `audio`; `[]` when there is no transcript.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

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

### *class* foley.weave.BroadcastBed(audio, sr, license, sources, treatment, notes=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A rendered broadcast bed: the audio and the rights of everything in it.

#### audio

Mono `float32` samples.

* **Type:**
  `ndarray`

#### sr

Sample rate (Hz).

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### license

The mix’s rights (`broadcast_license()`): the bed’s narrowed to the
speech’s, never wider than either.

* **Type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

#### sources

`(bed, speech)` provenance as given: the bed’s
[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) (library or generated) or
[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), and the speech’s licence (`None` if not
given). For the credit line use [`credits`](#foley.weave.BroadcastBed.credits), which reads both off
`license`.

* **Type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)

#### treatment

The device’s name (`'dry'` for none).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### notes

What the caller should know (unmeasurable levels, missing rights, the
bed generation’s own notes).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

#### *property* credits

the bed, “derived from” the speech.

* **Type:**
  The attribution [`Credits`](foley.provenance.html.md#foley.provenance.Credits)

#### *property* duration_s *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Length of [`audio`](#foley.weave.BroadcastBed.audio) in seconds.

### *exception* foley.weave.BroadcastRefusal

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A source whose rights do not allow it into a broadcast bed (refused, fail-closed).

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

### *class* foley.weave.MFAAligner(\*, mfa='mfa', models=None, extra_args=(), timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Montreal Forced Aligner (`mfa align_one`) behind the [`Aligner`](#foley.weave.Aligner) seam.

Kaldi-based, MIT-licensed, and among the most accurate open aligners on read
speech. It needs a pronunciation dictionary and an acoustic model per language,
downloaded once (`mfa model download ...`). MFA normalises the text (case,
punctuation, clitics) and writes `<unk>` for a word missing from its dictionary
(numbers too); the timeline still holds the transcript’s own words
(`onto_transcript()`), an unknown one timed by its `<unk>`.

* **Parameters:**
  * **mfa** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `mfa` executable: a name on `PATH`, or a path into a conda env
    (no need to activate it; its `bin` is put on the program’s `PATH`).
  * **models** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `{language: (dictionary, acoustic_model)}`, names or paths as
    `mfa align_one` takes them (default `MFA_MODELS`).
  * **extra_args** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – More `mfa align_one` options (`("--beam", "100")`).
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Align `transcript` to `audio`; `[]` when there is no transcript.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

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

### *class* foley.weave.TreatmentPreset(name, highpass_hz, lowpass_hz, threshold_db, ratio, makeup_db=0.0, filter_order=4, detector_s=0.02, ceiling_db=-1.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A diegetic-source colouring: band-pass -> RMS compressor -> make-up -> limiter.

Callable as `preset(samples, sample_rate)`, so a preset is just one value of the
`treatment=` strategy (any `(samples, sr) -> samples` callable is another).

#### name

The preset’s name (recorded on the result’s licence).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### highpass_hz

Lower edge of the device’s passband (Hz).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### lowpass_hz

Upper edge of the device’s passband (Hz).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### threshold_db

Compressor threshold (dBFS of the RMS detector).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### ratio

Compressor ratio above the threshold (`1` = none).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### makeup_db

Gain after the compressor (dB).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### filter_order

Butterworth order of the band-pass.

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### detector_s

RMS detector time constant (s).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### ceiling_db

Peak ceiling of the final limiter (dBFS).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### *class* foley.weave.WeaveResult(audio, sr, timeline, credits, captions_vtt, captions_srt, master_report, run_manifest_ref=None, content_credential=None, watermark=None, notes=list(), alignment=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The output of [`weave()`](#foley.weave.weave) — the v1 Definition-of-Done deliverable.

A mastered mix + an editable, re-renderable timeline + credits + SDH captions + a
reproducible run-artifact join, plus the fail-safe provenance re-assertion.

#### alignment *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

the aligner’s name (`fake` = evenly spaced
estimates, `whisperx`, `mfa`, …) or `cached` (the timeline already had them).

* **Type:**
  Where the word timings came from

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

### foley.weave.broadcast_bed(lines, , bed=None, bed_prompt=None, treatment='am_radio', gap_s=0.6, duration=None, bed_under_speech_db=-12.0, duck_db=-10.0, duck_attack_s=0.02, duck_release_s=0.3, loop_speech=True, crossfade_s=0.05, ceiling_db=-1.0, speech_license=None, bed_license=None, tts=None, library=None, generate=None, generate_options=None, sr=None)

Speech lines heard through a radio/TV/PA/phone over a bed, looped for a scene (#108).

Everything that can be checked is checked before anything is paid for: the lines,
the treatment, the bed’s form, and the rights of the speech and of a given bed
(`mix_refusal()`). Then the bed is generated (if prompted) and gated, and only
then is the text spoken.

* **Parameters:**
  * **lines** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)) – The spoken lines, in order: each an array at `sr`, `(samples, sr)`,
    encoded bytes or a path; or text (a `str` that is not a file), which goes
    through `tts=`. Audio lines never go through `tts`.
  * **bed** – The bed: a library sound id, or its audio (any `lines` form).
  * **bed_prompt** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Instead of `bed`: a prompt for [`foley.generate()`](foley.html.md#foley.generate) (its budget,
    paid-generation consent and licence gate apply unchanged).
  * **treatment** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`TreatmentPreset`](foley.weave.broadcast.html.md#foley.weave.broadcast.TreatmentPreset), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], `ndarray`], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The device: a `TREATMENTS` name (`'am_radio'` default,
    `'tv'`, `'pa'`, `'phone'`), a [`TreatmentPreset`](#foley.weave.TreatmentPreset), any
    `(samples, sr) -> samples` callable (e.g. the fleet’s, once `mixing` has
    it), or `None` for dry. Applied to the whole program, crowd included.
  * **gap_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Silence after each line (s).
  * **duration** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Length of the result (s); `None`: the lines once, with their gaps.
  * **bed_under_speech_db** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The bed’s level under the speech (LU, integrated
    loudness), set **before** the treatment: the device’s compressor then
    narrows the gap a little, as a real one would.
  * **duck_db** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – How far the bed dips under each line relative to its level between
    lines (dB, negative): the bed sits `bed_under_speech_db` under the speech
    while a line is spoken and swells up to `-duck_db` back up in the gaps
    (short gaps fall short: ~9.2 dB with the defaults). Must be `<= 0`.
    `0`: a constant bed (the behaviour before #253).
  * **duck_attack_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Time constant (s) of the bed’s dip into each line.
  * **duck_release_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Time constant (s) of the bed’s swell after each line.
  * **loop_speech** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Repeat the lines to fill `duration` (else they play once).
  * **crossfade_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Equal-power crossfade at each loop seam (s).
  * **ceiling_db** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The result’s peak ceiling (dBFS), held whatever the treatment
    (`mixing.loudness.limit_peaks()`).
  * **speech_license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – The speech’s rights, as given (e.g. the TTS vendor’s terms).
    `None`: unknown, so the result’s rights fail closed.
  * **bed_license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – The rights of raw bed audio given as `bed` (a library or
    generated bed carries its own).
  * **tts** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[`ndarray`, [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)]]]) – A `text -> audio` callable that speaks text lines (no default: see the
    module docstring for voxy and an’s ElevenLabs provider).
  * **library** – Where a bed id is looked up and a generated bed is stored (default:
    the process-wide library).
  * **generate** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)]) – The bed generator (default [`foley.generate()`](foley.html.md#foley.generate); a test seam).
  * **generate_options** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Keyword arguments for it (`backend`, `budget`,
    `duration_s`, `store`, …; not `library`).
  * **sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Working sample rate (default `foley.audio.WORKING_SAMPLE_RATE`).
* **Return type:**
  [`BroadcastBed`](foley.weave.broadcast.html.md#foley.weave.broadcast.BroadcastBed)
* **Returns:**
  A [`BroadcastBed`](#foley.weave.BroadcastBed).
* **Raises:**
  * [**BroadcastRefusal**](#foley.weave.BroadcastRefusal) – A source’s rights do not allow it in (`mix_refusal()`).
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – Unusable lines, treatment or bed form (before anything is spent).
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – A bed id that is neither a file nor in the library.

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

### foley.weave.render(timeline, library, , sr=48000, transcript=None, language=None, aligner=None, apply_strategy=None, cache=None)

Render `timeline` against `library` into a mastered mix (PURE, deterministic).

* **Parameters:**
  * **timeline** ([`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)) – The sound-design timeline (sparse or hydrated). `narration_ref`
    must resolve in `library`; `master` carries the loudness target.
  * **library** – A [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (or a mapping of ref → audio).
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Working/render sample rate in Hz.
  * **transcript** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Narration transcript for alignment when `timeline.word_timeline`
    is empty (else alignment is skipped — the cached timeline is the seed).
  * **language** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The narration’s language code (`"fr"`, …), passed to the aligner,
    which picks its models by it. `None` (default) sends none: the aligner’s own
    default (English for the built-ins) applies. Unused when the timeline already
    carries a `word_timeline`.
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

### foley.weave.weave(narration, timeline, , master='podcast', library=None, transcript=None, language=None, aligner=None, apply_strategy=None, sr=48000, cache=None, watermark=None, watermarker=None, sign_cert=None, export_captions=True, provenance_store=None, intended_use=None)

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
  * **language** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The narration’s language code (`"fr"`, …), passed to the aligner
    (MFA and aeneas pick their models by it; #225). `None` (default): the
    aligner’s own default, English for the built-ins. Like `transcript`, it is
    unused when the timeline already carries a `word_timeline` (a note says so).
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
  * **intended_use** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)]) – The rights intent the mix is for (#208). Given, the gate is
    fail-closed: every *enabled* clip is judged by its record in `library`
    (a clip with no record is refused), and so is the narration when it is a
    library ref; any refusal raises before rendering. `None` (default)
    renders as before but warns (`FutureWarning`) about what
    [`DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE) would refuse: a future
    release gates by default.
* **Return type:**
  [`WeaveResult`](#foley.weave.WeaveResult)
* **Returns:**
  A [`WeaveResult`](#foley.weave.WeaveResult).
* **Raises:**
  [**LicenseRefusal**](foley.html.md#foley.LicenseRefusal) – If `intended_use` is given and refuses a clip or the
      narration (`.refused` names each id and reason).

### Modules

| [`align`](foley.weave.align.html.md#module-foley.weave.align)               | Forced-alignment adapters — the `Aligner` seam's fake default + WhisperX real impl.          |
|-----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`anchor`](foley.weave.anchor.html.md#module-foley.weave.anchor)             | Symbolic-anchor → sample-onset heuristics — the SELECT→WEAVE timing bridge (report 06 §2.4). |
| [`broadcast`](foley.weave.broadcast.html.md#module-foley.weave.broadcast)       | A diegetic broadcast bed: speech lines heard through a radio/TV/PA/phone over a bed (#108).  |
| [`cli_aligners`](foley.weave.cli_aligners.html.md#module-foley.weave.cli_aligners) | Forced aligners run as external programs: Montreal Forced Aligner and aeneas (#43).          |
| [`master`](foley.weave.master.html.md#module-foley.weave.master)             | Mastering — loudness-normalize + true-peak-limit the finished mix (report 06 §5).            |
| [`mix`](foley.weave.mix.html.md#module-foley.weave.mix)                   | Pure-numpy mixing DSP — making a clip sit under the voice (report 06 §3).                    |
| [`protocols`](foley.weave.protocols.html.md#module-foley.weave.protocols)       | The structural DI seams of the WEAVE stage — `Aligner` / `ApplyStrategy`.                    |
| [`reaction`](foley.weave.reaction.html.md#module-foley.weave.reaction)         | Audience-reaction timing — a crowd answers an event, it does not coincide with it.           |
| [`requirements`](foley.weave.requirements.html.md#module-foley.weave.requirements) | System-dependency onboarding for WEAVE's optional upgrade paths (accompy-style).             |
| [`timeline`](foley.weave.timeline.html.md#module-foley.weave.timeline)         | The sound-design timeline as an editable document — hydrate, edit, caption.                  |
