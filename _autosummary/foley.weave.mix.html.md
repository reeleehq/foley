# foley.weave.mix

Pure-numpy mixing DSP — making a clip sit under the voice (report 06 §3).

Deterministic, testable, shell-out-free primitives for the WEAVE mixer: level
(gain staging), envelope-follower ducking, constant-power panning, a distance
recipe (attenuation + air-absorption low-pass), a pure-numpy reverb send,
equal-power crossfades / declicks, seamless loop/trim to a duration, and overlay.

Everything operates on the working representation (`float32`, time on axis 0);
the mix graph is **stereo** `(frames, 2)` so panning composes — [`constant_power_pan()`](#foley.weave.mix.constant_power_pan)
is the mono→stereo point. `numpy` is imported lazily inside each function so
`import foley.weave` stays dol-only (mirroring [`foley.audio`](foley.audio.html.md#module-foley.audio)). Nothing here
reaches for `scipy`/`pyroomacoustics`; those are optional-upgrade paths for a
later slice behind `foley[weave]`.

### Module Attributes

| [`LAYER_GAIN_DB`](#foley.weave.mix.LAYER_GAIN_DB)         | Base per-layer gain (dB, relative to the voice bus at 0 dB).                               |
|------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`DISTANCE_MAX_ATTEN_DB`](#foley.weave.mix.DISTANCE_MAX_ATTEN_DB) | Attenuation (dB) applied at maximum distance (distance == 1.0); ~inverse-distance.         |
| [`DISTANCE_MAX_LP`](#foley.weave.mix.DISTANCE_MAX_LP)       | Air-absorption one-pole low-pass coefficient at maximum distance (0 = none, →1 = darkest). |
| [`REVERB_IR_S`](#foley.weave.mix.REVERB_IR_S)           | Reverb-send impulse-response length (seconds) and decay time-constant.                     |

### Functions

| [`apply_distance`](#foley.weave.mix.apply_distance)(clip, sample_rate, distance)        | Apply a distance recipe: attenuation + air-absorption low-pass (report 06 §3.4).                |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| [`attack_release_envelope`](#foley.weave.mix.attack_release_envelope)(target, sample_rate, \*)   | Smooth a piecewise-constant gain `target` with a one-pole attack/release follower.              |
| [`constant_power_pan`](#foley.weave.mix.constant_power_pan)(clip, pan)                      | Pan a (mono or stereo) clip to a stereo image with a constant-power law (report 06 §3.3).       |
| [`convolution_reverb`](#foley.weave.mix.convolution_reverb)(clip, sample_rate, ir, \*, ...) | Convolution reverb with a real (recorded or synthesised) impulse response (report 06 §3.5).     |
| [`db_to_lin`](#foley.weave.mix.db_to_lin)(db)                                      | Convert decibels to a linear amplitude factor (`10 ** (db/20)`).                                |
| [`declick`](#foley.weave.mix.declick)(clip, sample_rate, \*[, fade_in, ...])     | Apply short in/out fades so an edit point produces no click (report 06 §3.6).                   |
| [`equal_power_crossfade`](#foley.weave.mix.equal_power_crossfade)(a, b, overlap_samples)       | Concatenate `a` then `b` with an equal-power crossfade over `overlap_samples` (report 06 §3.6). |
| [`fit_duration`](#foley.weave.mix.fit_duration)(clip, sample_rate, \*[, ...])         | Fit `clip` to `duration` seconds — seamless loop (beds) or trim/pass-through (report 06 §4).    |
| [`overlay`](#foley.weave.mix.overlay)(bus, clip, onset_samples)                  | Add `clip` into `bus` at `onset_samples` (report 06 §6.4 `overlay`).                            |
| [`reverb_send`](#foley.weave.mix.reverb_send)(clip, sample_rate, amount)             | Mix a pure-numpy exponential-decay reverb tail into `clip` (report 06 §3.5).                    |
| [`speech_duck_gain`](#foley.weave.mix.speech_duck_gain)(n_samples, sample_rate, ...)      | Build a (linear) gain envelope that dips to `duck_db` during speech spans (report 06 §3.2).     |
| [`time_stretch`](#foley.weave.mix.time_stretch)(clip, sample_rate, \*, rate)          | Pitch-preserving time-stretch by `rate` via `rubberband` (report 06 §4, optional).              |

### foley.weave.mix.DISTANCE_MAX_ATTEN_DB *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= -12.0*

Attenuation (dB) applied at maximum distance (distance == 1.0); ~inverse-distance.

### foley.weave.mix.DISTANCE_MAX_LP *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.85*

Air-absorption one-pole low-pass coefficient at maximum distance (0 = none, →1 = darkest).

### foley.weave.mix.LAYER_GAIN_DB *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[Layer](foley.base.html.md#foley.base.Layer), [float](https://docs.python.org/3/builtins/functions.html#float)]* *= {Layer.ambience: -21.0, Layer.music: -21.0, Layer.sfx_fg: -9.0, Layer.stinger: -6.0, Layer.voice: 0.0}*

Base per-layer gain (dB, relative to the voice bus at 0 dB). The render applies
this before each item’s own `processing.gain_db` so levels have a sane default.

### foley.weave.mix.REVERB_IR_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.18*

Reverb-send impulse-response length (seconds) and decay time-constant.

### foley.weave.mix.apply_distance(clip, sample_rate, distance)

Apply a distance recipe: attenuation + air-absorption low-pass (report 06 §3.4).

Distance reads as a *combination* of cues: quieter (~inverse-distance) and duller
(a low-pass, as air absorbs highs). The reverb component of distance is applied
separately via [`reverb_send()`](#foley.weave.mix.reverb_send). `distance == 0` is a no-op.

* **Parameters:**
  * **clip** (`ndarray`) – Working array (mono or stereo).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (kept for API symmetry / future filters).
  * **distance** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – 0 (near) .. 1 (far).
* **Return type:**
  `ndarray`
* **Returns:**
  The attenuated, low-passed clip (a new array; input not mutated).

### foley.weave.mix.attack_release_envelope(target, sample_rate, , attack=0.02, release=0.3, initial=1.0)

Smooth a piecewise-constant gain `target` with a one-pole attack/release follower.

The recurrence is `y[i] = t[i] + c·(y[i-1] - t[i])` with `c` the attack
coefficient while the gain falls (`t[i] < y[i-1]`) and the release one otherwise,
starting from `y[-1] = initial`. Within a run of equal targets the follower never
crosses the target, so `c` is fixed for the run and the recurrence has the closed
form `y = t + c**k·(y0 - t)`: each run is one vectorised numpy expression, and the
Python loop is over runs (a handful per speech span), not samples. It is built for
piecewise-constant targets (on/off gates): one numpy call per stretch means a
target that changes every sample is slower than a plain per-sample loop.

* **Parameters:**
  * **target** (`ndarray`) – `(n,)` gain the follower chases (linear; piecewise constant).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **attack** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Time constant (s) while the gain falls.
  * **release** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Time constant (s) while the gain rises.
  * **initial** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The follower’s value before the first sample.
* **Return type:**
  `ndarray`
* **Returns:**
  The smoothed `(n,)` float32 envelope (computed in float64).

```pycon
>>> env = attack_release_envelope([1.0, 0.0, 0.0], 1, attack=1.0)
>>> [round(float(g), 3) for g in env]
[1.0, 0.368, 0.135]
```

### foley.weave.mix.constant_power_pan(clip, pan)

Pan a (mono or stereo) clip to a stereo image with a constant-power law (report 06 §3.3).

`L = cos(θ)`, `R = sin(θ)` with `θ = (pan+1)·π/4` and `pan ∈ [-1, 1]`, so
`L² + R²` (perceived loudness) stays flat across the field — no ~3 dB centre dip.

* **Parameters:**
  * **clip** (`ndarray`) – Mono `(frames,)` or stereo `(frames, 2)` working array.
  * **pan** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – -1 (hard left) .. 0 (centre) .. +1 (hard right).
* **Return type:**
  `ndarray`
* **Returns:**
  A stereo `(frames, 2)` array.

### foley.weave.mix.convolution_reverb(clip, sample_rate, ir, , amount)

Convolution reverb with a real (recorded or synthesised) impulse response (report 06 §3.5).

The optional upgrade over [`reverb_send()`](#foley.weave.mix.reverb_send)’s synthetic exponential tail: convolves
`clip` with a supplied IR (a recorded room/plate, or one generated by
`pyroomacoustics`) via FFT — unity-gain-normalised, dry/wet-blended by `amount`,
and truncated to the clip length so the placement onset is unchanged. Pure-numpy (no
heavy dependency): only *producing* an IR needs an external tool; applying one does not.
`amount == 0` or an empty IR is a no-op (fully dry).

* **Parameters:**
  * **clip** (`ndarray`) – Working array (mono or stereo).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (kept for API symmetry).
  * **ir** (`ndarray`) – The impulse response (mono `(n,)` or stereo `(n, 2)`).
  * **amount** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – 0 (dry) .. 1 (fully wet).
* **Return type:**
  `ndarray`
* **Returns:**
  The dry/wet-blended clip (a new float32 array; input not mutated).

### foley.weave.mix.db_to_lin(db)

Convert decibels to a linear amplitude factor (`10 ** (db/20)`).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.weave.mix.declick(clip, sample_rate, , fade_in=0.008, fade_out=0.012)

Apply short in/out fades so an edit point produces no click (report 06 §3.6).

Thin wrapper over [`foley.audio.fade()`](foley.audio.html.md#foley.audio.fade) (linear ramps), sized in seconds.

* **Return type:**
  `ndarray`

### foley.weave.mix.equal_power_crossfade(a, b, overlap_samples)

Concatenate `a` then `b` with an equal-power crossfade over `overlap_samples` (report 06 §3.6).

The tail of `a` and head of `b` are ramped with `cos`/`sin` gains so
perceived loudness stays flat across the seam (no ~3 dB dip). Used for seamless
bed loops and ambience swaps.

* **Parameters:**
  * **a** (`ndarray`) – The leading clip (mono or stereo).
  * **b** (`ndarray`) – The trailing clip (same channel layout as `a`).
  * **overlap_samples** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Crossfade length in samples (clamped to both clip lengths).
* **Return type:**
  `ndarray`
* **Returns:**
  The crossfaded concatenation `(len(a) + len(b) - overlap,)` frames.

### foley.weave.mix.fit_duration(clip, sample_rate, , duration=None, loop=False, crossfade_s=0.05, stretch=False)

Fit `clip` to `duration` seconds — seamless loop (beds) or trim/pass-through (report 06 §4).

`duration is None` returns the clip unchanged (a one-shot plays once). When
`loop` and the clip is shorter than `duration`, it is tiled and equal-power
crossfaded at the seam to fill the span; anything longer than `duration` is
trimmed. A non-looping short clip is returned as-is (it plays once). When `stretch`,
the clip is pitch-preservingly time-stretched to exactly fill `duration` (via
[`time_stretch()`](#foley.weave.mix.time_stretch)), falling back to loop/trim if `rubberband` is unavailable.

* **Parameters:**
  * **clip** (`ndarray`) – Working array (mono or stereo).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **duration** ([`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Target duration in seconds (`None` = full clip length).
  * **loop** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Seamless-loop to fill `duration` when shorter.
  * **crossfade_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Equal-power crossfade length at each loop seam.
  * **stretch** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Pitch-preserving time-stretch to fill `duration` (needs `rubberband`).
* **Return type:**
  `ndarray`
* **Returns:**
  The duration-fitted clip.

### foley.weave.mix.overlay(bus, clip, onset_samples)

Add `clip` into `bus` at `onset_samples` (report 06 §6.4 `overlay`).

Sums (never replaces) into a copy of the bus; a clip whose tail would exceed the
bus length is truncated to fit (the mix length equals the narration length).

* **Parameters:**
  * **bus** (`ndarray`) – The destination layer bus (stereo `(frames, 2)`).
  * **clip** (`ndarray`) – The (mono or stereo) clip to place.
  * **onset_samples** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Start offset in samples (clamped at 0).
* **Return type:**
  `ndarray`
* **Returns:**
  A new bus with the clip summed in.

### foley.weave.mix.reverb_send(clip, sample_rate, amount)

Mix a pure-numpy exponential-decay reverb tail into `clip` (report 06 §3.5).

A deterministic dry/wet blend: the clip is convolved with a short
exponentially-decaying impulse response and mixed back at `amount`. This is the
zero-dependency default; `pyroomacoustics` / recorded-IR convolution is the
optional `foley[weave]` upgrade. `amount == 0` is a no-op (fully dry).

* **Parameters:**
  * **clip** (`ndarray`) – Working array (mono or stereo).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **amount** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – 0 (dry) .. 1 (fully wet).
* **Return type:**
  `ndarray`
* **Returns:**
  The dry/wet-blended clip (a new array; input not mutated).

### foley.weave.mix.speech_duck_gain(n_samples, sample_rate, speech_spans, , duck_db=-10.0, attack=0.02, release=0.3)

Build a (linear) gain envelope that dips to `duck_db` during speech spans (report 06 §3.2).

A one-pole attack/release smooths the transitions so the bed dips and recovers
without clicks. Deterministic and testable — the envelope-follower alternative to
`ffmpeg sidechaincompress`.

* **Parameters:**
  * **n_samples** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Length of the bed bus in samples.
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **speech_spans** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(start_s, end_s), ...]` from the word timeline.
  * **duck_db** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Attenuation depth during speech (negative dB).
  * **attack** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Attack time constant (seconds) as the bed drops.
  * **release** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Release time constant (seconds) as the bed recovers.
* **Return type:**
  `ndarray`
* **Returns:**
  A `(n_samples,)` linear gain envelope in `[db_to_lin(duck_db), 1.0]`.

### foley.weave.mix.time_stretch(clip, sample_rate, , rate)

Pitch-preserving time-stretch by `rate` via `rubberband` (report 06 §4, optional).

`rate > 1` shortens (plays faster), `< 1` lengthens — so fitting a clip of `n`
samples to a `target` span uses `rate = n / target`. Lazy: needs `pyrubberband`
(which shells out to the `rubberband` binary, a WEAVE system requirement); raises
[`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) when unavailable so callers (e.g. [`fit_duration()`](#foley.weave.mix.fit_duration)) fall back
to loop/trim. Preserves the channel layout.

* **Return type:**
  `ndarray`
