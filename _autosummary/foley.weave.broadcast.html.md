# foley.weave.broadcast

A diegetic broadcast bed: speech lines heard through a radio/TV/PA/phone over a bed (#108).

A scene needs “the car radio”: a commentator’s lines over a stadium crowd, coloured as
the device that plays them, looped for the scene. [`broadcast_bed()`](#foley.weave.broadcast.broadcast_bed) makes it in one
call and returns a [`BroadcastBed`](#foley.weave.broadcast.BroadcastBed) whose licence carries the rights of **both**
sources, narrowed, never widened:

```default
bed = foley.broadcast_bed(
    [line1, line2],                      # speech already spoken (arrays, bytes, paths)
    bed_prompt="football stadium crowd", # or bed=<library id or audio>
    speech_license=speech_rights,        # the speech's provenance, as given
    duration=90.0,
)
bed.audio, bed.sr, bed.license
```

The pipeline is small pure stages, each its own function:

1. **speech** — each line becomes a mono clip at `sr` ([`as_clip()`](#foley.weave.broadcast.as_clip)); lines given as
   text go through the injected `tts=` seam first. [`join_lines()`](#foley.weave.broadcast.join_lines) puts `gap_s` of
   silence after each line.
2. **bed** — a library sound id, raw bed audio (with its `bed_license`), or
   `bed_prompt` through [`foley.generate()`](foley.html.md#foley.generate) (budget, consent and licence rules
   unchanged; the `generate=` seam replaces it in tests).
3. **mix** — [`mix_program()`](#foley.weave.broadcast.mix_program) loops speech and bed to `duration` (the WEAVE
   [`fit_duration()`](foley.weave.mix.html.md#foley.weave.mix.fit_duration) loop with its equal-power seam), sets the bed
   > `bed_under_speech_db` below the speech by integrated loudness, and ducks it
   > ([`duck_envelope()`](#foley.weave.broadcast.duck_envelope)): the bed holds that level while a line is spoken and swells
   > up to `-duck_db` back up between lines (a gap shorter than a few release time
   > constants does not reach it: ~9.2 of 10 dB with the defaults; `duck_db=0`: a
   > constant bed).
4. **treatment** — the whole program goes through the device (a radio colours the crowd
   it carries as much as the voice): a named [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset) from
   [`TREATMENTS`](#foley.weave.broadcast.TREATMENTS) (band-pass -> RMS compressor -> lookahead peak limiter), or any
   > `(samples, sr) -> samples` callable.

Rights are checked first ([`mix_refusal()`](#foley.weave.broadcast.mix_refusal): no share-alike, no-derivatives,
territory-limited or unmodifiable source on either side), then the bed is resolved or
generated, and only then is any text spoken. A named generate backend’s licence row
is checked before it is called; a bed from an unnamed generation order can only be
gated on the clip it returns, so that refusal comes after the bed was paid for (never
after the speech). The result always ends in the peak limiter, whatever the
treatment.

**The treatment is a seam.** It is an audio “look” with no foley-specific knowledge, so
its eventual home is the fleet’s audio package (`mixing`, beside
`mixing.loudness`), not foley; until it lands there, foley’s in-house preset chain
is the default (numpy + scipy, which `foley[audio]` already brings through
`mixing[loudness]`; the limiter *is* `mixing.loudness.limit_peaks()`). Swapping in
the fleet’s one is `treatment=<its callable>`.

**Text-to-speech is a seam with no default.** `tts` is any `text -> audio` callable
(an array at `sr`, `(samples, sr)`, encoded bytes, or a path); foley adds no TTS
dependency. Two that exist in the fleet:

```default
import voxy
tts = lambda text: voxy.text_to_speech(text, "commentator").audio  # encoded bytes

from an.audio.elevenlabs_tts import ElevenLabsTTS
eleven = ElevenLabsTTS(output_format="pcm_44100")  # a format soundfile decodes
tts = lambda text: eleven.synthesize(text, VOICE_ID).bytes_
```

The speech’s rights are never inferred from the TTS call: pass them as
`speech_license` (e.g. a [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) for the TTS vendor’s
terms). Without it the result is fail-closed: the speech counts as unknown rights.

Import cost: stdlib, [`foley.base`](foley.base.html.md#module-foley.base) and the numpy-free [`foley.weave.mix`](foley.weave.mix.html.md#module-foley.weave.mix) constants; numpy, scipy and `mixing.loudness`
are imported inside the functions that need them, so `import foley.weave` stays
dol-only.

### Module Attributes

| [`LINE_GAP_S`](#foley.weave.broadcast.LINE_GAP_S)                  | Silence after each spoken line (s); the 0.6 s that read naturally in the #108 starter.                                                                                                                           |
|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`BED_UNDER_SPEECH_DB`](#foley.weave.broadcast.BED_UNDER_SPEECH_DB)         | -12 dB).                                                                                                                                                                                                         |
| [`BED_DUCK_DB`](#foley.weave.broadcast.BED_DUCK_DB)                 | How far the bed dips under each line, relative to its level between lines (dB).                                                                                                                                  |
| [`ACTIVITY_THRESHOLD`](#foley.weave.broadcast.ACTIVITY_THRESHOLD)          | A looped speech-activity mask counts as speech above this value (its seams crossfade).                                                                                                                           |
| [`LOOP_CROSSFADE_S`](#foley.weave.broadcast.LOOP_CROSSFADE_S)            | Equal-power crossfade at each loop seam of the speech and the bed (s).                                                                                                                                           |
| [`DEFAULT_TREATMENT`](#foley.weave.broadcast.DEFAULT_TREATMENT)           | The device a broadcast is heard through when none is named.                                                                                                                                                      |
| [`FILTER_ORDER`](#foley.weave.broadcast.FILTER_ORDER)                | Butterworth order of the treatment's band-pass (per edge).                                                                                                                                                       |
| [`MAX_CUTOFF_NYQUIST_FRACTION`](#foley.weave.broadcast.MAX_CUTOFF_NYQUIST_FRACTION) | The band-pass's upper edge is held under this fraction of Nyquist (a low `sr`).                                                                                                                                  |
| [`COMPRESSOR_DETECTOR_S`](#foley.weave.broadcast.COMPRESSOR_DETECTOR_S)       | Time constant of the compressor's RMS level detector (s).                                                                                                                                                        |
| [`TREATMENT_CEILING_DB`](#foley.weave.broadcast.TREATMENT_CEILING_DB)        | The treatment's peak ceiling (dBFS) after make-up gain.                                                                                                                                                          |
| [`DETECTOR_FLOOR_DB`](#foley.weave.broadcast.DETECTOR_FLOOR_DB)           | Floor of the compressor's level detector, so silence has a finite level (dBFS).                                                                                                                                  |
| [`BROADCAST_OP`](#foley.weave.broadcast.BROADCAST_OP)                | The `transformations` op recorded on the result's licence.                                                                                                                                                       |
| [`UNKNOWN_LICENSE_ID`](#foley.weave.broadcast.UNKNOWN_LICENSE_ID)          | The licence id of rights that were not given (fail-closed, never refused).                                                                                                                                       |
| [`TREATMENTS`](#foley.weave.broadcast.TREATMENTS)                  | `am_radio` is the #108 starter's chain (highpass 450, lowpass 3200); `phone` is the narrowband telephone channel (300-3400 Hz, ITU-T G.712); `tv` a small TV speaker; `pa` a horn loudspeaker, squashed hardest. |
| [`Treatment`](#foley.weave.broadcast.Treatment)                   | a [`TREATMENTS`](#foley.weave.broadcast.TREATMENTS) name, a [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset), any `(samples, sr) -> samples` callable, or `None` (dry, no device).     |
| [`ClipLike`](#foley.weave.broadcast.ClipLike)                    | an array at `sr`, `(samples, its_sr)`, encoded bytes, or a file path.                                                                                                                                            |

### Functions

| [`apply_treatment`](#foley.weave.broadcast.apply_treatment)(samples, sample_rate, preset)    | Colour `samples` as heard through `preset`'s device (mono or `(n, ch)`).                                              |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`as_clip`](#foley.weave.broadcast.as_clip)(item, sample_rate)                       | `item` as a mono `float32` working array at `sample_rate`.                                                            |
| [`bed_gain_db`](#foley.weave.broadcast.bed_gain_db)(speech, bed, sample_rate, \*[, ...]) | The gain that puts `bed` `under_db` below `speech` in integrated loudness.                                            |
| [`broadcast_bed`](#foley.weave.broadcast.broadcast_bed)(lines, \*[, bed, bed_prompt, ...]) | Speech lines heard through a radio/TV/PA/phone over a bed, looped for a scene (#108).                                 |
| [`broadcast_license`](#foley.weave.broadcast.broadcast_license)(bed, speech, \*, treatment)    | The broadcast's rights: the bed's, narrowed to the speech's (never widened).                                          |
| [`duck_envelope`](#foley.weave.broadcast.duck_envelope)(activity, sample_rate, \*[, ...])  | The bed's linear gain: `1` while speech is active, up to `-duck_db` dB above between.                                 |
| [`join_lines`](#foley.weave.broadcast.join_lines)(clips, sample_rate, \*[, gap_s])      | Concatenate mono `clips` with `gap_s` of silence after each one.                                                      |
| [`mix_program`](#foley.weave.broadcast.mix_program)(speech, bed, sample_rate, \*[, ...]) | Speech over the bed, both fitted to `duration` (default: the speech's length).                                        |
| [`mix_refusal`](#foley.weave.broadcast.mix_refusal)(source)                              | Why a sound with rights `source` may not be treated and mixed in, or `None`.                                          |
| [`resolve_treatment`](#foley.weave.broadcast.resolve_treatment)(treatment)                     | `treatment=` as a `(samples, sr) -> samples` callable (`None`: dry).                                                  |
| [`speech_activity`](#foley.weave.broadcast.speech_activity)(clips, sample_rate, \*[, gap_s]) | Where [`join_lines()`](#foley.weave.broadcast.join_lines) puts speech: `1` over each clip, `0` in the gaps. |

### Classes

| [`BroadcastBed`](#foley.weave.broadcast.BroadcastBed)(audio, sr, license, sources, ...)   | A rendered broadcast bed: the audio and the rights of everything in it.         |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset)(name, highpass_hz, ...[, ...])   | A diegetic-source colouring: band-pass -> RMS compressor -> make-up -> limiter. |

### Exceptions

| [`BroadcastRefusal`](#foley.weave.broadcast.BroadcastRefusal)   | A source whose rights do not allow it into a broadcast bed (refused, fail-closed).   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------|

### foley.weave.broadcast.ACTIVITY_THRESHOLD *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.5*

A looped speech-activity mask counts as speech above this value (its seams crossfade).

### foley.weave.broadcast.BED_DUCK_DB *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= -10.0*

How far the bed dips under each line, relative to its level between lines (dB).

### foley.weave.broadcast.BED_UNDER_SPEECH_DB *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= -12.0*

-12 dB).

* **Type:**
  Where the bed sits under the speech, in LU of integrated loudness (#108

### foley.weave.broadcast.BROADCAST_OP *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'broadcast_bed'*

The `transformations` op recorded on the result’s licence.

### *class* foley.weave.broadcast.BroadcastBed(audio, sr, license, sources, treatment, notes=list())

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

The mix’s rights ([`broadcast_license()`](#foley.weave.broadcast.broadcast_license)): the bed’s narrowed to the
speech’s, never wider than either.

* **Type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

#### sources

`(bed, speech)` provenance as given: the bed’s
[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) (library or generated) or
[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), and the speech’s licence (`None` if not
given). For the credit line use [`credits`](#foley.weave.broadcast.BroadcastBed.credits), which reads both off
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

Length of [`audio`](#foley.weave.broadcast.BroadcastBed.audio) in seconds.

### *exception* foley.weave.broadcast.BroadcastRefusal

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A source whose rights do not allow it into a broadcast bed (refused, fail-closed).

### foley.weave.broadcast.COMPRESSOR_DETECTOR_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.02*

Time constant of the compressor’s RMS level detector (s).

### foley.weave.broadcast.ClipLike

an array at `sr`, `(samples, its_sr)`, encoded bytes, or a file path.

* **Type:**
  One clip

alias of `ndarray` | [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)

### foley.weave.broadcast.DEFAULT_TREATMENT *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'am_radio'*

The device a broadcast is heard through when none is named.

### foley.weave.broadcast.DETECTOR_FLOOR_DB *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= -120.0*

Floor of the compressor’s level detector, so silence has a finite level (dBFS).

### foley.weave.broadcast.FILTER_ORDER *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 4*

Butterworth order of the treatment’s band-pass (per edge).

### foley.weave.broadcast.LINE_GAP_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.6*

Silence after each spoken line (s); the 0.6 s that read naturally in the #108 starter.

### foley.weave.broadcast.LOOP_CROSSFADE_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.05*

Equal-power crossfade at each loop seam of the speech and the bed (s).

### foley.weave.broadcast.MAX_CUTOFF_NYQUIST_FRACTION *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.95*

The band-pass’s upper edge is held under this fraction of Nyquist (a low `sr`).

### foley.weave.broadcast.TREATMENTS *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [TreatmentPreset](#foley.weave.broadcast.TreatmentPreset)]* *= {'am_radio': TreatmentPreset(name='am_radio', highpass_hz=450.0, lowpass_hz=3200.0, threshold_db=-24.0, ratio=4.0, makeup_db=6.0, filter_order=4, detector_s=0.02, ceiling_db=-1.0), 'pa': TreatmentPreset(name='pa', highpass_hz=400.0, lowpass_hz=4000.0, threshold_db=-26.0, ratio=6.0, makeup_db=8.0, filter_order=4, detector_s=0.02, ceiling_db=-1.0), 'phone': TreatmentPreset(name='phone', highpass_hz=300.0, lowpass_hz=3400.0, threshold_db=-22.0, ratio=4.0, makeup_db=6.0, filter_order=4, detector_s=0.02, ceiling_db=-1.0), 'tv': TreatmentPreset(name='tv', highpass_hz=150.0, lowpass_hz=7000.0, threshold_db=-20.0, ratio=3.0, makeup_db=4.0, filter_order=4, detector_s=0.02, ceiling_db=-1.0)}*

`am_radio` is the #108 starter’s chain (highpass 450,
lowpass 3200); `phone` is the narrowband telephone channel (300-3400 Hz, ITU-T
G.712); `tv` a small TV speaker; `pa` a horn loudspeaker, squashed hardest.

* **Type:**
  The named devices. Passbands

### foley.weave.broadcast.TREATMENT_CEILING_DB *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= -1.0*

The treatment’s peak ceiling (dBFS) after make-up gain.

### foley.weave.broadcast.Treatment

a [`TREATMENTS`](#foley.weave.broadcast.TREATMENTS) name, a [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset),
any `(samples, sr) -> samples` callable, or `None` (dry, no device).

* **Type:**
  What `treatment=` takes

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset) | `Callable`[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], `ndarray`] | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.weave.broadcast.TreatmentPreset(name, highpass_hz, lowpass_hz, threshold_db, ratio, makeup_db=0.0, filter_order=4, detector_s=0.02, ceiling_db=-1.0)

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

### foley.weave.broadcast.UNKNOWN_LICENSE_ID *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'unknown'*

The licence id of rights that were not given (fail-closed, never refused).

### foley.weave.broadcast.apply_treatment(samples, sample_rate, preset)

Colour `samples` as heard through `preset`’s device (mono or `(n, ch)`).

Band-pass -> RMS compressor with make-up gain -> lookahead peak limiter
(`mixing.loudness.limit_peaks()`). Returns `float32`, same shape.

Lazy dependencies: numpy, scipy, `mixing[loudness]` (all in `foley[audio]`).

* **Return type:**
  `ndarray`

### foley.weave.broadcast.as_clip(item, sample_rate)

`item` as a mono `float32` working array at `sample_rate`.

A bare array is taken to be at `sample_rate` already; `(samples, sr)` is
resampled; bytes and paths are decoded with [`foley.audio.load()`](foley.audio.html.md#foley.audio.load). Integer PCM
is scaled to full scale 1.0.

* **Return type:**
  `ndarray`

### foley.weave.broadcast.bed_gain_db(speech, bed, sample_rate, , under_db=-12.0)

The gain that puts `bed` `under_db` below `speech` in integrated loudness.

Returns `(gain_db, note)`. When either is too short or too quiet to measure, the
gain is `under_db` applied to the bed as is, and `note` says so. A boost is
capped at `mixing.loudness.MAX_GAIN_DB`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.weave.broadcast.broadcast_bed(lines, , bed=None, bed_prompt=None, treatment='am_radio', gap_s=0.6, duration=None, bed_under_speech_db=-12.0, duck_db=-10.0, duck_attack_s=0.02, duck_release_s=0.3, loop_speech=True, crossfade_s=0.05, ceiling_db=-1.0, speech_license=None, bed_license=None, tts=None, library=None, generate=None, generate_options=None, sr=None)

Speech lines heard through a radio/TV/PA/phone over a bed, looped for a scene (#108).

Everything that can be checked is checked before anything is paid for: the lines,
the treatment, the bed’s form, and the rights of the speech and of a given bed
([`mix_refusal()`](#foley.weave.broadcast.mix_refusal)). Then the bed is generated (if prompted) and gated, and only
then is the text spoken.

* **Parameters:**
  * **lines** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)) – The spoken lines, in order: each an array at `sr`, `(samples, sr)`,
    encoded bytes or a path; or text (a `str` that is not a file), which goes
    through `tts=`. Audio lines never go through `tts`.
  * **bed** – The bed: a library sound id, or its audio (any `lines` form).
  * **bed_prompt** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Instead of `bed`: a prompt for [`foley.generate()`](foley.html.md#foley.generate) (its budget,
    paid-generation consent and licence gate apply unchanged).
  * **treatment** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], `ndarray`], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The device: a [`TREATMENTS`](#foley.weave.broadcast.TREATMENTS) name (`'am_radio'` default,
    `'tv'`, `'pa'`, `'phone'`), a [`TreatmentPreset`](#foley.weave.broadcast.TreatmentPreset), any
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
  [`BroadcastBed`](#foley.weave.broadcast.BroadcastBed)
* **Returns:**
  A [`BroadcastBed`](#foley.weave.broadcast.BroadcastBed).
* **Raises:**
  * [**BroadcastRefusal**](#foley.weave.broadcast.BroadcastRefusal) – A source’s rights do not allow it in ([`mix_refusal()`](#foley.weave.broadcast.mix_refusal)).
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – Unusable lines, treatment or bed form (before anything is spent).
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – A bed id that is neither a file nor in the library.

### foley.weave.broadcast.broadcast_license(bed, speech, , treatment)

The broadcast’s rights: the bed’s, narrowed to the speech’s (never widened).

A copy of the bed’s licence, narrowed to the speech’s through the same lineage an
edit records ([`foley.sources.edit.EditLineage`](foley.sources.edit.html.md#foley.sources.edit.EditLineage): the permissions both hold,
either’s attribution and notice, the stricter AI-use scope, and a `transformations`
entry the credits and content credential read as “derived from” the speech). It is
AI-generated, and its AI disclosure recommended, if either source’s is; the
generator named is the bed’s, else the speech’s. Its bytes may be stored only if
both allow it, and its rights are verified only if both are. The bed’s own
watermark and content-credential reference are dropped: they described the bed’s
bytes, not the mix. `speech=None` narrows to unknown rights. Raises
[`BroadcastRefusal`](#foley.weave.broadcast.BroadcastRefusal) for a source [`mix_refusal()`](#foley.weave.broadcast.mix_refusal) refuses.

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.weave.broadcast.duck_envelope(activity, sample_rate, , duck_db=-10.0, attack=0.02, release=0.3)

The bed’s linear gain: `1` while speech is active, up to `-duck_db` dB above between.

`activity` above [`ACTIVITY_THRESHOLD`](#foley.weave.broadcast.ACTIVITY_THRESHOLD) counts as speech; the transitions are
the WEAVE attack/release follower ([`attack_release_envelope()`](foley.weave.mix.html.md#foley.weave.mix.attack_release_envelope)),
so the bed dips into each line and swells back after it without clicks. A
positive `duck_db` would invert the effect, so it is refused.

```pycon
>>> duck_envelope([1.0, 1.0], 10, duck_db=-6.0).tolist()
[1.0, 1.0]
```

* **Return type:**
  `ndarray`

### foley.weave.broadcast.join_lines(clips, sample_rate, , gap_s=0.6)

Concatenate mono `clips` with `gap_s` of silence after each one.

```pycon
>>> import numpy as np
>>> join_lines([np.ones(2), np.ones(3)], 10, gap_s=0.1).tolist()
[1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0]
```

* **Return type:**
  `ndarray`

### foley.weave.broadcast.mix_program(speech, bed, sample_rate, , duration=None, bed_under_speech_db=-12.0, activity=None, duck_db=-10.0, duck_attack_s=0.02, duck_release_s=0.3, loop_speech=True, crossfade_s=0.05)

Speech over the bed, both fitted to `duration` (default: the speech’s length).

The bed always loops (seamless, equal-power seams); the speech loops too when
`loop_speech`, else plays once and the bed carries on. When `activity` (where
the speech is spoken, as from [`speech_activity()`](#foley.weave.broadcast.speech_activity)) is given, the bed is ducked
([`duck_envelope()`](#foley.weave.broadcast.duck_envelope), with `duck_attack_s` / `duck_release_s`):
`bed_under_speech_db` under each line, up to `-duck_db` louder between them; without it, or with `duck_db=0`, the bed sits at
`bed_under_speech_db` throughout. Returns `(mono, notes)`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.weave.broadcast.mix_refusal(source)

Why a sound with rights `source` may not be treated and mixed in, or `None`.

The broadcast’s licence is the bed’s narrowed to the speech’s, so it cannot carry a
share-alike obligation, and the device modifies both sources. Refused: a
share-alike licence (on the record or in its lineage), a territory exclusion, a
licence with no [`LICENSE_FLAGS`](foley.licensing.html.md#foley.licensing.LICENSE_FLAGS) row (an `ND` one among
them), or one that forbids modification. Unknown rights (`'unknown'`) are not
refused: the result fails closed instead.

```pycon
>>> from foley.licensing import apply_license_flags
>>> ok = apply_license_flags(LicenseRecord(source="s", license_id="CC-BY-4.0"))
>>> mix_refusal(ok) is None
True
>>> mix_refusal(LicenseRecord(source="s", license_id="CC-BY-SA-4.0"))[:40]
'its licence (CC-BY-SA-4.0) is share-alik'
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.weave.broadcast.resolve_treatment(treatment)

`treatment=` as a `(samples, sr) -> samples` callable (`None`: dry).

```pycon
>>> resolve_treatment("phone").name
'phone'
>>> resolve_treatment(None)(1, 2)
1
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], `ndarray`]

### foley.weave.broadcast.speech_activity(clips, sample_rate, , gap_s=0.6)

Where [`join_lines()`](#foley.weave.broadcast.join_lines) puts speech: `1` over each clip, `0` in the gaps.

```pycon
>>> import numpy as np
>>> speech_activity([np.zeros(2), np.ones(1)], 10, gap_s=0.1).tolist()
[1.0, 1.0, 0.0, 1.0, 0.0]
```

* **Return type:**
  `ndarray`
