# foley.audio

Audio I/O and DSP primitives for foley.

The foundation every other foley layer decodes/encodes/transforms audio through.
It commits to a small, explicit set of representations (report 09):

> * **Working** (in RAM, between DSP ops): a `float32` NumPy array at
>   `48 kHz` — shape `(frames,)` mono or `(frames, channels)`. This is
>   the lingua franca of `soundfile`/`librosa`/`soxr` and exactly what
>   CLAP expects.
> * **Archive** (bytes at rest): **FLAC**, source sample-rate and bit-depth
>   preserved — lossless, ~40-60% smaller than WAV, self-describing.
> * **Delivery / preview** (derived): **Opus** by default (not implemented in
>   the foundation — an FFmpeg/`foley[ffmpeg]` concern surfaced later).

Design rules honoured here:

> * **Zero-dep import.** This module imports only the stdlib at top level; the
>   heavy libraries (`numpy`, `soundfile`, `soxr`, `librosa`,
>   `pyloudnorm`) are lazy-imported *inside* the functions that need them, so
>   `import foley.audio` always succeeds on a bare install and only the
>   function you call pays for (and requires) its dependency.
> * **No magic numbers.** Every default (sample rate, dtype, archive subtype,
>   resample quality, trim/fade/loudness targets) is a named module-level
>   constant used as a keyword-only argument default.
> * **Never bundle FFmpeg / pydub / torchaudio.** MP3/AAC/Opus transcode is an
>   optional external-tool concern, not part of this royalty-free core.

All ops assume the working representation (float array, time on axis 0). `load`
is the one function that produces it from arbitrary sources (path, raw bytes, or
a file-like object).

### Module Attributes

