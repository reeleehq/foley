"""The "tasteful weave" eval: does a sound designer produce a *restrained, clean, well-placed* result?

Runs a ``designer`` (``passage -> ScoreResult``) over a fixed passage set and REPORTS, per
passage and aggregated, the four things #45 asks of a tasteful design (report, never a gate):

* **restraint**: sounds per sentence, under the ceiling of :data:`SOUNDS_PER_SENTENCE_BAND`
  per passage and inside the band over the whole set;
* **licence cleanliness**: the share of placed sounds :func:`foley.keep` accepts under the
  intended use (target :data:`LICENCE_CLEAN_TARGET`, i.e. 100%); a sound with no library
  record is unclean (fail-closed, the same lookup the weave's rights gate uses);
* **placement sanity**: each placed sound lands within :data:`PLACEMENT_TOLERANCE_S` of its
  trigger. The trigger is read from SELECT's *symbolic* anchor (``"on 'door'"``), which edits
  never erase, and resolved against the timeline's word anchors (``word_timeline``), so a
  nudged, re-aligned or absolute-pinned spot effect shows up as an error. Without woven
  audio the words are evenly spaced estimates (the fake aligner), flagged ``aligned=False``;
* **loudness**: the woven mix's integrated LUFS, re-measured, vs the master target, within
  :data:`LOUDNESS_TOLERANCE_LU` (only for passages that carry narration audio).

The ``designer`` seam: the default, :func:`score_designer`, is ``foley.score`` over the Ring-0
wav fixture with the deterministic fake LLM and generation off, so the eval runs offline in
CI. The point of the harness, though, is the **agent-driven designer**: a fresh agent with
only ``foley`` and the shipped ``foley-sound-design`` skill (``foley.install_agent_kit(dest)``)
given one passage and asked for a sound design. Plug it in as any callable that returns a
:class:`~foley.score.ScoreResult`; the metrics read only ``.timeline`` and ``.weave``, so an
agent that hands back timeline JSON is wrapped as
``ScoreResult(timeline=SoundDesignTimeline.from_dict(d), events=[])``. Pass the ``library``
that agent drew from, so the licence check judges the same records. It is never run in tests.

Fit ("is this the right sound?") is not re-judged here: that is :func:`~foley.eval.fit.run_fit_eval`.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional, Union

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..base import IntendedUse, SoundDesignTimeline, TimelineItem
    from ..score import ScoreResult
    from ..weave import WeaveResult

#: Sane density band (sounds per sentence, inclusive). The ceiling holds per passage: more
#: sounds than sentences is "sound soup". The floor holds over the whole set only, since a
#: quiet passage left quiet is taste, while a designer that scores nothing anywhere is mute.
SOUNDS_PER_SENTENCE_BAND: "tuple[float, float]" = (0.1, 1.0)
#: Share of placed sounds the licence gate must keep. Anything under it is a defect.
LICENCE_CLEAN_TARGET: float = 1.0
#: How far (s) a sound may land from its trigger word. Word aligners are ~±50 ms and a
#: pre-roll is folded back in, so this only flags misplacements, not alignment jitter.
PLACEMENT_TOLERANCE_S: float = 0.25
#: How far (LU) the woven mix may sit from the master target (EBU R128's ±1 LU).
LOUDNESS_TOLERANCE_LU: float = 1.0

DEFAULT_PASSAGES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "taste" / "passages.json"
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

#: ``passage -> ScoreResult``: the seam this eval measures.
Designer = Callable[["Passage"], "ScoreResult"]


# ---------------------------------------------------------------------------
# the passage set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    """One narration passage: its segments (what ``foley.score`` takes) and optional audio.

    ``audio`` (a path, bytes, or a 48 kHz ndarray) makes the default designer weave, which
    is what the loudness metric needs.
    """

    id: str
    segments: "tuple[str, ...]"
    audio: Any = None

    @property
    def text(self) -> str:
        """The passage as one transcript."""
        return " ".join(self.segments)


def load_passages(path=DEFAULT_PASSAGES_PATH) -> "list[Passage]":
    """Load a passage set: a JSON list of ``{id, segments, audio?}``.

    A relative ``audio`` path resolves against the JSON file's folder.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    def _audio(a):
        return str(path.parent / a) if isinstance(a, str) else a

    return [
        Passage(id=p["id"], segments=tuple(p["segments"]), audio=_audio(p.get("audio")))
        for p in raw
    ]


