"""Human-panel infrastructure: blind tasks, a listening page, responses, and the calibration feed (#49).

A model judge is only trusted once it agrees with people (:mod:`foley.eval.reliability`). This
module is the manual-first path that produces those people's judgements; the panel itself is
run by a person. Three task kinds, one flow:

1. **Build** blind tasks from what you want judged: :func:`grade_tasks` (rate one clip 0-3 for
   a prompt: the scale the judge-vs-human α uses), :func:`pairwise_tasks` (2AFC: which of two
   fits better; feeds :mod:`foley.eval.bradley_terry`), :func:`mushra_tasks` (rate several
   systems 0-100 against a reference, with a hidden copy of the reference and a low anchor, in
   the style of ITU-R BS.1534). Sides and order are shuffled with a ``seed``; stimulus ids are
   opaque. :func:`save_tasks` copies every clip to ``audio/<stimulus id><ext>`` (so neither a
   file name nor the hidden reference's path gives it away) and writes ``tasks.json`` (what
   raters get) and ``key.json`` (which system each stimulus is; keep it from the raters).
2. **Run** it: :func:`render_panel_html` writes one self-contained page (audio, forms, a
   "download responses" button) to open in a browser or host anywhere static; or send
   ``tasks.json`` to raters and collect the same ``responses.jsonl`` by any means. A response is
   one JSON line: ``{"rater": ..., "task": ..., "answer": ...}`` (the answer shape is per kind,
   see :func:`check_answer`).
3. **Analyse**: :func:`pairwise_comparisons` -> ``bradley_terry.fit``;
   :func:`screen_mushra` (the hidden-reference rule of ITU-R BS.1534 only; the standard's
   mid-range anchor rule is not implemented) and :func:`mushra_scores`; :func:`rating_units` ->
   :func:`calibrate_against_judge`, which returns the human-human and judge-vs-human
   Krippendorff α (:func:`foley.eval.reliability.calibrate_judge_vs_human`) to put in the
   calibration report.

Pure stdlib apart from the numpy used in the analysis functions.
"""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import asdict, dataclass, replace
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
#: A judge is only "promoted" on at least this many raters and rated units; below that α
#: says little (and a panel with no variation in its grades gives α = 1 by construction).
MIN_RATERS = 3
MIN_UNITS = 50
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
    for unit, prompt, a, b in comparisons:
        tid = f"p{len(tasks):04d}"
        pair = [a, b]
        rng.shuffle(pair)
        stimuli = []
        for k, (clip, system) in enumerate(pair):
            sid = f"{tid}-{k}"
            stimuli.append(Stimulus(sid, clip))
            key[sid] = {"role": ROLE_SYSTEM, "system": system}
        tasks.append(Task(tid, PAIRWISE, prompt, tuple(stimuli), unit))
    return tasks, key


def mushra_tasks(
    trials: "Iterable[tuple[str, str, str, Sequence[tuple[str, str]], Optional[str]]]",
    *,
    seed: int = 0,
) -> "tuple[list[Task], dict]":
    """MUSHRA-style tasks; ``trials`` are ``(unit_id, prompt, reference_clip, [(clip, system), ...], anchor_clip)``.

    Each task shows the reference, and the systems plus a hidden copy of the reference and
    (if ``anchor_clip`` is given) a low-quality anchor, in shuffled order.
    """
    rng = random.Random(seed)
    tasks, key = [], {}
    for unit, prompt, reference, systems, anchor in trials:
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
        tasks.append(Task(tid, MUSHRA, prompt, tuple(stimuli), unit, reference))
    return tasks, key


def save_tasks(
    tasks: Sequence[Task], key: Key, directory, *, audio_dir: str = "audio"
) -> "tuple[Path, Path, list[Task]]":
    """Write the panel folder: ``tasks.json`` (for raters), ``key.json`` (keep private), the audio.

    Every clip (a local file) is copied to ``<directory>/<audio_dir>/<stimulus id><ext>`` and the
    tasks written point at the copies, so a file name never names the system and the hidden
    reference does not share a path with the visible one. The returned tasks are those
    rewritten ones (hand them to :func:`foley.eval.panel_page.render_panel_html`).

    Raises:
        FileNotFoundError: A clip is not a local file (fetch it first).
        ValueError: Task ids repeat, or the clips are in more than one format (the extension
            would give a system away).
    """
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("task ids are not unique (two task lists were combined?)")
    clips = [s.clip for t in tasks for s in t.stimuli] + [
        t.reference for t in tasks if t.reference
    ]
    suffixes = {Path(c).suffix.lower() for c in clips}
    if len(suffixes) > 1:
        raise ValueError(
            f"the clips have mixed formats {sorted(suffixes)}: a file extension would tell "
            "the systems apart; convert them to one format first"
        )
    root = Path(directory)
    audio = root / audio_dir
    audio.mkdir(parents=True, exist_ok=True)

    def anonymise(clip: str, name: str) -> str:
        src = Path(clip)
        if not src.is_file():
            raise FileNotFoundError(f"panel clip {clip!r} is not a local file")
        dest = audio / f"{name}{src.suffix}"
        shutil.copyfile(src, dest)
        return f"{audio_dir}/{dest.name}"

    blind = [
        replace(
            t,
            stimuli=tuple(Stimulus(s.id, anonymise(s.clip, s.id)) for s in t.stimuli),
            reference=anonymise(t.reference, f"{t.id}-ref") if t.reference else None,
        )
        for t in tasks
    ]
    tasks_path, key_path = root / "tasks.json", root / "key.json"
    tasks_path.write_text(json.dumps([asdict(t) for t in blind], indent=1) + "\n")
    key_path.write_text(json.dumps(dict(key), indent=1, sort_keys=True) + "\n")
    return tasks_path, key_path, blind


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


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


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
        ok = answer is None or (isinstance(answer, str) and answer in ids)
    elif task.kind == MUSHRA:
        lo, hi = MUSHRA_RANGE
        ok = (
            isinstance(answer, dict)
            and set(answer) == ids
            and all(_is_number(v) and lo <= v <= hi for v in answer.values())
        )
    else:
        raise ValueError(f"unknown task kind {task.kind!r}; use one of {KINDS}")
    if not ok:
        raise ValueError(f"task {task.id} ({task.kind}): bad answer {answer!r}")


