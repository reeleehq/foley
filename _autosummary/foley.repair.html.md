# foley.repair

Repair instead of quarantine: the fixes a Tier-0 QC report suggests, applied and re-checked (#107).

A paid generation (or any clip) that [`foley.qc.run_qc()`](foley.qc.html.md#foley.qc.run_qc) would quarantine for a
*trivially repairable* fault — a clipped run just over the gate, which usually rides
with an edge click and a true peak over the ceiling — is worth a 20 ms fade and a
true-peak attenuation more than it is worth the bin: the bytes were paid for.
[`repair()`](#foley.repair.repair) applies exactly the fixes the report names, with foley’s own numpy
primitives ([`foley.audio.fade()`](foley.audio.html.md#foley.audio.fade), [`foley.audio.limit_true_peak()`](foley.audio.html.md#foley.audio.limit_true_peak)), runs QC
again on the result the way ingest will ([`foley.audio.to_working()`](foley.audio.html.md#foley.audio.to_working) then
[`foley.qc.run_qc()`](foley.qc.html.md#foley.qc.run_qc)), and says what it did. What it cannot fix it leaves alone,
and says why ([`unrepairable()`](#foley.repair.unrepairable)): NaN/Inf, silence, a too-short clip, or clipping
heavy enough to be distortion — a flat top longer than about a millisecond, or more
than a tenth of a percent of the clip — rather than a run just over the gate.

Only clipping quarantines a clip (an edge click and an over-ceiling peak are warnings,
admitted), so by default the policy acts only on a clip QC would refuse; the fade and
the attenuation then also clear the warnings it carries. To declick and attenuate
clips QC admits with a warning too, lower the trigger:
`functools.partial(repair, min_status=QCStatus.pass_)`.

[`foley.generate()`](foley.html.md#foley.generate) runs this by default (`repair=True`); `repair=False` keeps
the quarantine, and a callable with [`repair()`](#foley.repair.repair)’s signature replaces the policy (an
ffmpeg `afade` + `alimiter` repair, say). [`repair_bytes()`](#foley.repair.repair_bytes) is the same policy
over encoded bytes — what `generate` calls, and the route for bytes a quarantine
kept (`foley.generations.get(key)`). Every repair is recorded on the candidate’s
`notes` and in the licence’s `transformations`, so the credit reads “(modified)”
and the content credential carries an edit action.

Zero-dependency import: stdlib only at the top level; `numpy` (and `soxr` when the
clip is not at the working rate, `soundfile` for [`repair_bytes()`](#foley.repair.repair_bytes)) load inside
the functions.

### Module Attributes

| [`DEFAULT_REPAIR_FADE_S`](#foley.repair.DEFAULT_REPAIR_FADE_S)            | 20 ms, the upper end of the 10-20 ms the QC note asks for (the Tier-0 `edge_fade_s` floor is 10 ms).                                                                                                                                                             |
|-----------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DEFAULT_REPAIR_CEILING_DBTP`](#foley.repair.DEFAULT_REPAIR_CEILING_DBTP)      | 0.5 dB under foley's -1 dBTP ceiling, so the re-check never sits on the threshold (the production's ffmpeg repair used `alimiter=limit=0.85`, about -1.4 dB).                                                                                                    |
| [`DEFAULT_REPAIR_MAX_CLIPPED_RATIO`](#foley.repair.DEFAULT_REPAIR_MAX_CLIPPED_RATIO) | ten times the reject gate (`QCThresholds.clip_reject_ratio`, 0.01 %).                                                                                                                                                                                            |
| [`DEFAULT_REPAIR_MAX_CLIPPED_RUN`](#foley.repair.DEFAULT_REPAIR_MAX_CLIPPED_RUN)   | The longest single flat top still treated as repairable, in samples at the working rate: five times the reject run (`QCThresholds.clip_reject_run`, 10), about a millisecond.                                                                                    |
| [`FIX_FADE`](#foley.repair.FIX_FADE)                         | The fix names [`suggested_fixes()`](#foley.repair.suggested_fixes) can return, in the order [`repair()`](#foley.repair.repair) applies them (the fade first: an edge sample can be the peak the attenuation then measures). |

### Functions

| [`repair`](#foley.repair.repair)(samples, sample_rate, \*[, report, ...])   | Apply the fixes `report` suggests to `samples` and QC the result again.                                                                                                     |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`repair_bytes`](#foley.repair.repair_bytes)(audio_bytes, \*[, policy, ...])      | [`repair()`](#foley.repair.repair) over an encoded clip: decode, QC, apply `policy`, re-encode if it cleared.                                        |
| [`suggested_fixes`](#foley.repair.suggested_fixes)(report, \*[, thresholds])         | The fixes `report` calls for: [`FIX_FADE`](#foley.repair.FIX_FADE) (an edge click) and/or `FIX_LIMIT` (a clip event, or a true peak over the ceiling). |
| [`unrepairable`](#foley.repair.unrepairable)(report, \*[, thresholds, ...])       | Why `report`'s faults are beyond a Tier-0 repair — `None` when they are not.                                                                                                |

### Classes

| [`RepairResult`](#foley.repair.RepairResult)(samples, sample_rate, before[, ...])   | What [`repair()`](#foley.repair.repair) did to a clip.   |
|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|

### foley.repair.DEFAULT_REPAIR_CEILING_DBTP *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= -1.5*

0.5 dB under foley’s -1 dBTP ceiling, so the
re-check never sits on the threshold (the production’s ffmpeg repair used
`alimiter=limit=0.85`, about -1.4 dB).

* **Type:**
  Where the true-peak attenuation lands

### foley.repair.DEFAULT_REPAIR_FADE_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.02*

20 ms, the upper end of the 10-20 ms the
QC note asks for (the Tier-0 `edge_fade_s` floor is 10 ms).

* **Type:**
  The declick fade applied to an edge click

### foley.repair.DEFAULT_REPAIR_MAX_CLIPPED_RATIO *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.001*

ten times the
reject gate (`QCThresholds.clip_reject_ratio`, 0.01 %). Attenuating such a clip
would make it pass the range check while its flat tops stay audible, so it is left
to the quarantine (regenerate instead).

* **Type:**
  A clipped ratio above this is distortion, not “just over the gate”

### foley.repair.DEFAULT_REPAIR_MAX_CLIPPED_RUN *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 50*

The longest single flat top still treated as repairable, in samples at the working
rate: five times the reject run (`QCThresholds.clip_reject_run`, 10), about a
millisecond. The ratio bound scales with the clip’s length, so a long clip could
otherwise hide a long plateau under it; this one does not.

### foley.repair.FIX_FADE *= 'fade'*

The fix names [`suggested_fixes()`](#foley.repair.suggested_fixes) can return, in the order [`repair()`](#foley.repair.repair) applies
them (the fade first: an edge sample can be the peak the attenuation then measures).

### *class* foley.repair.RepairResult(samples, sample_rate, before, after=None, applied=list(), reason=None, min_status=QCStatus.warn)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What [`repair()`](#foley.repair.repair) did to a clip.

`samples` is the (possibly) repaired clip at `sample_rate`; `applied` names
each fix in the order applied (empty when nothing was done — `reason` says why);
`before` is the QC report the decision was made on and `after` the re-check
(`None` when nothing was applied).

#### cleared(admit=QCStatus.warn)

True when the clip, as it now stands, meets the admission floor `admit`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### note(admit=QCStatus.warn)

One line for a result’s notes: what was done, or why nothing was.

`None` when there was nothing to do (the clip met `admit` and the policy
left it alone) — the common case says nothing.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### *property* repaired *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when at least one fix was applied.

#### *property* report *: [QCReport](foley.qc.html.md#foley.qc.QCReport)*

The QC report of the clip as it now stands (`after` when repaired).

### foley.repair.repair(samples, sample_rate, , report=None, thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100), min_status=QCStatus.warn, fade_s=0.02, ceiling_dbtp=-1.5, max_clipped_ratio=0.001, max_clipped_run=50)

Apply the fixes `report` suggests to `samples` and QC the result again.

Acts only on a clip whose status is below `min_status` — by default ingest’s
admission floor, so only a clip that would be quarantined (clipping) — and whose
faults a fade and an attenuation can fix ([`unrepairable()`](#foley.repair.unrepairable)); otherwise the
clip comes back untouched with `reason` set. Fixes, in order: a `fade_s`
in/out declick when the report flags an edge click; a static true-peak
attenuation to `ceiling_dbtp` when it flags a clip event or an over-ceiling
peak. The re-check runs on the working array exactly as ingest does, so what
clears here clears there.

* **Parameters:**
  * **samples** (`ndarray`) – The clip to repair — the native-rate decoded array (mono or
    `(frames, channels)`), so what is stored afterwards is the repaired clip.
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Its rate in Hz.
  * **report** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`QCReport`](foley.qc.html.md#foley.qc.QCReport)]) – The clip’s QC report (default: computed here on the working array).
  * **thresholds** ([`QCThresholds`](foley.qc.html.md#foley.qc.QCThresholds)) – The QC thresholds (default: the shipped table).
  * **min_status** ([`QCStatus`](foley.qc.html.md#foley.qc.QCStatus)) – Act on a clip whose status is below this (default: ingest’s
    admission floor, `warn`: only a clip that would be quarantined;
    `QCStatus.pass_` also declicks/attenuates clips admitted with a warning).
  * **fade_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Declick fade length in seconds.
  * **ceiling_dbtp** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The true-peak ceiling the attenuation lands at.
  * **max_clipped_ratio** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The most clipping still treated as repairable.
  * **max_clipped_run** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The longest flat top (working-rate samples) still repairable.
* **Return type:**
  [`RepairResult`](#foley.repair.RepairResult)
* **Returns:**
  A [`RepairResult`](#foley.repair.RepairResult).

Lazy dependencies: `numpy`; `soxr` when `sample_rate` is not the working rate.

### foley.repair.repair_bytes(audio_bytes, , policy=True, admit=QCStatus.warn, thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100))

[`repair()`](#foley.repair.repair) over an encoded clip: decode, QC, apply `policy`, re-encode if it cleared.

What [`foley.generate()`](foley.html.md#foley.generate) calls on a fresh generation, and the route for bytes a
quarantine kept: `raw = foley.generations.get(key); fixed, result =
foley.repair.repair_bytes(raw)`. The QC pass here is the one ingest runs (the
working array, the same thresholds), so a clip the gate admits as is costs one
decode and nothing else.

* **Parameters:**
  * **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – Any clip `soundfile` decodes (the provider’s WAV/MP3/FLAC).
  * **policy** – `True` for [`repair()`](#foley.repair.repair) with its defaults, or a callable with its
    signature (`(samples, sample_rate, *, report) -> RepairResult`).
  * **admit** ([`QCStatus`](foley.qc.html.md#foley.qc.QCStatus)) – The admission floor a repair has to clear to be kept (ingest’s).
  * **thresholds** ([`QCThresholds`](foley.qc.html.md#foley.qc.QCThresholds)) – The QC thresholds (default: the shipped table).
* **Returns:**
  the repaired clip re-encoded in the FLAC archive form when
  the policy repaired it and the re-check meets `admit` — a record made from it
  then describes this re-encode (`format='flac'`, 24-bit), while the provider’s
  bytes as received stay where they were — else `audio_bytes` unchanged; and the
  [`RepairResult`](#foley.repair.RepairResult) (`result.note(admit)` is the one-line account, `None`
  when there was nothing to do).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`RepairResult`](#foley.repair.RepairResult)]

Lazy dependencies: `soundfile`, `numpy`; `soxr` off the working rate.

### foley.repair.suggested_fixes(report, , thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100))

The fixes `report` calls for: [`FIX_FADE`](#foley.repair.FIX_FADE) (an edge click) and/or
`FIX_LIMIT` (a clip event, or a true peak over the ceiling).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.repair.unrepairable(report, , thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=4, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100), max_clipped_ratio=0.001, max_clipped_run=50)

Why `report`’s faults are beyond a Tier-0 repair — `None` when they are not.

Both clipping prongs QC fails on are bounded: the clipped ratio (a share of the
clip) and the longest flat top (a length, so a long clip cannot hide a long
plateau under a small ratio).

* **Parameters:**
  * **report** ([`QCReport`](foley.qc.html.md#foley.qc.QCReport)) – The clip’s QC report.
  * **thresholds** ([`QCThresholds`](foley.qc.html.md#foley.qc.QCThresholds)) – The QC thresholds the report was made with.
  * **max_clipped_ratio** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The most clipping still treated as a run just over the gate.
  * **max_clipped_run** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The longest flat top (samples at the working rate) still
    treated as one.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