| [`AudioSource`](#foley.audio.AudioSource)   | a filesystem path, raw encoded bytes, or an already-open binary file-like object (e.g. `io.BytesIO`).   |
|----------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|

### Functions

| [`encode`](#foley.audio.encode)(samples, sample_rate, \*[, fmt, subtype])   | Encode `samples` fully in memory and return the container bytes.                     |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`ensure_channels`](#foley.audio.ensure_channels)(samples, \*, channels)             | Coerce `samples` to exactly `channels` channels.                                     |
| [`fade`](#foley.audio.fade)(samples, sample_rate, \*[, fade_in_s, ...])   | Apply in/out gain ramps to `samples` (a short declick by default).                   |
| [`limit_true_peak`](#foley.audio.limit_true_peak)(samples, sample_rate, \*[, ...])   | Attenuate `samples` so their inter-sample true peak sits at or below `ceiling_dbtp`. |
| [`load`](#foley.audio.load)(src, \*[, target_sr, mono, dtype])            | Decode audio into a float working array.                                             |
| [`loudness_normalize`](#foley.audio.loudness_normalize)(samples, sample_rate, \*)       | Loudness-normalize to `target_lufs`, then keep it peak-safe.                         |
| [`resample`](#foley.audio.resample)(samples, sample_rate, \*[, ...])          | Resample `samples` to `target_sr` (a no-op when already there).                      |
| [`save`](#foley.audio.save)(samples, sample_rate, dst, \*[, fmt, ...])    | Write `samples` to `dst` as `fmt`/`subtype` (default = FLAC archive).                |
| [`to_mono`](#foley.audio.to_mono)(samples)                                   | Down-mix to mono by averaging channels; 1-D input passes through.                    |
| [`to_working`](#foley.audio.to_working)(samples, sample_rate, \*[, mono, ...])  | Produce the canonical CLAP/QC working array from an arbitrary clip.                  |
| [`trim_silence`](#foley.audio.trim_silence)(samples, sample_rate, \*[, top_db])   | Strip leading/trailing silence, returning the clip and its kept span.                |

### foley.audio.AudioSource

a filesystem path, raw encoded bytes, or an
already-open binary file-like object (e.g. `io.BytesIO`).

* **Type:**
  A source `load` can decode

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)

### foley.audio.encode(samples, sample_rate, , fmt='flac', subtype='PCM_24')

Encode `samples` fully in memory and return the container bytes.

This is the producer for the content-addressed byte store: default output is
the FLAC archive form.

* **Parameters:**
  * **samples** (`ndarray`) – The working array to encode.
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Container/codec name (case-insensitive).
  * **subtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Sample subtype (e.g. `PCM_24`).
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
* **Returns:**
  The encoded audio as `bytes`.

Lazy dependency: `soundfile`.

### foley.audio.ensure_channels(samples, , channels)

Coerce `samples` to exactly `channels` channels.

Mappings: mono -> N by duplication; N -> mono by mean; N -> M (N != M, both
> 1) by collapsing to mono then tiling up to M.

* **Parameters:**
  * **samples** (`ndarray`) – Mono or multichannel working array.
  * **channels** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Target channel count (must be >= 1).
* **Return type:**
  `ndarray`
* **Returns:**
  A `(frames,)` array when `channels == 1`, else a
  `(frames, channels)` array.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `channels < 1`.

Lazy dependency: `numpy` (only for the up-mix / tile path).

### foley.audio.fade(samples, sample_rate, , fade_in_s=0.01, fade_out_s=0.01, kind='linear')

Apply in/out gain ramps to `samples` (a short declick by default).

Ramp lengths are clamped to at most `len(samples) // 2` so the in- and
out-ramps never overlap on tiny inputs.

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (converts the fade durations to samples).
  * **fade_in_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Fade-in duration in seconds.
  * **fade_out_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Fade-out duration in seconds.
  * **kind** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'linear'` or `'equal_power'` ramp shape.
* **Return type:**
  `ndarray`
* **Returns:**
  A new array with the fade envelope applied (input is not mutated).

Lazy dependency: `numpy`.

### foley.audio.limit_true_peak(samples, sample_rate, , ceiling_dbtp=-1.0, oversample=None)

Attenuate `samples` so their inter-sample true peak sits at or below `ceiling_dbtp`.

A **static** gain — the whole clip is turned down by one factor, never boosted —
which is transparent and exactly what a Tier-0 range fault needs: after it, a
flat-topped run or an over-ceiling peak is no longer at full scale. It is not a
dynamic look-ahead limiter (the shared leveler of foley#91 is), so the distortion
of a heavily clipped clip stays in the waveform; that is why [`foley.repair`](foley.repair.html.md#module-foley.repair)
applies it only to a clip just over the clipping gate.

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (passed to the true-peak measurement).
  * **ceiling_dbtp** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The true-peak ceiling in dBTP (default: foley’s -1 dBTP).
  * **oversample** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Oversampling factor for the true-peak estimate (default: the
    QC table’s `true_peak_oversample`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`float`](https://docs.python.org/3/builtins/functions.html#float)]
* **Returns:**
  `(attenuated, gain_db)`. `gain_db` is `0.0` — and `samples` comes back
  as is — when the clip is already under the ceiling or is silent.

Lazy dependency: `numpy` (via [`foley.qc.true_peak_dbtp()`](foley.qc.html.md#foley.qc.true_peak_dbtp)).

### foley.audio.load(src, , target_sr=None, mono=False, dtype='float32')

Decode audio into a float working array.

`src` may be a filesystem path, raw encoded `bytes` (wrapped in a
`BytesIO` so nothing touches disk), or any binary file-like object.

* **Parameters:**
  * **src** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – Path, raw bytes, or file-like object to decode.
  * **target_sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – If given, resample the decoded audio to this rate (via
    [`resample()`](#foley.audio.resample)); otherwise the native rate is returned.
  * **mono** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, down-mix multichannel audio to mono.
  * **dtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – NumPy dtype string for the returned array (default `float32`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)]
* **Returns:**
  A `(samples, sample_rate)` tuple. `samples` has shape `(frames,)`
  (mono) or `(frames, channels)`; `sample_rate` reflects any resample.

Lazy dependencies: `soundfile` (and `soxr` when `target_sr` differs).

### foley.audio.loudness_normalize(samples, sample_rate, , target_lufs=-16.0, peak_ceiling_dbfs=-1.0, min_block_s=0.4)

Loudness-normalize to `target_lufs`, then keep it peak-safe.

Integrated loudness is measured (ITU-R BS.1770-4 / EBU R128), the signal is
scaled to `target_lufs`, and finally attenuated so its sample peak sits at
or below `peak_ceiling_dbfs`. Two inputs are returned **unchanged** (flag
them, don’t amplify): near-silent input (measured loudness at or below
`LUFS_GATE_FLOOR`), and a clip shorter than one BS.1770 gating block
(`min_block_s`) — which `pyloudnorm` cannot measure and would otherwise
raise `ValueError` on (routine for one-shots: clicks, blips, gunshots).

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel, time on axis 0 — the layout
    pyloudnorm expects).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **target_lufs** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Desired integrated loudness (default = foley’s podcast
    target).
  * **peak_ceiling_dbfs** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Sample-peak ceiling (dBFS) applied after loudness
    normalization. Note this is a *sample*-peak limit, not an inter-sample
    true-peak (dBTP) limit — see [`foley.qc.true_peak_dbtp()`](foley.qc.html.md#foley.qc.true_peak_dbtp) for the
    oversampled measurement.
  * **min_block_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Minimum clip length (seconds) that can be loudness-measured;
    shorter clips are returned unchanged with `measured = -inf`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`float`](https://docs.python.org/3/builtins/functions.html#float)]
* **Returns:**
  `(normalized, measured_input_lufs)`. When the input is near-silent or
  too short to measure, `normalized` is the unchanged input and
  `measured_input_lufs` is at or below `LUFS_GATE_FLOOR` (`-inf` for
  the too-short case).

Lazy dependencies: `pyloudnorm` (+ `numpy`).

### foley.audio.resample(samples, sample_rate, , target_sr=48000, quality='HQ')

Resample `samples` to `target_sr` (a no-op when already there).

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono `(frames,)` or `(frames, channels)`).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The array’s current rate in Hz.
  * **target_sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Desired output rate in Hz (default = the working rate).
  * **quality** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – soxr quality preset (`QQ`/`LQ`/`MQ`/`HQ`/`VHQ`).
* **Return type:**
  `ndarray`
* **Returns:**
  The resampled array (the input unchanged when `sample_rate ==
  target_sr`). dtype is preserved by soxr.

Lazy dependency: `soxr`.

### foley.audio.save(samples, sample_rate, dst, , fmt='flac', subtype='PCM_24')

Write `samples` to `dst` as `fmt`/`subtype` (default = FLAC archive).

* **Parameters:**
  * **samples** (`ndarray`) – The working array to write (shape `(frames,)` or
    `(frames, channels)`).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **dst** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – Destination path or writable binary file-like object.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Container/codec name (case-insensitive; passed to libsndfile).
  * **subtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Sample subtype (e.g. `PCM_24`, `PCM_16`, `FLOAT`).
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

Lazy dependency: `soundfile`.

### foley.audio.to_mono(samples)

Down-mix to mono by averaging channels; 1-D input passes through.

* **Parameters:**
  **samples** (`ndarray`) – Mono `(frames,)` or multichannel `(frames, channels)` array.
* **Return type:**
  `ndarray`
* **Returns:**
  A 1-D mono array (dtype preserved).

### foley.audio.to_working(samples, sample_rate, , mono=True, target_sr=48000, dtype='float32')

Produce the canonical CLAP/QC working array from an arbitrary clip.

Down-mixes (when `mono`), resamples to `target_sr`, and casts to
`dtype` — the `float32` @ 48 kHz mono array every embedder/tagger/QC
check consumes.

* **Parameters:**
  * **samples** (`ndarray`) – Decoded working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The array’s current rate in Hz.
  * **mono** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, down-mix to mono.
  * **target_sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Working sample rate in Hz.
  * **dtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Output NumPy dtype string.
* **Return type:**
  `ndarray`
* **Returns:**
  The canonical working array.

Lazy dependency: `soxr` (only when `sample_rate != target_sr`).

### foley.audio.trim_silence(samples, sample_rate, , top_db=30.0)

Strip leading/trailing silence, returning the clip and its kept span.

Silence detection runs on a transient mono down-mix (so librosa’s time-last
convention never clashes with foley’s time-first `(frames, channels)`
layout); the returned sample indices then slice the *original* array along
axis 0, preserving its channel layout.

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (kept in the signature for API symmetry;
    trimming is index-based).
  * **top_db** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – A frame is silent when it sits at least this many dB below the
    reference (peak) level.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]
* **Returns:**
  `(trimmed, (start_sample, end_sample))`. On all-silent (or otherwise
  degenerate) input the original array is returned unchanged with a
  full-length span `(0, len(samples))`.

Lazy dependency: `librosa`.
