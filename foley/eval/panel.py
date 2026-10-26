"""Human-panel infrastructure: blind tasks, a listening page, responses, and the calibration feed (#49).

A model judge is only trusted once it agrees with people (:mod:`foley.eval.reliability`). This
module is the manual-first path that produces those people's judgements; the panel itself is
run by a person. Three task kinds, one flow:

1. **Build** blind tasks from what you want judged: :func:`grade_tasks` (rate one clip 0-3 for
   a prompt: the scale the judge-vs-human α uses), :func:`pairwise_tasks` (2AFC: which of two
   fits better; feeds :mod:`foley.eval.bradley_terry`), :func:`mushra_tasks` (rate several
   systems 0-100 against a reference, with a hidden copy of the reference and a low anchor, in
   the style of ITU-R BS.1534). Sides and order are shuffled with a ``seed``; stimulus ids are
   opaque. :func:`save_tasks` writes ``tasks.json`` (what raters get) and ``key.json`` (which
   system each stimulus is; keep it from the raters).
2. **Run** it: :func:`render_panel_html` writes one self-contained page (audio, forms, a
   "download responses" button) to open in a browser or host anywhere static; or send
   ``tasks.json`` to raters and collect the same ``responses.jsonl`` by any means. A response is
   one JSON line: ``{"rater": ..., "task": ..., "answer": ...}`` (the answer shape is per kind,
   see :func:`check_answer`).
3. **Analyse**: :func:`pairwise_comparisons` -> ``bradley_terry.fit``;
   :func:`screen_mushra` and :func:`mushra_scores`; :func:`rating_units` ->
   :func:`calibrate_against_judge`, which returns the human-human and judge-vs-human
   Krippendorff α (:func:`foley.eval.reliability.calibrate_judge_vs_human`) to put in the
   calibration report.

Pure stdlib apart from the numpy used in the analysis functions.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

GRADE, PAIRWISE, MUSHRA = "grade", "2afc", "mushra"
KINDS = (GRADE, PAIRWISE, MUSHRA)

#: The ordinal fit scale of the judge-vs-human calibration, and what each grade means.
GRADE_LABELS = {
    0: "wrong: not the sound asked for",
    1: "related: same family, clearly off",
    2: "acceptable: usable for the moment",
    3: "ideal: exactly right",
}
MUSHRA_RANGE = (0, 100)
#: Post-screening (ITU-R BS.1534): drop a rater who scores the hidden reference under
#: ``MUSHRA_REFERENCE_MIN`` in more than ``MUSHRA_MAX_VIOLATION_RATE`` of the trials.
MUSHRA_REFERENCE_MIN = 90
MUSHRA_MAX_VIOLATION_RATE = 0.15
#: MUSHRA 0-100 scores binned to the 0-3 grade scale (lower bound of each grade).
MUSHRA_GRADE_BOUNDS = (0, 25, 60, 85)
#: The z of a 95% normal interval on a mean score.
Z95 = 1.96
ROLE_SYSTEM, ROLE_REFERENCE, ROLE_ANCHOR = "system", "reference", "anchor"
HIDDEN_REFERENCE = "hidden_reference"
ANCHOR = "anchor"


@dataclass(frozen=True)
class Stimulus:
    """One clip a rater hears: an opaque ``id`` and the audio ``clip`` (a path or URL)."""

    id: str
    clip: str


@dataclass(frozen=True)
class Task:
    """One judgement: ``kind``, the ``prompt`` shown, the ``stimuli`` (shuffled), and a ``unit``.

    ``unit`` names what is judged (a golden-set unit id); judge-vs-human calibration joins on it.
    MUSHRA tasks also carry the visible ``reference`` clip.
    """

    id: str
    kind: str
    prompt: str
    stimuli: "tuple[Stimulus, ...]"
    unit: str = ""
    reference: Optional[str] = None


#: ``key`` maps a stimulus id to ``{"role": ..., "system": ...}`` (never shown to raters).
Key = Mapping[str, Mapping[str, str]]


def grade_tasks(
    units: "Iterable[tuple[str, str, str, str]]",
) -> "tuple[list[Task], dict]":
    """Tasks that ask for a 0-3 grade; ``units`` are ``(unit_id, prompt, clip, system)``."""
    tasks, key = [], {}
    for unit, prompt, clip, system in units:
        tid = f"g{len(tasks):04d}"
        sid = f"{tid}-0"
        tasks.append(Task(tid, GRADE, prompt, (Stimulus(sid, clip),), unit))
        key[sid] = {"role": ROLE_SYSTEM, "system": system}
    return tasks, key


def pairwise_tasks(
    comparisons: "Iterable[tuple[str, tuple[str, str], tuple[str, str]]]",
    *,
    seed: int = 0,
) -> "tuple[list[Task], dict]":
    """2AFC tasks; ``comparisons`` are ``(prompt, (clip_a, system_a), (clip_b, system_b))``.

    Which clip is on the left is shuffled per task from ``seed``.
    """
    rng = random.Random(seed)
    tasks, key = [], {}
    for prompt, a, b in comparisons:
        tid = f"p{len(tasks):04d}"
        pair = [a, b]
        rng.shuffle(pair)
        stimuli = []
        for k, (clip, system) in enumerate(pair):
            sid = f"{tid}-{k}"
            stimuli.append(Stimulus(sid, clip))
            key[sid] = {"role": ROLE_SYSTEM, "system": system}
        tasks.append(Task(tid, PAIRWISE, prompt, tuple(stimuli), prompt))
    return tasks, key


def mushra_tasks(
    trials: "Iterable[tuple[str, str, Sequence[tuple[str, str]], Optional[str]]]",
    *,
    seed: int = 0,
) -> "tuple[list[Task], dict]":
    """MUSHRA-style tasks; ``trials`` are ``(prompt, reference_clip, [(clip, system), ...], anchor_clip)``.

    Each task shows the reference, and the systems plus a hidden copy of the reference and
    (if ``anchor_clip`` is given) a low-quality anchor, in shuffled order.
    """
    rng = random.Random(seed)
    tasks, key = [], {}
    for prompt, reference, systems, anchor in trials:
        tid = f"m{len(tasks):04d}"
        items = [(clip, ROLE_SYSTEM, system) for clip, system in systems]
        items.append((reference, ROLE_REFERENCE, HIDDEN_REFERENCE))
        if anchor:
            items.append((anchor, ROLE_ANCHOR, ANCHOR))
        rng.shuffle(items)
        stimuli = []
        for k, (clip, role, system) in enumerate(items):
            sid = f"{tid}-{k}"
            stimuli.append(Stimulus(sid, clip))
            key[sid] = {"role": role, "system": system}
        tasks.append(Task(tid, MUSHRA, prompt, tuple(stimuli), prompt, reference))
    return tasks, key


def save_tasks(tasks: Sequence[Task], key: Key, directory) -> "tuple[Path, Path]":
    """Write ``tasks.json`` (for raters) and ``key.json`` (keep private) into ``directory``."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    tasks_path, key_path = root / "tasks.json", root / "key.json"
    tasks_path.write_text(json.dumps([asdict(t) for t in tasks], indent=1) + "\n")
    key_path.write_text(json.dumps(dict(key), indent=1, sort_keys=True) + "\n")
    return tasks_path, key_path


