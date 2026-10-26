# foley.eval.panel

Human-panel infrastructure: blind tasks, a listening page, responses, and the calibration feed (#49).

A model judge is only trusted once it agrees with people ([`foley.eval.reliability`](foley.eval.reliability.html.md#module-foley.eval.reliability)). This
module is the manual-first path that produces those people’s judgements; the panel itself is
run by a person. Three task kinds, one flow:

1. **Build** blind tasks from what you want judged: [`grade_tasks()`](#foley.eval.panel.grade_tasks) (rate one clip 0-3 for
   a prompt: the scale the judge-vs-human α uses), [`pairwise_tasks()`](#foley.eval.panel.pairwise_tasks) (2AFC: which of two
   fits better; feeds [`foley.eval.bradley_terry`](foley.eval.bradley_terry.html.md#module-foley.eval.bradley_terry)), [`mushra_tasks()`](#foley.eval.panel.mushra_tasks) (rate several
   systems 0-100 against a reference, with a hidden copy of the reference and a low anchor, in
   the style of ITU-R BS.1534). Sides and order are shuffled with a `seed`; stimulus ids are
   opaque. [`save_tasks()`](#foley.eval.panel.save_tasks) copies every clip to `audio/<stimulus id><ext>` (so neither a
   file name nor the hidden reference’s path gives it away) and writes `tasks.json` (what
   raters get) and `key.json` (which system each stimulus is; keep it from the raters).
2. **Run** it: `render_panel_html()` writes one self-contained page (audio, forms, a
   “download responses” button) to open in a browser or host anywhere static; or send
   `tasks.json` to raters and collect the same `responses.jsonl` by any means. A response is
   one JSON line: `{"rater": ..., "task": ..., "answer": ...}` (the answer shape is per kind,
   see [`check_answer()`](#foley.eval.panel.check_answer)).
3. **Analyse**: [`pairwise_comparisons()`](#foley.eval.panel.pairwise_comparisons) -> `bradley_terry.fit`;
   [`screen_mushra()`](#foley.eval.panel.screen_mushra) (the hidden-reference rule of ITU-R BS.1534 only; the standard’s
   > mid-range anchor rule is not implemented) and [`mushra_scores()`](#foley.eval.panel.mushra_scores); [`rating_units()`](#foley.eval.panel.rating_units) ->

   [`calibrate_against_judge()`](#foley.eval.panel.calibrate_against_judge), which returns the human-human and judge-vs-human
   : Krippendorff α ([`foley.eval.reliability.calibrate_judge_vs_human()`](foley.eval.reliability.html.md#foley.eval.reliability.calibrate_judge_vs_human)) to put in the
     calibration report.

Pure stdlib apart from the numpy used in the analysis functions.

### Module Attributes

| [`GRADE_LABELS`](#foley.eval.panel.GRADE_LABELS)         | The ordinal fit scale of the judge-vs-human calibration, and what each grade means.                                                                                          |
|-----------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`MUSHRA_REFERENCE_MIN`](#foley.eval.panel.MUSHRA_REFERENCE_MIN) | drop a rater who scores the hidden reference under `MUSHRA_REFERENCE_MIN` in more than `MUSHRA_MAX_VIOLATION_RATE` of the trials.                                            |
| [`MUSHRA_GRADE_BOUNDS`](#foley.eval.panel.MUSHRA_GRADE_BOUNDS)  | MUSHRA 0-100 scores binned to the 0-3 grade scale (lower bound of each grade).                                                                                               |
| [`MIN_RATERS`](#foley.eval.panel.MIN_RATERS)           | A judge is only "promoted" on at least this many raters and rated units; below that α says little (and a panel with no variation in its grades gives α = 1 by construction). |
| [`Z95`](#foley.eval.panel.Z95)                  | The z of a 95% normal interval on a mean score.                                                                                                                              |
| [`Key`](#foley.eval.panel.Key)                  | `key` maps a stimulus id to `{"role": ..., "system": ...}` (never shown to raters).                                                                                          |

### Functions

| [`calibrate_against_judge`](#foley.eval.panel.calibrate_against_judge)(units, judge_grades, \*)   | Human-human and judge-vs-human agreement, ready for the calibration report.                               |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| [`check_answer`](#foley.eval.panel.check_answer)(task, answer)                         | Raise `ValueError` unless `answer` has the shape `task.kind` takes.                                       |
| [`grade_tasks`](#foley.eval.panel.grade_tasks)(units)                                 | Tasks that ask for a 0-3 grade; `units` are `(unit_id, prompt, clip, system)`.                            |
| [`load_key`](#foley.eval.panel.load_key)(path)                                     | Read `key.json`.                                                                                          |
| [`load_responses`](#foley.eval.panel.load_responses)(path, tasks)                        | Read `responses.jsonl` (one `{"rater", "task", "answer"}` per line), validated.                           |
| [`load_tasks`](#foley.eval.panel.load_tasks)(path)                                   | Read `tasks.json`.                                                                                        |
| [`mushra_scores`](#foley.eval.panel.mushra_scores)(tasks, key, responses, \*[, raters]) | `{system: (mean, ci_low, ci_high)}` over MUSHRA answers (95% normal interval).                            |
| [`mushra_tasks`](#foley.eval.panel.mushra_tasks)(trials, \*[, seed])                   | MUSHRA-style tasks; `trials` are `(unit_id, prompt, reference_clip, [(clip, system), ...], anchor_clip)`. |
| [`mushra_to_grade`](#foley.eval.panel.mushra_to_grade)(score, \*[, bounds])               | A 0-100 score as a 0-3 grade (the highest grade whose lower bound the score reaches).                     |
| [`pairwise_comparisons`](#foley.eval.panel.pairwise_comparisons)(tasks, key, responses)        | `(winner_system, loser_system)` for every non-tie 2AFC answer (feed `bradley_terry.fit`).                 |
| [`pairwise_tasks`](#foley.eval.panel.pairwise_tasks)(comparisons, \*[, seed])            | 2AFC tasks; `comparisons` are `(prompt, (clip_a, system_a), (clip_b, system_b))`.                         |
| [`rating_units`](#foley.eval.panel.rating_units)(tasks, key, responses)                | `{unit: {rater: grade}}` from the grade and MUSHRA answers (the calibration feed).                        |
| [`save_tasks`](#foley.eval.panel.save_tasks)(tasks, key, directory, \*[, audio_dir]) | Write the panel folder: `tasks.json` (for raters), `key.json` (keep private), the audio.                  |
| [`screen_mushra`](#foley.eval.panel.screen_mushra)(tasks, key, responses, \*[, ...])    | `(accepted_raters, {rejected_rater: violation_rate})` by the hidden-reference rule.                       |

### Classes

| [`Stimulus`](#foley.eval.panel.Stimulus)(id, clip)                           | One clip a rater hears: an opaque `id` and the audio `clip` (a path or URL).       |
|-----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`Task`](#foley.eval.panel.Task)(id, kind, prompt, stimuli[, unit, ...]) | One judgement: `kind`, the `prompt` shown, the `stimuli` (shuffled), and a `unit`. |

### foley.eval.panel.GRADE_LABELS *= {0: 'wrong: not the sound asked for', 1: 'related: same family, clearly off', 2: 'acceptable: usable for the moment', 3: 'ideal: exactly right'}*

The ordinal fit scale of the judge-vs-human calibration, and what each grade means.

### foley.eval.panel.Key

`key` maps a stimulus id to `{"role": ..., "system": ...}` (never shown to raters).

alias of [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.eval.panel.MIN_RATERS *= 3*

A judge is only “promoted” on at least this many raters and rated units; below that α
says little (and a panel with no variation in its grades gives α = 1 by construction).

### foley.eval.panel.MUSHRA_GRADE_BOUNDS *= (0, 25, 60, 85)*

MUSHRA 0-100 scores binned to the 0-3 grade scale (lower bound of each grade).

### foley.eval.panel.MUSHRA_REFERENCE_MIN *= 90*

drop a rater who scores the hidden reference under
`MUSHRA_REFERENCE_MIN` in more than `MUSHRA_MAX_VIOLATION_RATE` of the trials.

* **Type:**
  Post-screening (ITU-R BS.1534)

### *class* foley.eval.panel.Stimulus(id, clip)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One clip a rater hears: an opaque `id` and the audio `clip` (a path or URL).

### *class* foley.eval.panel.Task(id, kind, prompt, stimuli, unit='', reference=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One judgement: `kind`, the `prompt` shown, the `stimuli` (shuffled), and a `unit`.

`unit` names what is judged (a golden-set unit id); judge-vs-human calibration joins on it.
MUSHRA tasks also carry the visible `reference` clip.

### foley.eval.panel.Z95 *= 1.96*

The z of a 95% normal interval on a mean score.

### foley.eval.panel.calibrate_against_judge(units, judge_grades, , level='ordinal', min_raters=3, min_units=50)

Human-human and judge-vs-human agreement, ready for the calibration report.

The judge is compared with the humans’ **consensus** (the per-unit median grade), never
as one more rater next to all of them: with many humans who agree with each other, a
judge added as a row would borrow their agreement and look reliable whatever it says.
`per_rater` is α of the judge against each person alone.

* **Parameters:**
  * **units** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]) – [`rating_units()`](#foley.eval.panel.rating_units)’ `{unit: {rater: grade}}`.
  * **judge_grades** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The model judge’s `{unit: grade}` for the same units.
  * **min_raters** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Fewer raters than this and nothing is promoted.
  * **min_units** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Fewer units rated by at least two people than this and nothing is promoted.
* **Returns:**
  AlphaResult | None, “judge_vs_human”: AlphaResult | None,
  “per_rater”: {rater: alpha}, “n_units”: …, “raters”: […], “insufficient”: […]}\`\`.
  `human_alpha` is the humans’ own α (it needs two raters and a unit both rated);
  `judge_vs_human` is the judge against the consensus. An `AlphaResult` is never
  `promoted` while `insufficient` is non-empty: too few raters, too few doubly-rated
  units, or human (or judge) grades that do not vary (α is 1 by construction then).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.panel.check_answer(task, answer)

Raise `ValueError` unless `answer` has the shape `task.kind` takes.

`grade`: an int in 0-3. `2afc`: a stimulus id of the task, or `None` for a tie.
`mushra`: `{stimulus_id: score 0-100}` covering every stimulus.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.eval.panel.grade_tasks(units)

Tasks that ask for a 0-3 grade; `units` are `(unit_id, prompt, clip, system)`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Task`](#foley.eval.panel.Task)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.panel.load_key(path)

Read `key.json`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.panel.load_responses(path, tasks)

Read `responses.jsonl` (one `{"rater", "task", "answer"}` per line), validated.

A rater answering the same task twice keeps the last answer. Raters are told apart by
name only: two people using the same name are merged, so give every rater a unique one.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.panel.load_tasks(path)

Read `tasks.json`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Task`](#foley.eval.panel.Task)]

### foley.eval.panel.mushra_scores(tasks, key, responses, , raters=None)

`{system: (mean, ci_low, ci_high)}` over MUSHRA answers (95% normal interval).

Only `raters` (default: those [`screen_mushra()`](#foley.eval.panel.screen_mushra) accepts). The hidden reference and
anchor are reported under their own names.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### foley.eval.panel.mushra_tasks(trials, , seed=0)

MUSHRA-style tasks; `trials` are `(unit_id, prompt, reference_clip, [(clip, system), ...], anchor_clip)`.

Each task shows the reference, and the systems plus a hidden copy of the reference and
(if `anchor_clip` is given) a low-quality anchor, in shuffled order.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Task`](#foley.eval.panel.Task)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.panel.mushra_to_grade(score, , bounds=(0, 25, 60, 85))

A 0-100 score as a 0-3 grade (the highest grade whose lower bound the score reaches).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.eval.panel.pairwise_comparisons(tasks, key, responses)

`(winner_system, loser_system)` for every non-tie 2AFC answer (feed `bradley_terry.fit`).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.eval.panel.pairwise_tasks(comparisons, , seed=0)

2AFC tasks; `comparisons` are `(prompt, (clip_a, system_a), (clip_b, system_b))`.

Which clip is on the left is shuffled per task from `seed`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Task`](#foley.eval.panel.Task)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.panel.rating_units(tasks, key, responses)

`{unit: {rater: grade}}` from the grade and MUSHRA answers (the calibration feed).

A unit is `"<task.unit>|<system>"` for both kinds (one golden unit judged for two systems
is two units); a MUSHRA score is binned by [`mushra_to_grade()`](#foley.eval.panel.mushra_to_grade). The hidden
reference and anchor are not units.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

### foley.eval.panel.save_tasks(tasks, key, directory, , audio_dir='audio')

Write the panel folder: `tasks.json` (for raters), `key.json` (keep private), the audio.

Every clip (a local file) is copied to `<directory>/<audio_dir>/<stimulus id><ext>` and the
tasks written point at the copies, so a file name never names the system and the hidden
reference does not share a path with the visible one. The returned tasks are those
rewritten ones (hand them to [`foley.eval.panel_page.render_panel_html()`](foley.eval.panel_page.html.md#foley.eval.panel_page.render_panel_html)).

* **Raises:**
  * [**FileNotFoundError**](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) – A clip is not a local file (fetch it first).
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – Task ids repeat, or the clips are in more than one format (the extension
        would give a system away).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Task`](#foley.eval.panel.Task)]]

### foley.eval.panel.screen_mushra(tasks, key, responses, , reference_min=90, max_violation_rate=0.15)

`(accepted_raters, {rejected_rater: violation_rate})` by the hidden-reference rule.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
