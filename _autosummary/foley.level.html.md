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
[`Layer`](foley.base.html.md#foley.base.Layer), or a LUFS number). It does not by default: the WEAVE
render applies the layer gains itself to the clip as stored, so a library clip
levelled to its class target would be attenuated twice. Levelling exported clips for
listening, or a library weave normalises by measured loudness, are the uses.

Zero-dependency import: `numpy`, `pyloudnorm` and `soundfile` load inside the
functions.

### Module Attributes

| [`LevelSpec`](#foley.level.LevelSpec)   | a layer (or its name) for its class target, or a LUFS value.   |
|--------------------------------------------------------------|----------------------------------------------------------------|

### Functions

| [`class_target_lufs`](#foley.level.class_target_lufs)(layer)         | The integrated-loudness target (LUFS) for a clip of `layer`.                                                                         |
|-----------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`level_bytes`](#foley.level.level_bytes)(audio_bytes, target) | Scale an encoded clip to `target` loudness; return `(bytes, applied, measured)`.                                                     |
| [`require_loudness_meter`](#foley.level.require_loudness_meter)()         | Raise `ImportError` (with the install line) when `pyloudnorm` is missing.                                                            |
| [`resolve_target_lufs`](#foley.level.resolve_target_lufs)(spec)        | A `level=` value as a LUFS target: a number as is, a layer via [`class_target_lufs()`](#foley.level.class_target_lufs). |

### foley.level.LevelSpec

a layer (or its name) for its class target, or a LUFS value.

* **Type:**
  What `level=` accepts

alias of [`Layer`](foley.base.html.md#foley.base.Layer) | [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`int`](https://docs.python.org/3/builtins/functions.html#int)

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

### foley.level.level_bytes(audio_bytes, target)

Scale an encoded clip to `target` loudness; return `(bytes, applied, measured)`.

* **Parameters:**
  * **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – Any clip `soundfile` decodes.
  * **target** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`Layer`](foley.base.html.md#foley.base.Layer), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int)]) – A layer (its class target) or a LUFS number (see [`resolve_target_lufs()`](#foley.level.resolve_target_lufs)).
* **Returns:**
  the levelled clip re-encoded in foley’s FLAC
  archive form and a one-line account of the gain applied (for the licence’s
  `transformations`); or, for a clip too short or too quiet to measure, the
  bytes unchanged, `applied=None` and `measured_lufs=None`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]

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