def load_tasks(path) -> "list[Task]":
    """Read ``tasks.json``."""
    return [
        Task(
            id=t["id"],
            kind=t["kind"],
            prompt=t["prompt"],
            stimuli=tuple(Stimulus(**s) for s in t["stimuli"]),
            unit=t.get("unit", ""),
            reference=t.get("reference"),
        )
        for t in json.loads(Path(path).read_text())
    ]


def load_key(path) -> dict:
    """Read ``key.json``."""
    return json.loads(Path(path).read_text())


def check_answer(task: Task, answer) -> None:
    """Raise ``ValueError`` unless ``answer`` has the shape ``task.kind`` takes.

    ``grade``: an int in 0-3. ``2afc``: a stimulus id of the task, or ``None`` for a tie.
    ``mushra``: ``{stimulus_id: score 0-100}`` covering every stimulus.
    """
    ids = {s.id for s in task.stimuli}
    if task.kind == GRADE:
        ok = (
            isinstance(answer, int)
            and not isinstance(answer, bool)
            and answer in GRADE_LABELS
        )
    elif task.kind == PAIRWISE:
        ok = answer is None or answer in ids
    elif task.kind == MUSHRA:
        lo, hi = MUSHRA_RANGE
        ok = (
            isinstance(answer, dict)
            and set(answer) == ids
            and all(
                isinstance(v, (int, float)) and lo <= v <= hi for v in answer.values()
            )
        )
    else:
        raise ValueError(f"unknown task kind {task.kind!r}; use one of {KINDS}")
    if not ok:
        raise ValueError(f"task {task.id} ({task.kind}): bad answer {answer!r}")