def _as_passages(passages) -> "list[Passage]":
    if passages is None or isinstance(passages, (str, Path)):
        return load_passages(DEFAULT_PASSAGES_PATH if passages is None else passages)
    return [
        p
        if isinstance(p, Passage)
        else Passage(**{**p, "segments": tuple(p["segments"])})
        for p in passages
    ]


def count_sentences(text: str) -> int:
    """Sentences in ``text`` (split after ``.!?``); at least 1 for non-empty text."""
    return len([s for s in _SENTENCE_END.split(text.strip()) if s])


# ---------------------------------------------------------------------------
# the four metrics (pure, one per concern)
# ---------------------------------------------------------------------------


def _finite(x: Optional[float]) -> Optional[float]:
    """``x`` as a JSON-safe float (``None`` for ``None``/±inf/NaN)."""
    return float(x) if x is not None and math.isfinite(x) else None


def _share(flags: "Iterable[bool]") -> Optional[float]:
    flags = list(flags)
    return sum(flags) / len(flags) if flags else None


def _mean(xs: "Iterable[Optional[float]]") -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def restraint(
    n_sounds: int,
    n_sentences: int,
    *,
    band: "tuple[float, float]" = SOUNDS_PER_SENTENCE_BAND,
) -> dict:
    """Sounds per sentence and whether it stays under ``band``'s ceiling (one passage)."""
    density = n_sounds / n_sentences if n_sentences else None
    return {
        "n_sounds": n_sounds,
        "n_sentences": n_sentences,
        "sounds_per_sentence": density,
        "within_ceiling": density is not None and density <= band[1],
    }


def licence_rows(
    items: "Iterable[TimelineItem]", library, intended_use: "IntendedUse"
) -> "list[dict]":
    """One ``{clip_ref, clean, reason}`` row per placed sound, judged by its library record.

    Fail-closed: no readable record is unclean, as in the weave's own rights gate.
    """
    from ..licensing import checked_refusal_reason, placed_record

    def _row(clip_ref):
        record = placed_record(library, clip_ref)
        reason = (
            "no library record"
            if getattr(record, "license", None) is None
            else checked_refusal_reason(record.license, intended_use)
        )
        return {"clip_ref": clip_ref, "clean": reason is None, "reason": reason}

    return [_row(it.clip_ref) for it in items]


def _trigger_s(item: "TimelineItem", word_timeline: "list[dict]") -> Optional[float]:
    """When ``item`` should land: its symbolic anchor resolved on the word timeline.

    ``None`` when it has no trigger (a spot effect with no cue word, or a cue word that is
    not in the narration). A bed with no cue spans the narration, so it triggers at its start.
    """
    from ..base import Anchor
    from ..weave.anchor import nearest_word, parse_symbolic_anchor, resolve_anchor

    intent = parse_symbolic_anchor(item.onset, layer=item.layer, loop=item.loop)
    if intent.ref is None:
        is_bed = intent.anchor is Anchor.sentence
        return float(word_timeline[0]["start"]) if is_bed and word_timeline else None
    if nearest_word(intent.ref, word_timeline) is None:
        return None
    onset, _ = resolve_anchor(replace(intent, pre_roll=0.0), word_timeline)
    return onset


