# Running a human panel for the judge calibration

A model judge (the fit judge behind `foley eval-fit`) is only trusted unattended once it agrees with people: Krippendorff's α of at least 0.8 between the judge and the human raters on a calibration slice (`foley.eval.reliability`). This is the manual-first path that produces those human judgements. Building the tasks, the listening page and the analysis is code; recruiting and running the raters is yours.

## 1. Choose what to judge

- **Grade** (`panel.grade_tasks`): "how well does this clip fit the prompt?", 0 wrong, 1 related, 2 acceptable, 3 ideal. This is the scale the judge-vs-human α uses, so a calibration needs these (or MUSHRA scores, which are binned to it).
- **2AFC** (`panel.pairwise_tasks`): "which of these two fits better?" Compares systems (two backends, two prompt styles). Feeds `bradley_terry.fit` for a ranking with intervals.
- **MUSHRA-style** (`panel.mushra_tasks`): rate several systems 0-100 against a reference, with a hidden copy of the reference and a low-quality anchor. Raters who score the hidden reference under 90 in more than 15% of trials are dropped (ITU-R BS.1534 post-screening).

Aim for at least 3 raters and 50 or more units for a grade calibration; α is unstable below that.

## 2. Build the tasks

```python
from foley.eval import panel, render_panel_html

tasks, key = panel.grade_tasks([(unit_id, prompt, "audio/u1.wav", "sa3"), ...])
panel.save_tasks(tasks, key, "panel/")          # tasks.json for raters, key.json: keep private
open("panel/index.html", "w").write(render_panel_html(tasks, title="Foley fit panel"))
```

Copy the clips to `panel/audio/` (the page uses the paths in the tasks). Order and sides are shuffled from a seed; stimulus ids are opaque; the page and `tasks.json` never contain a system name.

## 3. Run it

Host `panel/` anywhere static, or send raters the folder to open `index.html`. Raters use headphones, enter a name, answer every item, and press "Download responses". Collect their `responses-<name>.jsonl` files into one (`cat`). A response line is `{"rater": ..., "task": ..., "answer": ...}`; the answer is an int 0-3 (grade), a stimulus id or `null` for a tie (2AFC), or `{stimulus_id: score}` (MUSHRA). Progress is kept in the browser, so a reload does not lose answers.

## 4. Analyse and feed the calibration

```python
from foley.eval import bradley_terry, panel
import dataclasses

responses = panel.load_responses("panel/responses.jsonl", tasks)

# 2AFC: which system wins?
print(bradley_terry.fit(panel.pairwise_comparisons(tasks, key, responses), bootstrap=1000).ranking())

# MUSHRA: screened mean scores with 95% intervals
print(panel.mushra_scores(tasks, key, responses))

# Grades: human-human and judge-vs-human α, for the calibration report
units = panel.rating_units(tasks, key, responses)
cal = panel.calibrate_against_judge(units, judge_grades)     # {unit: grade} from the fit judge
report = dataclasses.replace(fit_report, calibration=dataclasses.asdict(cal["judge_vs_human"]))
```

`cal["human_alpha"]` is the humans' own agreement: if it is under 0.667, fix the rubric before judging the judge. `cal["judge_vs_human"].promoted` is true when the judge reaches α of 0.8.

## 5. The fit baseline

`foley eval-fit --baseline` gates the hermetic fit run (the deterministic fake judge) against `foley/data/golden/fit_baseline.json`, the same way `foley eval` gates nDCG. A run under a different judge, rung, sample, seed or `k` is reported as not comparable and fails. Once a real judge is calibrated and its numbers are stable, run `foley eval-fit --llm anthropic --update-baseline` (or inject your judge through `foley.evaluate_fit`) to re-stamp it; the judge is recorded in the file's `run`.
