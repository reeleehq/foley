# foley.weave.master

Mastering — loudness-normalize + true-peak-limit the finished mix (report 06 §5).

Normalises the whole program to a [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile) integrated-loudness
target (ITU-R BS.1770-4 / EBU R128 via `pyloudnorm`) and holds an inter-sample
**true-peak** ceiling. It reuses [`foley.audio.loudness_normalize()`](foley.audio.html.md#foley.audio.loudness_normalize) (the same
BS.1770 meter Tier-0 QC uses) for the LUFS stage and [`foley.qc.true_peak_dbtp()`](foley.qc.html.md#foley.qc.true_peak_dbtp)
(oversampled) for the ceiling — so `pyloudnorm` comes from the existing `audio`
extra (no redundant dependency) and is imported function-locally, keeping `import
foley.weave` dol-only.

The default `engine='auto'` masters fully in-process (portable, testable).
`engine='ffmpeg'` runs the two-pass `ffmpeg loudnorm` “guarantee the numbers” master
(report 06 §5.4) — measure, then apply a linear loudnorm to the measured values — and
**fails safe** back to the in-process path when the `ffmpeg` binary is unavailable or
errors, so weaving never depends on it. `ffmpeg` is a WEAVE system requirement (see
[`foley.weave.requirements`](foley.weave.requirements.html.md#module-foley.weave.requirements)); everything is lazy so `import foley.weave` stays dol-only.

### Functions

| [`master`](#foley.weave.master.master)(mix, sample_rate, profile, \*[, ...])   | Master `mix` to `profile` — LUFS-normalise then true-peak-limit (report 06 §5).   |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|

### Classes

| [`MasterReport`](#foley.weave.master.MasterReport)(target_lufs, input_lufs, ...)   | What the master stage did — a JSON-serialisable audit row for the run-artifact.   |
|-----------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|

### *class* foley.weave.master.MasterReport(target_lufs, input_lufs, output_lufs, true_peak_dbtp, true_peak_ceiling_db, gain_db, limited, engine)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the master stage did — a JSON-serialisable audit row for the run-artifact.

#### to_dict()

Return the plain-dict form (for `WeaveResult.master_report` / obs).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.weave.master.master(mix, sample_rate, profile, , engine='auto', limiter=None, meter=None)

Master `mix` to `profile` — LUFS-normalise then true-peak-limit (report 06 §5).

* **Parameters:**
  * **mix** (`ndarray`) – The summed working mix (stereo `(frames, 2)` float32).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **profile** ([`MasterProfile`](foley.base.html.md#foley.base.MasterProfile)) – The [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile) (target LUFS / true-peak / LRA).
  * **engine** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'auto'`/`'inprocess'` master in-process (default, portable). `'ffmpeg'`
    uses the two-pass `ffmpeg loudnorm` “guarantee the numbers” master (report 06
    §5.4) and **fails safe** back to in-process if ffmpeg is unavailable or errors.
  * **limiter** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int), [`float`](https://docs.python.org/3/builtins/functions.html#float)], `ndarray`]]) – The in-process true-peak stage (a `Limiter`, `(mix, sample_rate,
    ceiling_db) -> mix`; default: a static true-peak-safe scale). The seam for a
    lookahead limiter (foley#91). In-process engine only; the true peak in the
    report is always measured here, never taken from the limiter.
  * **meter** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – A [`foley.audio.Meter`](foley.audio.html.md#foley.audio.Meter) for the loudness stages (default `pyloudnorm`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`MasterReport`](#foley.weave.master.MasterReport)]
* **Returns:**
  `(mastered_mix, MasterReport)`. Loudness is measured before and after so the
  report is a faithful audit; when a true-peak limit engages, output LUFS may
  sit slightly below target (peak-safety wins over exact loudness).