def load_responses(path, tasks: Sequence[Task]) -> "list[dict]":
    """Read ``responses.jsonl`` (one ``{"rater", "task", "answer"}`` per line), validated.

    A rater answering the same task twice keeps the last answer. Raters are told apart by
    name only: two people using the same name are merged, so give every rater a unique one.
    """
    by_id = {t.id: t for t in tasks}
    latest: dict = {}
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            not isinstance(row, dict)
            or row.get("task") not in by_id
            or not isinstance(row.get("rater"), str)
            or not row["rater"].strip()
            or "answer" not in row
        ):
            raise ValueError(
                f"{path}:{n}: unknown task, missing rater or answer: {row}"
            )
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

    A unit is ``"<task.unit>|<system>"`` for both kinds (one golden unit judged for two systems
    is two units); a MUSHRA score is binned by :func:`mushra_to_grade`. The hidden
    reference and anchor are not units.
    """
    by_id = _tasks_by_id(tasks)
    units: dict = {}
    for r in responses:
        task = by_id[r["task"]]
        if task.kind == GRADE:
            system = key[task.stimuli[0].id]["system"]
            units.setdefault(f"{task.unit}|{system}", {})[r["rater"]] = r["answer"]
        elif task.kind == MUSHRA:
            for sid, score in r["answer"].items():
                if key[sid]["role"] == ROLE_SYSTEM:
                    unit = f"{task.unit}|{key[sid]['system']}"
                    units.setdefault(unit, {})[r["rater"]] = mushra_to_grade(score)
    return units


def _consensus(grades: "Iterable[int]") -> int:
    """The median human grade, rounded down on a tie between two grades (the cautious side)."""
    ordered = sorted(grades)
    return ordered[(len(ordered) - 1) // 2]


def calibrate_against_judge(
    units: "Mapping[str, Mapping[str, int]]",
    judge_grades: "Mapping[str, int]",
    *,
    level: str = "ordinal",
    min_raters: int = MIN_RATERS,
    min_units: int = MIN_UNITS,
) -> dict:
    """Human-human and judge-vs-human agreement, ready for the calibration report.

    The judge is compared with the humans' **consensus** (the per-unit median grade), never
    as one more rater next to all of them: with many humans who agree with each other, a
    judge added as a row would borrow their agreement and look reliable whatever it says.
    ``per_rater`` is α of the judge against each person alone.

    Args:
        units: :func:`rating_units`' ``{unit: {rater: grade}}``.
        judge_grades: The model judge's ``{unit: grade}`` for the same units.
        min_raters: Fewer raters than this and nothing is promoted.
        min_units: Fewer units rated by at least two people than this and nothing is promoted.

    Returns:
        ``{"human_alpha": AlphaResult | None, "judge_vs_human": AlphaResult | None,
        "per_rater": {rater: alpha}, "n_units": ..., "raters": [...], "insufficient": [...]}``.
        ``human_alpha`` is the humans' own α (it needs two raters and a unit both rated);
        ``judge_vs_human`` is the judge against the consensus. An ``AlphaResult`` is never
        ``promoted`` while ``insufficient`` is non-empty: too few raters, too few doubly-rated
        units, or human (or judge) grades that do not vary (α is 1 by construction then).
    """
    import numpy as np

    from .reliability import alpha_result, calibrate_judge_vs_human, krippendorff_alpha

    raters = sorted({r for row in units.values() for r in row})
    shared = sorted(u for u in units if u in judge_grades)
    human = np.full((len(raters), len(shared)), np.nan)
    for j, unit in enumerate(shared):
        for i, rater in enumerate(raters):
            if rater in units[unit]:
                human[i, j] = units[unit][rater]
    judge = np.array([float(judge_grades[u]) for u in shared])
    consensus = np.array([_consensus(units[u].values()) for u in shared], dtype=float)
    doubly_rated = int((np.sum(~np.isnan(human), axis=0) >= 2).sum())

    insufficient = []
    if len(raters) < min_raters:
        insufficient.append(f"{len(raters)} raters, need {min_raters}")
    if doubly_rated < min_units:
        insufficient.append(
            f"{doubly_rated} units rated by two or more people, need {min_units}"
        )
    if len({g for row in units.values() for g in row.values()}) < 2:
        insufficient.append("the human grades do not vary")
    if len(set(judge.tolist())) < 2:
        insufficient.append("the judge grades do not vary")

    result: dict = {
        "human_alpha": None, "judge_vs_human": None, "per_rater": {},
        "n_units": len(shared), "raters": raters, "insufficient": insufficient,
    }  # fmt: skip
    if len(raters) >= 2 and shared:
        result["human_alpha"] = alpha_result(human, level=level)
    if len(shared) >= 2 and raters:
        result["judge_vs_human"] = calibrate_judge_vs_human(
            consensus, judge, level=level
        )
        for i, rater in enumerate(raters):
            pair = np.vstack([human[i], judge])
            if (~np.isnan(human[i])).sum() >= 2:
                result["per_rater"][rater] = krippendorff_alpha(pair, level=level)
    if insufficient:
        for name in ("human_alpha", "judge_vs_human"):
            if result[name] is not None:
                result[name] = replace(result[name], promoted=False)
    return result