def placement_rows(
    timeline: "SoundDesignTimeline", *, tolerance_s: float = PLACEMENT_TOLERANCE_S
) -> "list[dict]":
    """One row per enabled item of a *hydrated* timeline: trigger vs where it lands.

    The landing time is the resolved onset plus its pre-roll (the transient, not the file
    start). An item with no trigger is ``ok=False`` (``trigger_s=None``): a spot effect
    must hang on a word.
    """
    wt = list(timeline.word_timeline or ())

    def _row(it):
        trigger = _trigger_s(it, wt)
        p = it.placement
        lands = (p.onset + p.pre_roll) if p is not None else None
        error = abs(lands - trigger) if None not in (lands, trigger) else None
        return {
            "clip_ref": it.clip_ref,
            "layer": getattr(it.layer, "value", it.layer),
            "cue": it.onset,
            "trigger_s": trigger,
            "lands_s": lands,
            "error_s": error,
            "ok": error is not None and error <= tolerance_s,
        }

    return [_row(it) for it in timeline.items if it.enabled]


def loudness_row(
    weave: "Optional[WeaveResult]", *, tolerance_lu: float = LOUDNESS_TOLERANCE_LU
) -> Optional[dict]:
    """The woven mix's integrated LUFS (re-measured) vs its master target; ``None`` unwoven."""
    if weave is None:
        return None
    from ..audio import integrated_lufs

    measured = _finite(integrated_lufs(weave.audio, weave.sr))
    target = float(weave.timeline.master.target_lufs)
    delta = None if measured is None else measured - target
    return {
        "lufs": measured,
        "target_lufs": target,
        "delta_lu": delta,
        "ok": delta is not None and abs(delta) <= tolerance_lu,
    }


def _hydrated(timeline: "SoundDesignTimeline", transcript: str):
    """``(timeline, aligned)``: as woven, or hydrated on evenly spaced estimated words."""
    from ..weave.align import FakeAligner
    from ..weave.timeline import hydrate

    if timeline.word_timeline:
        return timeline, True
    words = FakeAligner().word_timeline(None, 0, transcript=transcript)
    return hydrate(timeline, words), False


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


@dataclass
class PassageTaste:
    """The four measurements for one passage (JSON-safe via :meth:`to_dict`)."""

    passage_id: str
    restraint: dict = field(default_factory=dict)
    licence: list = field(default_factory=list)
    placement: list = field(default_factory=list)
    aligned: bool = False
    loudness: Optional[dict] = None
    error: Optional[str] = None

    @property
    def licence_clean_share(self) -> Optional[float]:
        """Share of placed sounds the licence gate keeps (``None`` when nothing was placed)."""
        return _share(r["clean"] for r in self.licence)

    @property
    def placement_ok_share(self) -> Optional[float]:
        """Share of placed sounds within the placement tolerance."""
        return _share(r["ok"] for r in self.placement)

    def to_dict(self) -> dict:
        """Plain, JSON-safe dict (with the derived shares)."""
        return {
            **asdict(self),
            "licence_clean_share": self.licence_clean_share,
            "placement_ok_share": self.placement_ok_share,
        }


