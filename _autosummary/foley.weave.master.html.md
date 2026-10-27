# foley.weave.master

Mastering — loudness-normalize + true-peak-limit the finished mix (report 06 §5).

Normalises the whole program to a [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile) integrated-loudness
target (ITU-R BS.1770-4 / EBU R128) and holds an inter-sample **true-peak** ceiling. It
reuses [`foley.audio.loudness_normalize()`](foley.audio.html.md#foley.audio.loudness_normalize) (the same BS.1770 meter Tier-0 QC uses) for
the LUFS stage, the shared lookahead limiter (`mixing.loudness.limit_peaks()`,
`true_peak=True`) for the ceiling, and [`foley.qc.true_peak_dbtp()`](foley.qc.html.md#foley.qc.true_peak_dbtp) (oversampled) to
report it — all from the existing `audio` extra, imported function-locally, keeping
`import foley.weave` dol-only.

The default `engine='auto'` masters fully in-process (portable, testable).
`engine='ffmpeg'` runs the two-pass `ffmpeg loudnorm` “guarantee the numbers” master
(report 06 §5.4) — measure, then apply a linear loudnorm to the measured values — and
**fails safe** back to the in-process path when the `ffmpeg` binary is unavailable or
errors, so weaving never depends on it. `ffmpeg` is a WEAVE system requirement (see
[`foley.weave.requirements`](foley.weave.requirements.html.md#module-foley.weave.requirements)); everything is lazy so `import foley.weave` stays dol-only.

### Module Attributes

| [`TRIM_MARGIN_DB`](#foley.weave.master.TRIM_MARGIN_DB)   | How far under the ceiling a trim aims, so the rounding of a float32 mix never reads over it (a few 1e-7 dB at most).   |
|-------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`lookahead_true_peak_limit`](#foley.weave.master.lookahead_true_peak_limit)(mix, sample_rate, ...)   | Hold `mix`'s inter-sample true peak at/below `ceiling_db` with a lookahead limiter.   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`master`](#foley.weave.master.master)(mix, sample_rate, profile, \*[, ...])       | Master `mix` to `profile` — LUFS-normalise then true-peak-limit (report 06 §5).       |

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

### foley.weave.master.TRIM_MARGIN_DB *= 1e-05*

How far under the ceiling a trim aims, so the rounding of a float32 mix never
reads over it (a few 1e-7 dB at most).

### foley.weave.master.lookahead_true_peak_limit(mix, sample_rate, ceiling_db)

Hold `mix`’s inter-sample true peak at/below `ceiling_db` with a lookahead limiter.

The default `Limiter` (foley#91): `mixing.loudness.limit_peaks()` with
`true_peak=True` turns down the peaks (the gain eases in and out over its 50 ms
window), not the whole program. What it leaves over the ceiling (it interpolates
its gain between samples; reeleehq/mixing#92) is trimmed by [`master()`](#foley.weave.master.master), which
measures the result once. Deterministic, never raises the level; `mix` comes back
as is (same object) when nothing is over, else with the same shape and dtype. A
non-finite sample is limited as silence and put back where it was, so it neither
spreads over the limiter’s window nor lets the overs around it through.

* **Return type:**
  `ndarray`

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
    ceiling_db) -> mix`; default [`lookahead_true_peak_limit()`](#foley.weave.master.lookahead_true_peak_limit)). For the
    default, the loudness stage lets the sample peak run up to
    `profile.max_limiting_db` over the ceiling for it to take back down; an
    injected limiter gets a mix already held at the ceiling’s sample peak (no
    headroom is assumed of a stage foley does not know). In-process engine
    only; the true peak in the report is always measured here, once, never
    taken from the limiter, and whatever any limiter leaves over the ceiling is
    trimmed by a static gain, so the ceiling holds by the reported number.
  * **meter** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – A [`foley.audio.Meter`](foley.audio.html.md#foley.audio.Meter) for the loudness stages (default
    [`foley.audio.DEFAULT_METER`](foley.audio.html.md#foley.audio.DEFAULT_METER)).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`MasterReport`](#foley.weave.master.MasterReport)]
* **Returns:**
  `(mastered_mix, MasterReport)`. Loudness is measured before and after so the
  report is a faithful audit; when a true-peak limit engages, output LUFS may
  sit slightly below target (peak-safety wins over exact loudness).