def load_responses(path, tasks: Sequence[Task]) -> "list[dict]":
    """Read ``responses.jsonl`` (one ``{"rater", "task", "answer"}`` per line), validated.

    A rater answering the same task twice keeps the last answer.
    """
    by_id = {t.id: t for t in tasks}
    latest: dict = {}
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("task") not in by_id or not row.get("rater"):
            raise ValueError(f"{path}:{n}: unknown task or missing rater: {row}")
        check_answer(by_id[row["task"]], row["answer"])
        latest[(row["rater"], row["task"])] = row
    return list(latest.values())


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


def _tasks_by_id(tasks: Sequence[Task]) -> dict:
    return {t.id: t for t in tasks}


def pairwise_comparisons(
    tasks: Sequence[Task], key: Key, responses: Sequence[dict]
) -> "list[tuple[str, str]]":
    """``(winner_system, loser_system)`` for every non-tie 2AFC answer (feed ``bradley_terry.fit``)."""
    by_id = _tasks_by_id(tasks)
    out = []
    for r in responses:
        task = by_id[r["task"]]
        if task.kind != PAIRWISE or r["answer"] is None:
            continue
        won = key[r["answer"]]["system"]
        lost = next(key[s.id]["system"] for s in task.stimuli if s.id != r["answer"])
        if won != lost:
            out.append((won, lost))
    return out


def screen_mushra(
    tasks: Sequence[Task],
    key: Key,
    responses: Sequence[dict],
    *,
    reference_min: float = MUSHRA_REFERENCE_MIN,
    max_violation_rate: float = MUSHRA_MAX_VIOLATION_RATE,
) -> "tuple[list[str], dict]":
    """``(accepted_raters, {rejected_rater: violation_rate})`` by the hidden-reference rule."""
    by_id = _tasks_by_id(tasks)
    trials: dict = {}
    for r in responses:
        task = by_id[r["task"]]
        if task.kind != MUSHRA:
            continue
        ref = next(s.id for s in task.stimuli if key[s.id]["role"] == ROLE_REFERENCE)
        trials.setdefault(r["rater"], []).append(r["answer"][ref] < reference_min)
    rates = {rater: sum(v) / len(v) for rater, v in trials.items()}
    accepted = sorted(
        rater for rater, rate in rates.items() if rate <= max_violation_rate
    )
    rejected = {
        rater: rate
        for rater, rate in sorted(rates.items())
        if rate > max_violation_rate
    }
    return accepted, rejected