@dataclass
class TasteReport:
    """The tasteful-weave eval over a passage set: per passage + aggregated, plus thresholds."""

    designer: str
    passages: "list[PassageTaste]"
    thresholds: dict

    @property
    def _ok(self) -> "list[PassageTaste]":
        return [p for p in self.passages if p.error is None]

    def summary(self) -> dict:
        """The aggregate numbers (pooled over sounds, or over passages for the band/loudness)."""
        ok = self._ok
        n_sounds = sum(p.restraint["n_sounds"] for p in ok)
        n_sentences = sum(p.restraint["n_sentences"] for p in ok)
        licence = [r for p in ok for r in p.licence]
        placement = [r for p in ok for r in p.placement]
        loud = [p.loudness for p in ok if p.loudness is not None]
        clean = _share(r["clean"] for r in licence)
        density = n_sounds / n_sentences if n_sentences else None
        low, high = self.thresholds["sounds_per_sentence_band"]
        return {
            "n_passages": len(self.passages),
            "n_failed": len(self.passages) - len(ok),
            "n_sounds": n_sounds,
            "sounds_per_sentence": density,
            "restraint_in_band": density is not None and low <= density <= high,
            "within_ceiling_share": _share(p.restraint["within_ceiling"] for p in ok),
            "licence_clean_share": clean,
            "licence_target_met": clean is None
            or clean >= self.thresholds["licence_clean_target"],
            "placement_ok_share": _share(r["ok"] for r in placement),
            "placement_mean_abs_error_s": _mean(r["error_s"] for r in placement),
            "aligned_share": _share(p.aligned for p in ok),
            "n_woven": len(loud),
            "loudness_ok_share": _share(r["ok"] for r in loud),
            "loudness_mean_abs_delta_lu": _mean(
                None if r["delta_lu"] is None else abs(r["delta_lu"]) for r in loud
            ),
        }

    def to_dict(self) -> dict:
        """Plain, JSON-safe dict: designer, thresholds, summary, per-passage rows."""
        return {
            "designer": self.designer,
            "thresholds": dict(self.thresholds),
            "summary": self.summary(),
            "passages": [p.to_dict() for p in self.passages],
        }

    def to_markdown(self) -> str:
        """A short markdown rendering: the aggregate table, then one row per passage."""
        s, t = self.summary(), self.thresholds
        low, high = t["sounds_per_sentence_band"]
        lines = [
            f"## Tasteful-weave eval: `{self.designer}` "
            f"({s['n_passages']} passages, {s['n_failed']} failed)",
            "",
            "| metric | value | target |",
            "|---|---|---|",
            f"| restraint (sounds/sentence) | {_fmt(s['sounds_per_sentence'])}"
            f"{'' if s['restraint_in_band'] else ' (out of band)'}; "
            f"{_pct(s['within_ceiling_share'])} of passages ≤ {high} | {low}–{high} |",
            f"| licence cleanliness | {_pct(s['licence_clean_share'])} of "
            f"{s['n_sounds']} sounds | {_pct(t['licence_clean_target'])} |",
            f"| placement sanity | {_pct(s['placement_ok_share'])} within "
            f"{t['placement_tolerance_s']} s (mean err {_fmt(s['placement_mean_abs_error_s'])} s"
            f"{'' if s['aligned_share'] == 1 else ', estimated word timings'}) | 100% |",
            f"| loudness | {_pct(s['loudness_ok_share'])} of {s['n_woven']} woven "
            f"(mean abs Δ {_fmt(s['loudness_mean_abs_delta_lu'])} LU) "
            f"| ±{t['loudness_tolerance_lu']} LU |",
            "",
            "| passage | sounds/sentence | licence | placement | loudness (LUFS) |",
            "|---|---|---|---|---|",
        ]
        for p in self.passages:
            if p.error is not None:
                lines.append(f"| {p.passage_id} | error: {p.error} | | | |")
                continue
            r, loud = p.restraint, p.loudness
            lines.append(
                f"| {p.passage_id} | {r['n_sounds']}/{r['n_sentences']}"
                f"{'' if r['within_ceiling'] else ' (over ceiling)'} | "
                f"{_pct(p.licence_clean_share)} | {_pct(p.placement_ok_share)} | "
                f"{'n/a' if loud is None else _fmt(loud['lufs'])} |"
            )
        return "\n".join(lines)


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


# ---------------------------------------------------------------------------
# the designer seam + the harness
# ---------------------------------------------------------------------------


def eval_library():
    """The offline default library: the Ring-0 wav fixture (6 CC0 clips, wav-backed, so it weaves)."""
    from .golden import RING0_MANIFEST_PATH, build_eval_library

    return build_eval_library(manifest_path=RING0_MANIFEST_PATH)


def score_designer(
    *,
    library=None,
    intended_use=None,
    llm: Optional[str] = "fake",
    generate: bool = False,
    **score_kwargs,
) -> Designer:
    """A designer that is ``foley.score`` on a passage's segments (and audio, when it has some).

    Defaults are the offline, deterministic ones: the fake LLM and no generation fallback
    (``Budget(allow_generate=False, max_usd=0)``), so nothing is fetched, generated or paid.
    ``generate=True`` and ``llm=None`` (``$FOLEY_LLM``) give the production behaviour.
    """
    from ..agent.policy import Budget
    from ..score import score

    def design(passage: Passage) -> "ScoreResult":
        budget = None if generate else Budget(allow_generate=False, max_usd=0.0)
        return score(
            list(passage.segments),
            audio=passage.audio,
            library=library,
            intended_use=intended_use,
            llm=llm,
            budget=budget,
            **score_kwargs,
        )

    design.__name__ = "foley.score"
    return design


