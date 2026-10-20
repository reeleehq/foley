# foley.qc

Tier-0 deterministic audio QC for foley (research report 08 §3).

Pure, per-clip range-checks over a floating-point waveform in `[-1, 1]`:
clipping, true-peak, DC offset, whole-clip silence, SNR, edge clicks, loudness
(LUFS), duration, and `NaN`/`Inf` sanity. Every threshold is an explicit
[`QCThresholds`](#foley.qc.QCThresholds) field — there are **no inline policy literals** — so the
whole table is a single, overridable source of truth.

Zero-dependency import contract:
: This module imports **stdlib only** at the top level. `numpy` is
  lazy-imported inside each function body (like `foley.audio`), so
  `import foley.qc` succeeds on a bare install with no scientific stack.
  [`measure_lufs()`](#foley.qc.measure_lufs) additionally lazy-imports `pyloudnorm` and returns
  `None` when it (or a measurable clip) is absent; everything else is
  numpy-only.

Waveform convention:
: `samples` is a float array shaped `(frames,)` (mono) or
  `(frames, channels)`. dBFS is `20·log10(|x|)` with full scale at 1.0.

Typical use (at ingest, a later phase):

```default
report = run_qc(working_array, sample_rate)
sound_record.qc = report.to_dict()   # becomes filterable metadata
```

### Module Attributes

| [`LUFS_MIN_BLOCK_S`](#foley.qc.LUFS_MIN_BLOCK_S)      | BS.1770 integrated-loudness gating block = 400 ms; a clip shorter than one block cannot be measured (`pyloudnorm` raises), so [`measure_lufs()`](#foley.qc.measure_lufs) returns `None` for it.                          |
|------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`QC_STATUS_RANK`](#foley.qc.QC_STATUS_RANK)        | the SSOT for "is this clip below the floor?" — [`is_below()`](#foley.qc.is_below), the ingest gate's `min_status` and [`foley.repair`](foley.repair.html.md#module-foley.repair) all read it. |
| [`DEFAULT_MIN_STATUS`](#foley.qc.DEFAULT_MIN_STATUS)    | `warn` clips are stored (their notes travel with the record); only `fail` clips are quarantined.                                                                                                                                              |
| [`DEFAULT_QC_THRESHOLDS`](#foley.qc.DEFAULT_QC_THRESHOLDS) | The shipped default thresholds; the default for every keyword below.                                                                                                                                                                          |

### Functions

| [`dc_offset`](#foley.qc.dc_offset)(samples)                              | Largest per-channel absolute DC offset, `max_c |mean_n x[n, c]|`.                                                                                                              |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`detect_clipping`](#foley.qc.detect_clipping)(samples, \*[, full_scale, ...]) | Detect hard (flat-topped) clipping.                                                                                                                                            |
| [`duration_s`](#foley.qc.duration_s)(samples, sample_rate)                | Clip duration in seconds: `frames / sample_rate`.                                                                                                                              |
| [`estimate_snr`](#foley.qc.estimate_snr)(samples, sample_rate, \*[, ...])   | Estimate SNR in dB (advisory — a busy-street SFX legitimately scores low).                                                                                                     |
| [`has_nan_inf`](#foley.qc.has_nan_inf)(samples)                            | Return `True` if any sample is `NaN` or `Inf` (corrupt-clip guard).                                                                                                            |
| [`is_below`](#foley.qc.is_below)(status[, min_status])                  | True when `status` is worse than the admission floor `min_status`.                                                                                                             |
| [`is_silent`](#foley.qc.is_silent)(samples, \*[, rms_floor_dbfs])        | Return `True` when whole-clip RMS falls below `rms_floor_dbfs`.                                                                                                                |
| [`measure_lufs`](#foley.qc.measure_lufs)(samples, sample_rate, \*[, ...])   | Integrated loudness (LUFS, ITU-R BS.1770-4) via `pyloudnorm` (lazy).                                                                                                           |
| [`needs_edge_fade`](#foley.qc.needs_edge_fade)(samples, \*[, rel_peak_dbfs])   | Return `True` when the first or last sample sits above `rel_peak_dbfs` relative to the clip peak — i.e. a nonzero boundary that clicks under narration and needs a short fade. |
| [`run_qc`](#foley.qc.run_qc)(samples, sample_rate, \*[, thresholds])  | Run every Tier-0 check and fold the results into a [`QCReport`](#foley.qc.QCReport).                                                                  |
| [`true_peak_dbtp`](#foley.qc.true_peak_dbtp)(samples, sample_rate, \*[, ...]) | Inter-sample true-peak level in dBTP.                                                                                                                                          |

### Classes

| [`QCReport`](#foley.qc.QCReport)(duration_s, sample_rate, channels, ...)   | Per-clip Tier-0 QC result.                                           |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| [`QCStatus`](#foley.qc.QCStatus)(\*values)                                 | Overall verdict for a clip (subclasses `str` so it is JSON-safe).    |
| [`QCThresholds`](#foley.qc.QCThresholds)([clip_full_scale, ...])               | All Tier-0 QC defaults (report 08 §3 table), each an explicit field. |

### foley.qc.DEFAULT_MIN_STATUS *: [QCStatus](#foley.qc.QCStatus)* *= QCStatus.warn*

`warn` clips are
stored (their notes travel with the record); only `fail` clips are quarantined.

* **Type:**
  The admission floor foley’s ingest uses unless told otherwise

### foley.qc.DEFAULT_QC_THRESHOLDS *= QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100)*

The shipped default thresholds; the default for every keyword below.

### foley.qc.LUFS_MIN_BLOCK_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.4*

BS.1770 integrated-loudness gating block = 400 ms; a clip shorter than one
block cannot be measured (`pyloudnorm` raises), so [`measure_lufs()`](#foley.qc.measure_lufs)
returns `None` for it. This is a fixed property of the algorithm, not a
tunable QC policy threshold, hence a module constant rather than a field.

### *class* foley.qc.QCReport(duration_s, sample_rate, channels, clipped_ratio, clipped_max_run, dc_offset, rms_dbfs, is_silent, needs_edge_fade, has_nan_inf, true_peak_dbtp=None, snr_db=None, loudness_lufs=None, status=QCStatus.pass_, notes=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Per-clip Tier-0 QC result.

Mirrors the fields the `SoundRecord` schema already carries
(`duration_s`, `sample_rate`, `channels`, `loudness_lufs`) plus the
deterministic check outputs, an overall `status`, and human-readable
`notes` for every firing condition. Serialize with [`to_dict()`](#foley.qc.QCReport.to_dict) into
`SoundRecord.qc`.

#### to_dict()

Return a plain, JSON-safe dict (`status` as its string value).

Non-finite floats are swept to `None` at this boundary too (belt-and-
suspenders over the construction-time `_json_safe()` guard) so no
`Infinity`/`NaN` can ever reach `json.dumps` regardless of who set a
field.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.qc.QCStatus(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Overall verdict for a clip (subclasses `str` so it is JSON-safe).

### *class* foley.qc.QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

All Tier-0 QC defaults (report 08 §3 table), each an explicit field.

Grouped by check. Pass a customized instance to [`run_qc()`](#foley.qc.run_qc) (or the
per-check keyword arguments) to override any threshold without editing code.

### foley.qc.QC_STATUS_RANK *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)* *= {'fail': 0, 'pass': 2, 'warn': 1}*

the SSOT for
“is this clip below the floor?” — [`is_below()`](#foley.qc.is_below), the ingest gate’s `min_status`
and [`foley.repair`](foley.repair.html.md#module-foley.repair) all read it.

* **Type:**
  Admission ordering of [`QCStatus`](#foley.qc.QCStatus) values (worse -> better)

### foley.qc.dc_offset(samples)

Largest per-channel absolute DC offset, `max_c |mean_n x[n, c]|`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.qc.detect_clipping(samples, , full_scale=0.999, min_run=3)

Detect hard (flat-topped) clipping.

A frame is “hot” when any channel reaches `|x| >= full_scale`. Only
maximal hot runs of length `>= min_run` count as clip events.

* **Parameters:**
  * **samples** (`ndarray`) – Waveform in `[-1, 1]`.
  * **full_scale** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Absolute level at/above which a sample is full-scale.
  * **min_run** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Minimum consecutive full-scale frames to count as clipping.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int)]
* **Returns:**
  `(clipped_ratio, max_run_length)` — the fraction of frames inside
  counting runs, and the longest counting run (`(0.0, 0)` if none).

### foley.qc.duration_s(samples, sample_rate)

Clip duration in seconds: `frames / sample_rate`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.qc.estimate_snr(samples, sample_rate, , quiet_percentile=10.0, frame_s=0.025, hop_s=0.01)

Estimate SNR in dB (advisory — a busy-street SFX legitimately scores low).

The noise floor is the mean short-time RMS of the quietest
`quiet_percentile` percent of frames; the signal level is the whole-clip
RMS. A near-noise-free clip (quiet frames -> ~0) yields a very high value;
an exactly-zero floor returns `inf` and a silent clip returns `-inf`.

* **Parameters:**
  * **samples** (`ndarray`) – Waveform in `[-1, 1]` (down-mixed to mono internally).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (sizes the frames).
  * **quiet_percentile** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Percent of quietest frames forming the noise floor.
  * **frame_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Short-time frame length in seconds.
  * **hop_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Hop between frames in seconds.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  SNR in dB.

### foley.qc.has_nan_inf(samples)

Return `True` if any sample is `NaN` or `Inf` (corrupt-clip guard).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.qc.is_below(status, min_status=QCStatus.warn)

True when `status` is worse than the admission floor `min_status`.

Accepts [`QCStatus`](#foley.qc.QCStatus) members or their string values; an unknown value ranks
as `fail` (fail-closed).

```pycon
>>> is_below(QCStatus.fail, QCStatus.warn), is_below("warn", "warn")
(True, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.qc.is_silent(samples, , rms_floor_dbfs=-60.0)

Return `True` when whole-clip RMS falls below `rms_floor_dbfs`.

A zero (exactly silent) clip has RMS `0` -> `-inf` dBFS -> `True`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.qc.measure_lufs(samples, sample_rate, , gate_floor_lufs=-70.0, min_block_s=0.4)

Integrated loudness (LUFS, ITU-R BS.1770-4) via `pyloudnorm` (lazy).

Returns `None` when `pyloudnorm` is unavailable, the clip is shorter than
one gating block (`min_block_s`), the samples are non-finite, or the
measured loudness is at/below the gate floor (near-silent / unstable — do
not amplify, just flag).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.qc.needs_edge_fade(samples, , rel_peak_dbfs=-40.0)

Return `True` when the first or last sample sits above `rel_peak_dbfs`
relative to the clip peak — i.e. a nonzero boundary that clicks under
narration and needs a short fade.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.qc.run_qc(samples, sample_rate, , thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100))

Run every Tier-0 check and fold the results into a [`QCReport`](#foley.qc.QCReport).

Status rules (evaluated in order):
: FAIL if `has_nan_inf` OR `is_silent` OR
  `clipped_max_run >= clip_reject_run` OR
  `clipped_ratio > clip_reject_ratio` OR `duration_s < duration_min_s`.
  WARN if `dc_offset > dc_offset_fail` OR `needs_edge_fade` OR
  (`snr_db` is a finite value `< snr_clean_db`) OR
  (`true_peak_dbtp` is a finite value `> true_peak_max_dbtp`).
  Otherwise PASS.

Each firing condition appends a human-readable string to `notes`. Two
thresholds are intentionally NOT evaluated on a single source clip here
because they belong to later stages: the library-median loudness-outlier
check (`+/- lufs_outlier_lu`, a library-level concern) and the delivery
sample-rate target (`deliver_min_sample_rate`, enforced at the weave/master
stage).

* **Parameters:**
  * **samples** (`ndarray`) – Waveform in `[-1, 1]` (mono or `(frames, channels)`).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **thresholds** ([`QCThresholds`](#foley.qc.QCThresholds)) – Overridable QC thresholds (defaults to shipped values).
* **Return type:**
  [`QCReport`](#foley.qc.QCReport)
* **Returns:**
  A populated [`QCReport`](#foley.qc.QCReport).

### foley.qc.true_peak_dbtp(samples, sample_rate, , oversample=4)

Inter-sample true-peak level in dBTP.

Each channel is band-limited-upsampled `oversample``x (numpy FFT), the
peak magnitude is taken across all channels, and converted to dBTP. Returns
``-inf` for a fully silent clip. `sample_rate` is accepted for interface
symmetry (FFT interpolation is rate-independent).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