def mushra_scores(
    tasks: Sequence[Task],
    key: Key,
    responses: Sequence[dict],
    *,
    raters: Optional[Iterable[str]] = None,
) -> "dict[str, tuple[float, float, float]]":
    """``{system: (mean, ci_low, ci_high)}`` over MUSHRA answers (95% normal interval).

    Only ``raters`` (default: those :func:`screen_mushra` accepts). The hidden reference and
    anchor are reported under their own names.
    """
    import numpy as np

    keep = (
        set(raters)
        if raters is not None
        else set(screen_mushra(tasks, key, responses)[0])
    )
    by_id = _tasks_by_id(tasks)
    scores: dict = {}
    for r in responses:
        if r["rater"] in keep and by_id[r["task"]].kind == MUSHRA:
            for sid, value in r["answer"].items():
                scores.setdefault(key[sid]["system"], []).append(float(value))
    out = {}
    for system, values in sorted(scores.items()):
        mean = float(np.mean(values))
        sem = (
            float(np.std(values, ddof=1) / np.sqrt(len(values)))
            if len(values) > 1
            else 0.0
        )
        out[system] = (mean, mean - Z95 * sem, mean + Z95 * sem)
    return out


def mushra_to_grade(
    score: float, *, bounds: Sequence[float] = MUSHRA_GRADE_BOUNDS
) -> int:
    """A 0-100 score as a 0-3 grade (the highest grade whose lower bound the score reaches)."""
    return max(g for g, low in enumerate(bounds) if score >= low)


def rating_units(
    tasks: Sequence[Task], key: Key, responses: Sequence[dict]
) -> "dict[str, dict[str, int]]":
    """``{unit: {rater: grade}}`` from the grade and MUSHRA answers (the calibration feed).

    A grade task's unit is ``task.unit``; a MUSHRA stimulus of a system is the unit
    ``"<task.unit>|<system>"`` with its score binned by :func:`mushra_to_grade`. The hidden
    reference and anchor are not units.
    """
    by_id = _tasks_by_id(tasks)
    units: dict = {}
    for r in responses:
        task = by_id[r["task"]]
        if task.kind == GRADE:
            units.setdefault(task.unit, {})[r["rater"]] = r["answer"]
        elif task.kind == MUSHRA:
            for sid, score in r["answer"].items():
                if key[sid]["role"] == ROLE_SYSTEM:
                    unit = f"{task.unit}|{key[sid]['system']}"
                    units.setdefault(unit, {})[r["rater"]] = mushra_to_grade(score)
    return units


def calibrate_against_judge(
    units: "Mapping[str, Mapping[str, int]]",
    judge_grades: "Mapping[str, int]",
    *,
    level: str = "ordinal",
) -> dict:
    """Human-human and judge-vs-human agreement, ready for the calibration report.

    Args:
        units: :func:`rating_units`' ``{unit: {rater: grade}}``.
        judge_grades: The model judge's ``{unit: grade}`` for the same units.

    Returns:
        ``{"human_alpha": AlphaResult | None, "judge_vs_human": AlphaResult | None,
        "n_units": ..., "raters": [...]}``. ``human_alpha`` needs two or more raters;
        ``judge_vs_human`` needs a judge grade on at least two rated units.
    """
    import numpy as np

    from .reliability import (
        ALPHA_RELIABLE,
        AlphaResult,
        calibrate_judge_vs_human,
        krippendorff_alpha,
        percent_agreement,
        reliability_band,
    )

    raters = sorted({r for row in units.values() for r in row})
    shared = sorted(u for u in units if u in judge_grades)
    human = np.full((len(raters), len(shared)), np.nan)
    for j, unit in enumerate(shared):
        for i, rater in enumerate(raters):
            if rater in units[unit]:
                human[i, j] = units[unit][rater]
    judge = np.array([float(judge_grades[u]) for u in shared])
    result: dict = {
        "human_alpha": None,
        "judge_vs_human": None,
        "n_units": len(shared),
        "raters": raters,
    }
    if len(raters) >= 2 and shared:
        alpha = krippendorff_alpha(human, level=level)
        result["human_alpha"] = AlphaResult(
            alpha=alpha, level=level, n_units=int((np.sum(~np.isnan(human), axis=0) >= 2).sum()),
            n_raters=len(raters), percent_agreement=percent_agreement(human),
            band=reliability_band(alpha), promoted=alpha >= ALPHA_RELIABLE,
        )  # fmt: skip
    if len(shared) >= 2 and raters:
        result["judge_vs_human"] = calibrate_judge_vs_human(human, judge, level=level)
    return result