def measure_passage(
    passage: Passage,
    result: "ScoreResult",
    *,
    library,
    intended_use: "IntendedUse",
    band: "tuple[float, float]" = SOUNDS_PER_SENTENCE_BAND,
    placement_tolerance_s: float = PLACEMENT_TOLERANCE_S,
    loudness_tolerance_lu: float = LOUDNESS_TOLERANCE_LU,
) -> PassageTaste:
    """Measure one designer result for ``passage`` (reads only ``.timeline`` and ``.weave``)."""
    timeline, aligned = _hydrated(result.timeline, passage.text)
    placed = [it for it in timeline.items if it.enabled]
    return PassageTaste(
        passage_id=passage.id,
        restraint=restraint(len(placed), count_sentences(passage.text), band=band),
        licence=licence_rows(placed, library, intended_use),
        placement=placement_rows(timeline, tolerance_s=placement_tolerance_s),
        aligned=aligned,
        loudness=loudness_row(result.weave, tolerance_lu=loudness_tolerance_lu),
    )


def run_taste_eval(
    passages: "Union[None, str, Path, Iterable]" = None,
    *,
    designer: Optional[Designer] = None,
    library=None,
    intended_use=None,
    band: "tuple[float, float]" = SOUNDS_PER_SENTENCE_BAND,
    licence_clean_target: float = LICENCE_CLEAN_TARGET,
    placement_tolerance_s: float = PLACEMENT_TOLERANCE_S,
    loudness_tolerance_lu: float = LOUDNESS_TOLERANCE_LU,
) -> TasteReport:
    """Run ``designer`` over ``passages`` and report restraint / licence / placement / loudness.

    Report-only: nothing here fails a build. A passage whose designer raises is recorded
    with its error and left out of the aggregates.

    Args:
        passages: The passage set: ``None`` (the shipped set), a JSON path, or an iterable
            of :class:`Passage` / ``{id, segments, audio?}`` dicts.
        designer: ``passage -> ScoreResult`` (default: :func:`score_designer` over ``library``).
        library: The library the designer draws from, used for the licence check. Default:
            :func:`eval_library` with the default designer, else ``foley``'s default library.
        intended_use: The rights intent (default: commercial publishing, as ``foley.score``).
        band / licence_clean_target / placement_tolerance_s / loudness_tolerance_lu: The
            thresholds (defaults: the module constants); echoed in the report.

    Returns:
        A :class:`TasteReport` (``to_dict()`` for JSON, ``to_markdown()`` for people).
    """
    from ..licensing import intended_use_for

    use = intended_use_for(intended_use)
    if library is None:
        if designer is None:
            library = eval_library()
        else:
            from ..index import default_library

            library = default_library()
    designer = designer or score_designer(library=library, intended_use=use)
    measure = dict(
        library=library,
        intended_use=use,
        band=band,
        placement_tolerance_s=placement_tolerance_s,
        loudness_tolerance_lu=loudness_tolerance_lu,
    )

    def _one(passage: Passage) -> PassageTaste:
        try:
            return measure_passage(passage, designer(passage), **measure)
        except Exception as exc:  # report, don't gate: one bad passage keeps the rest
            return PassageTaste(
                passage_id=passage.id, error=f"{type(exc).__name__}: {exc}"
            )

    return TasteReport(
        designer=getattr(designer, "__name__", type(designer).__name__),
        passages=[_one(p) for p in _as_passages(passages)],
        thresholds={
            "sounds_per_sentence_band": list(band),
            "licence_clean_target": licence_clean_target,
            "placement_tolerance_s": placement_tolerance_s,
            "loudness_tolerance_lu": loudness_tolerance_lu,
        },
    )
