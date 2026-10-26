# foley.level

Level a clip to a stated loudness target for its class, so relative levels are sane.

A generated clip comes out at whatever level its model likes: Stable Audio 3 peaks near
-20 dBFS, ElevenLabs much hotter, so two sounds meant to sit side by side differ by
10 dB or more before anyone touches a fader. [`level_bytes()`](#foley.level.level_bytes) measures a clip’s
integrated loudness (ITU-R BS.1770-4) and scales it to the target for its class,
then keeps the sample peak under foley’s ceiling.

The class targets are not new numbers. They are the dialogue-relative layer gains the
WEAVE mixer already uses ([`foley.weave.mix.LAYER_GAIN_DB`](foley.weave.mix.html.md#foley.weave.mix.LAYER_GAIN_DB): a one-shot sits
9 dB under the voice, an ambience bed 21 dB under) applied to a voice at the
reference programme loudness (`foley.audio.DEFAULT_LOUDNESS_TARGET_LUFS`,
-16 LUFS). So a levelled one-shot is at -25 LUFS and a levelled bed at -37 LUFS:
what they would be under a voice at -16 LUFS, and how they should sound side by side.

Two cases are left unchanged and said so, never amplified: a clip too short to
measure (under one 400 ms gating block: a click, a page flick) and a near-silent one.

[`foley.generate()`](foley.html.md#foley.generate) levels a clip when asked (`level='sfx_fg'`, a
[`Layer`](foley.base.html.md#foley.base.Layer), or a LUFS number), for export and listening. It does not by
default: the library keeps clips as generated, and the WEAVE render brings every clip to
the reference loudness itself (below), so a stored clip’s level does not matter to the mix.

**The WEAVE render levels by measurement** ([`reference_gain_db()`](#foley.level.reference_gain_db), used by
[`foley.weave.render.FullRender`](foley.weave.html.md#foley.weave.FullRender)): each clip is first brought to the reference
loudness, then the layer gain is applied, so a hot ElevenLabs clip and a quiet Stable
Audio one land at the same place in the mix and `generate(level=...)` stays an export
tool. A clip too short for a loudness reading is levelled by its peak instead.

Zero-dependency import: `numpy`, `pyloudnorm` and `soundfile` load inside the
functions.

### Module Attributes

| [`LevelSpec`](#foley.level.LevelSpec)                   | a layer (or its name) for its class target, or a LUFS value.                                                             |
|------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| [`REFERENCE_PEAK_CEILING_DBFS`](#foley.level.REFERENCE_PEAK_CEILING_DBFS) | Sample-peak ceiling (dBFS) the levelled clip must stay under.                                                            |
| [`SHORT_CLIP_PEAK_DBFS`](#foley.level.SHORT_CLIP_PEAK_DBFS)        | Where a clip too short for a loudness reading (a click, a page flick) puts its sample peak.                              |
| [`MAX_REFERENCE_BOOST_DB`](#foley.level.MAX_REFERENCE_BOOST_DB)      | The most a clip is boosted to reach the reference (dB), so a near-silent clip's noise floor is not raised without bound. |

### Functions

| [`class_target_lufs`](#foley.level.class_target_lufs)(layer)                        | The integrated-loudness target (LUFS) for a clip of `layer`.                                                                         |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`level_bytes`](#foley.level.level_bytes)(audio_bytes, target, \*[, meter])   | Scale an encoded clip to `target` loudness; return `(bytes, applied, measured)`.                                                     |
| [`reference_gain_db`](#foley.level.reference_gain_db)(clip, sample_rate, \*[, ...]) | The gain (dB) that brings `clip` to the reference loudness; `0.0` if it cannot.                                                      |
| [`require_loudness_meter`](#foley.level.require_loudness_meter)()                        | Raise `ImportError` (with the install line) when `pyloudnorm` is missing.                                                            |
| [`resolve_target_lufs`](#foley.level.resolve_target_lufs)(spec)                       | A `level=` value as a LUFS target: a number as is, a layer via [`class_target_lufs()`](#foley.level.class_target_lufs). |

### foley.level.LevelSpec

a layer (or its name) for its class target, or a LUFS value.

* **Type:**
  What `level=` accepts

alias of [`Layer`](foley.base.html.md#foley.base.Layer) | [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.level.MAX_REFERENCE_BOOST_DB *= 36.0*

The most a clip is boosted to reach the reference (dB), so a near-silent clip’s noise
floor is not raised without bound. The 29 dB spread seen on a real film fits inside.

### foley.level.REFERENCE_PEAK_CEILING_DBFS *= -1.0*

Sample-peak ceiling (dBFS) the levelled clip must stay under. The render passes this
*after* the layer gain (see [`foley.weave.render.FullRender`](foley.weave.html.md#foley.weave.FullRender)), so a loud transient
is not held back by headroom the layer gain is about to take anyway.

### foley.level.SHORT_CLIP_PEAK_DBFS *= -6.0*

Where a clip too short for a loudness reading (a click, a page flick) puts its sample
peak. Provisional: the peak a typical one-shot has when its integrated loudness is the
reference (about 10 dB of crest above -16 LUFS).

### foley.level.class_target_lufs(layer)

The integrated-loudness target (LUFS) for a clip of `layer`.

The reference voice loudness plus the layer’s dialogue-relative gain (see the
module docstring), so it moves with both SSOTs.

```pycon
>>> class_target_lufs("sfx_fg")
-25.0
>>> class_target_lufs(Layer.ambience)
-37.0
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.level.level_bytes(audio_bytes, target, , meter=None)

Scale an encoded clip to `target` loudness; return `(bytes, applied, measured)`.

* **Parameters:**
  * **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – Any clip `soundfile` decodes.
  * **target** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`Layer`](foley.base.html.md#foley.base.Layer), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int)]) – A layer (its class target) or a LUFS number (see [`resolve_target_lufs()`](#foley.level.resolve_target_lufs)).
  * **meter** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[ndarray, [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – A [`foley.audio.Meter`](foley.audio.html.md#foley.audio.Meter) (default `pyloudnorm`).
* **Returns:**
  the levelled clip re-encoded in foley’s FLAC
  archive form and a one-line account of the gain applied (for the licence’s
  `transformations`); or, for a clip too short or too quiet to measure, the
  bytes unchanged, `applied=None` and `measured_lufs=None`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### foley.level.reference_gain_db(clip, sample_rate, , reference_lufs=None, peak_ceiling_dbfs=-1.0, short_peak_dbfs=-6.0, max_boost_db=36.0, meter=None)

The gain (dB) that brings `clip` to the reference loudness; `0.0` if it cannot.

Integrated loudness (BS.1770, gated) is measured and the gain is
`reference_lufs - measured`. A clip too short to measure is levelled by
its sample peak (to `short_peak_dbfs`) instead; one that is long enough but below the
loudness gate is near-silent and left alone. Either way the gain is capped so the
clip’s sample peak stays at or under `peak_ceiling_dbfs` and the boost at
`max_boost_db`; a silent or non-finite clip gets `0.0`. Pure and deterministic.

* **Parameters:**
  * **clip** – Mono or multichannel samples, time on axis 0.
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **reference_lufs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – The loudness every clip is brought to (default: foley’s
    reference programme loudness, `foley.audio.DEFAULT_LOUDNESS_TARGET_LUFS`).
  * **meter** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[ndarray, [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – A [`foley.audio.Meter`](foley.audio.html.md#foley.audio.Meter) (default `pyloudnorm`).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.level.require_loudness_meter()

Raise `ImportError` (with the install line) when `pyloudnorm` is missing.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.level.resolve_target_lufs(spec)

A `level=` value as a LUFS target: a number as is, a layer via [`class_target_lufs()`](#foley.level.class_target_lufs).

```pycon
>>> resolve_target_lufs(-30)
-30.0
>>> resolve_target_lufs("stinger")
-22.0
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
