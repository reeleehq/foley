"""The SELECT orchestration: ``find()`` / ``plan()`` + the small pure tool wrappers.

This is the one seam that serves the Python API, the agent loop, and the future MCP
server (#12) — the same functions, three surfaces (report 05 §5.2). It OWNS every
side-effecting call (``search`` → ``gate`` → ``verify`` → ``decide`` → ``generate`` →
``place``); :func:`~foley.agent.policy.decide` is a pure tail step that only branches.

``find()`` opens **one** ``foley.obs.run('find')`` scope, so the nested
:func:`foley.search` / :func:`foley.generate` façade calls aggregate into a single
reproducible run-manifest (report 10 §1.3); each stage emits a typed
:class:`~foley.obs.run_artifact.Step` and each LLM rung a GenAI span. The plan it emits
is the **sparse** :class:`~foley.base.SoundDesignTimeline` subset — WEAVE (#8) resolves
anchors, mix, and mastering.

``import foley`` stays dol-only: ``foley.search`` / ``foley.generate`` and the
generation-error hierarchy are imported lazily inside the functions that call them.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterator, Optional, Union

from ..base import (
    Candidate,
    IntendedUse,
    Layer,
    SoundDesignTimeline,
    TimelineItem,
    VerifyLevel,
)
from ..index import RRF_K, default_library
from ..obs.recorder import current_run
from ..obs.recorder import run as _obs_run
from ..obs.run_artifact import Step
from .decompose import decompose_context, _default_decomposer
from ..licensing import intended_use_for
from .policy import Budget, DecideAction, decide, gate_candidates
from .refine import refine_query, _default_refiner
from .verify import _default_judge, verify_match

# ---------------------------------------------------------------------------
# small pure tool wrappers (Python-API == agent == future MCP surface)
# ---------------------------------------------------------------------------


def _license_prefilter(intended_use: IntendedUse) -> "Optional[dict]":
    """Map an :class:`IntendedUse` to search filters — a retrieval pushdown OPTIMIZATION.

    Narrows the shortlist so fewer license-incompatible clips are fetched; it is NOT the
    authoritative gate (:func:`~foley.agent.policy.gate_candidates` is). Returns ``None``
    when nothing needs pushing down.
    """
    f: dict = {}
    if intended_use.commercial:
        f["commercial_ok"] = True
    return f or None


def search_sounds(
    queries: "Union[str, list[str]]",
    *,
    k: int = 10,
    library=None,
    filters: "Optional[dict]" = None,
) -> "list[Candidate]":
    """Hybrid search for one query, or a multi-query RRF-merge (the SELECT retrieval tool).

    Delegates a single query VERBATIM to :meth:`SoundLibrary.search` (so the retrieval
    ranking the nDCG@10 gate measures is untouched); a multi-query list runs each query
    and RRF-merges (``k=RRF_K``) — the query-expansion recall lever, exercised only on a
    refine pass.

    Args:
        queries: One query string, or a list of paraphrases to merge.
        k: Number of results.
        library: Target library (default: the process-wide default).
        filters: Extra :meth:`SoundLibrary.search` kwargs (e.g. the license prefilter).
    """
    library = library if library is not None else default_library()
    if isinstance(queries, str):
        queries = [queries]
    kw = dict(filters or {})
    if len(queries) == 1:
        return library.search(queries[0], k=k, **kw)
    result_lists = [library.search(q, k=k, **kw) for q in queries]
    return _rrf_merge(result_lists, k)


def _rrf_merge(result_lists: "list[list[Candidate]]", k: int) -> "list[Candidate]":
    """Reciprocal-rank-fuse several ranked candidate lists into one top-``k`` (``k=RRF_K``)."""
    scores: "dict[str, float]" = {}
    best: "dict[str, Candidate]" = {}
    for hits in result_lists:
        for rank, c in enumerate(hits):
            sid = c.sound.id
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (RRF_K + rank + 1)
            best.setdefault(sid, c)
    ordered = sorted(best.values(), key=lambda c: scores[c.sound.id], reverse=True)
    for c in ordered:
        c.rrf_score = scores[c.sound.id]
    return ordered[:k]


def generate_sound(query: str, *, backend: str = "auto", library=None) -> Candidate:
    """Generate a clip for ``query`` (the fallback tool) — a thin wrapper over ``foley.generate``.

    Returns a :class:`Candidate` (``origin=generated``); raises the ``GenerationError``
    hierarchy on refusal / no-result (caught fail-closed by :func:`_generate_and_reverify`).
    """
    import foley  # lazy: avoids the foley → foley.agent import cycle at module load

    kw = {} if backend == "auto" else {"backend": backend}
    return foley.generate(query, library=library, **kw)


def place_in_timeline(
    clip: Candidate,
    *,
    onset: "Optional[str]" = None,
    gain: float = 0.0,
    layer: "Union[str, Layer]" = Layer.sfx_fg,
    loop: bool = False,
) -> TimelineItem:
    """Emit the SPARSE per-item plan subset (``clip_ref·onset·gain·layer·loop``) — no more.

    ``onset`` stays a SYMBOLIC anchor string (never a resolved offset); mix / processing /
    alignment / mastering are WEAVE's (#8) job, not SELECT's.
    """
    return TimelineItem(
        clip_ref=clip.sound.id,
        onset=onset,
        gain=gain,
        layer=Layer(layer) if isinstance(layer, str) else layer,
        loop=loop,
    )


# ---------------------------------------------------------------------------
# obs step helpers
# ---------------------------------------------------------------------------


def _emit_step(
    run, kind: str, *, event_index: "Optional[int]" = None, span=None, detail=None
) -> None:
    """Append a typed :class:`Step` (``seq`` auto-assigned; ``detail`` redacted at record time)."""
    run.add_step(
        Step(
            kind=kind,
            event_index=event_index,
            span_id=getattr(span, "span_id", None),
            detail=detail or {},
        )
    )


def _verify_kept(
    run, event, kept, *, event_index, max_level, judge, tau_clap
) -> "list[Candidate]":
    """Run the verify ladder over each license-clean candidate; return the matches.

    Opens ONE child span per candidate (``CLIENT`` on the LLM rungs so each judged clip
    gets its own GenAI-attributed span — 1 call : 1 span, like decompose/refine;
    ``INTERNAL`` for the zero-cost ``clap`` rung). Records a ``verify`` Step per candidate
    (match/confidence/level only — the LLM's free-text ``reason`` is NOT persisted, since
    it can echo the query and is not a redacted key).
    """
    verified: "list[Candidate]" = []
    span_kind = "CLIENT" if max_level != VerifyLevel.clap else "INTERNAL"
    for c in kept:
        with run.span("verify_match", kind=span_kind) as sp:
            verdict = verify_match(
                event, c, level=max_level, judge=judge, tau_clap=tau_clap, _span=sp
            )
        c.verdict = verdict
        _emit_step(
            run,
            "verify",
            event_index=event_index,
            span=sp,
            detail={
                "candidate_id": c.sound.id,
                "level": verdict.level.value,
                "match": verdict.match,
                "confidence": verdict.confidence,
            },
        )
        if verdict.match:
            verified.append(c)
    return verified


def _score_row(c: Candidate) -> dict:
    """A leak-free candidate-score row for ``RunManifest.candidate_scores`` (ids + scores only)."""
    return {
        "id": c.sound.id,
        "clap": c.clap_score,
        "bm25": c.bm25_score,
        "rrf": c.rrf_score,
        "rerank": c.rerank_score,
    }


# ---------------------------------------------------------------------------
# the generate-and-re-verify fallback (loop-owned side effect)
# ---------------------------------------------------------------------------


def _generate_and_reverify(
    event,
    intended_use: IntendedUse,
    *,
    backend: str,
    judge,
    level: VerifyLevel,
    library,
    llm: "Optional[str]" = None,
) -> "Optional[Candidate]":
    """Generate a clip, then RE-GATE + RE-VERIFY it before acceptance (the flywheel admission gate).

    A generated clip is not pre-vetted: it must pass the SAME fail-closed license gate
    (generations keep ``ai_training_ok=False``) and the SAME verify ladder as a retrieved
    one before it is accepted into the plan. The generation-error hierarchy
    (``TrademarkRefusal`` / ``RecognizableVoiceRefusal`` < ``SafetyRefusal`` <
    ``GenerationError``) is caught fail-closed → the event is skipped, ``find()`` continues.
    Handles the ``skipped_dup`` byte-twin (a bare ``Candidate`` with event/verdict/​license
    unset — still gated + verified here, never assumed pre-vetted).
    """
    from ..cost import BudgetExceeded
    from ..runtime import EgressBlocked
    from ..sources import GenerationError  # lazy: keeps import foley dol-only

    from ..sources.base import SourceConfigurationError

    try:
        gc = generate_sound(event.query, backend=backend, library=library)
    except (BudgetExceeded, SourceConfigurationError) as exc:
        # Generation is find's optional fallback: an exhausted enclosing budget, or a
        # backend that is not set up (no key, no plan, extra not installed), skips it —
        # loudly, since nothing was generated — and find falls back to retrieval.
        import warnings

        warnings.warn(f"generation skipped: {exc}", UserWarning, stacklevel=2)
        return None
    except EgressBlocked as exc:
        # Offline: an external backend, or a local one whose weights are not cached.
        import warnings

        warnings.warn(f"generation skipped: {exc}", UserWarning, stacklevel=2)
        return None
    except GenerationError:
        # Refused or failed: skip generation; find falls back to the best verified
        # retrieval.
        return None
    gc.event = event  # (origin is already 'generated' from foley.generate)
    if not gate_candidates([gc], intended_use):
        return None
    # A generated clip has no retrieval clap_score to gate on, so re-verify at the
    # 'listen' rung (an audio/judge rung) even when find(verify='clap') — otherwise the
    # clap gate would drop EVERY generation (emptying all non-diegetic output). At
    # verify='clap' the injected judge is the ClapJudge (no use here), so resolve a
    # listen-capable one; higher rungs keep the caller's judge.
    if level == VerifyLevel.clap:
        reverify_level, reverify_judge = (
            VerifyLevel.listen,
            _default_judge(VerifyLevel.listen, llm),
        )
    else:
        reverify_level, reverify_judge = level, judge
    verdict = verify_match(event, gc, level=reverify_level, judge=reverify_judge)
    gc.verdict = verdict
    return gc if verdict.match else None


# ---------------------------------------------------------------------------
# the headline: find() / plan()
# ---------------------------------------------------------------------------


def find(
    context: str,
    *,
    max_events: int = 6,
    seconds: "Optional[float]" = None,
    intended_use: "Optional[IntendedUse]" = None,
    backend: str = "auto",
    verify: "Union[str, VerifyLevel]" = "listen",
    stream: bool = False,
    k: int = 10,
    tau_retrieve: float = 0.5,
    tau_clap: float = 0.35,
    max_refine_loops: int = 1,
    budget: "Optional[Budget]" = None,
    library=None,
    decomposer=None,
    judge=None,
    refiner=None,
    llm: "Optional[str]" = None,
) -> "Union[list[Candidate], Iterator[Candidate]]":
    """The headline: a narrative context → verified, license-clean sound candidates.

    ``decompose → (per event) refine/search → verify_match ladder → decide (with the
    fail-closed license gate FIRST) → place`` (report 05 §5). Works out of the box —
    ``foley.find("She pushed open the heavy oak door; rain hammered outside.")`` — with
    deterministic defaults; every model / threshold / seam is an optional keyword.

    Args:
        context: The narrative passage.
        max_events: The sparse density cap on decomposed events.
        seconds: Optional passage duration (density-window hint; forwarded).
        intended_use: The caller's rights intent (default:
            :data:`foley.licensing.DEFAULT_INTENDED_USE` — commercial publishing;
            NC / SA material is refused unless you pass a different intent).
        backend: Generation backend for the fallback (``'auto'`` → ``foley.generate``'s default).
        verify: The max verify rung — ``'clap'`` | ``'listen'`` | ``'judge'``.
        stream: If ``True``, return a generator yielding one :class:`Candidate` per
            resolved event; else return the collected ``list``.
        k: Retrieval shortlist depth per query.
        tau_retrieve: Confidence threshold to auto-accept a retrieved clip.
        tau_clap: The ``clap``-rung gate threshold.
        max_refine_loops: Max refine→re-retrieve passes per event (also the default
            :class:`Budget`).
        budget: An explicit :class:`Budget` (overrides ``max_refine_loops``). It is
            also the run's spend cap: ``Budget(max_usd=...)`` (default $1; $3 when
            ``llm='anthropic'`` or ``$FOLEY_LLM=anthropic``, whose default run is
            bounded at about $2.52 — :data:`foley.cost.DEFAULT_MAX_USD_BY_LLM`) bounds
            every paid call the run makes — generations and paid LLM rungs —
            cumulatively, and a call of unknown cost needs
            ``Budget(approve_unknown_cost=True)`` (#57).
        library: Target :class:`SoundLibrary` (default: the process-wide default).
        decomposer / judge / refiner: Injected DI seams
            (:class:`~foley.agent.protocols.Decomposer` / ``Judge`` / ``Refiner``);
            each defaults to the ``llm`` provider's implementation.
        llm: Which LLM the decompose / refine / judge rungs use when not injected —
            ``'fake'`` | ``'local'`` | ``'anthropic'``. ``None`` reads ``$FOLEY_LLM``,
            then falls back to the free default (a configured local endpoint, else the
            deterministic fake). A key being present never opts in to paid calls.

    Returns:
        ``list[Candidate]`` (``stream=False``) or an ``Iterator[Candidate]``
        (``stream=True``) — one verified, license-clean candidate per resolved event.
    """
    gen = _find_stream(
        context,
        max_events=max_events,
        seconds=seconds,
        intended_use=intended_use,
        backend=backend,
        verify=verify,
        k=k,
        tau_retrieve=tau_retrieve,
        tau_clap=tau_clap,
        max_refine_loops=max_refine_loops,
        budget=budget,
        library=library,
        decomposer=decomposer,
        judge=judge,
        refiner=refiner,
        llm=llm,
    )
    return gen if stream else list(gen)


def _find_stream(
    context,
    *,
    max_events,
    seconds,
    intended_use,
    backend,
    verify,
    k,
    tau_retrieve,
    tau_clap,
    max_refine_loops,
    budget,
    library,
    decomposer,
    judge,
    refiner,
    llm=None,
) -> "Iterator[Candidate]":
    """The streaming body of :func:`find` (``find(stream=False)`` == ``list(_find_stream(...))``)."""
    from ..cost import check, default_max_usd, scoped_iter

    use = intended_use_for(intended_use)
    budget = budget or Budget(
        max_refine_loops=max_refine_loops, max_usd=default_max_usd(llm)
    )

    def run():
        # Before the first paid call: the whole run's upper bound must fit every
        # budget in force (#57's acceptance), else nothing is spent. A check, not a
        # reservation: each call reserves its own cost when it is made.
        check(
            estimate_find_usd(
                max_events=max_events,
                backend=backend,
                llm=llm,
                k=k,
                verify=verify,
                max_refine_loops=budget.max_refine_loops,
                max_generations=budget.max_generations if budget.allow_generate else 0,
                context_chars=len(context),
                injected={
                    "decomposer": decomposer is not None,
                    "refiner": refiner is not None,
                    "judge": judge is not None,
                },
            ),
            what=f"this find run (upper bound for {max_events} events)",
        )
        return _find_events(
            context,
            use=use,
            budget=budget,
            max_events=max_events,
            seconds=seconds,
            backend=backend,
            verify=verify,
            k=k,
            tau_retrieve=tau_retrieve,
            tau_clap=tau_clap,
            library=library,
            decomposer=decomposer,
            judge=judge,
            refiner=refiner,
            llm=llm,
        )

    # The budget is in force only while the stream runs, never between items.
    yield from scoped_iter(run, budget)


def estimate_find_usd(
    *,
    max_events: int = 6,
    backend: str = "auto",
    llm: "Optional[str]" = None,
    k: int = 10,
    verify: str = "listen",
    max_refine_loops: int = 1,
    max_generations: int = 1,
    injected: "Optional[dict]" = None,
    context_chars: int = 0,
) -> "Optional[float]":
    """An upper bound on what one :func:`find` run can spend, or ``None`` if unknown.

    Every generation (``max_generations`` per event through ``backend``) plus every
    LLM call the default rungs could make: one decomposition, ``max_refine_loops``
    refinements per event, ``k`` judge calls per retrieval pass above the ``clap``
    rung, and one re-verification per generation. Injected rungs are the caller's to
    meter (their real calls are still checked one by one).
    """
    from ..sources._dispatch import estimate_generation
    from .llm import RUNG_MAX_TOKENS, llm_call_estimate, resolve_llm

    injected = injected or {}
    provider = resolve_llm(llm)
    per_gen = 0.0
    if max_generations:
        name = "stable_audio" if backend == "auto" else backend
        per_gen = estimate_generation(name)
    calls = {
        "decomposer": 0 if injected.get("decomposer") else 1,
        "refiner": 0 if injected.get("refiner") else max_events * max_refine_loops,
        "judge": 0
        if injected.get("judge")
        else max_events
        * (
            (max_refine_loops + 1)
            * (k if VerifyLevel(verify) != VerifyLevel.clap else 0)
            + max_generations
        ),
    }
    total = 0.0 if per_gen is None else max_events * max_generations * per_gen
    if per_gen is None:
        return None
    for kind, n in calls.items():
        if not n:
            continue
        extra = context_chars if kind == "decomposer" else 0  # the passage goes to it
        each = llm_call_estimate(
            provider, max_tokens=RUNG_MAX_TOKENS[kind], kind=kind, input_chars=extra
        )
        if each is None:
            return None
        total += n * each
    return total


def _find_events(
    context,
    *,
    use,
    budget,
    max_events,
    seconds,
    backend,
    verify,
    k,
    tau_retrieve,
    tau_clap,
    library,
    decomposer,
    judge,
    refiner,
    llm,
) -> "Iterator[Candidate]":
    """The per-event loop of :func:`find`, run inside the run's spend scope."""
    library = library if library is not None else default_library()
    decomposer = decomposer or _default_decomposer(llm)
    max_level = VerifyLevel(verify)
    judge = judge or _default_judge(max_level, llm)
    refiner = refiner or _default_refiner(llm)
    prefilter = _license_prefilter(use)

    with _obs_run(
        "find",
        inputs={"context_text": context},
        params={
            "max_events": max_events,
            "verify": max_level.value,
            "backend": backend,
            "k": k,
            "tau_retrieve": tau_retrieve,
        },
    ) as run:
        with run.span("decompose_context", kind="CLIENT") as sp:
            events = decompose_context(
                context,
                max_events=max_events,
                seconds=seconds,
                decomposer=decomposer,
                _span=sp,
            )
            _emit_step(run, "decompose", span=sp, detail={"n_events": len(events)})

        for i, event in enumerate(events):
            budget.reset()  # per-event caps: a hard event never starves later ones
            chosen: "Optional[Candidate]" = None
            queries = [event.query]
            last_reason: "Optional[str]" = None
            loop = 0
            while True:
                if loop > 0:
                    with run.span("refine_query", kind="CLIENT") as sp:
                        queries = refine_query(
                            event.query,
                            n=3,
                            hint=last_reason,
                            refiner=refiner,
                            _span=sp,
                        )
                        _emit_step(
                            run,
                            "refine",
                            event_index=i,
                            span=sp,
                            detail={"query": event.query, "n": len(queries)},
                        )

                cands = search_sounds(queries, k=k, library=library, filters=prefilter)
                run.add_candidate_scores([_score_row(c) for c in cands])
                _emit_step(
                    run,
                    "search",
                    event_index=i,
                    detail={
                        "query": event.query,
                        "n_hits": len(cands),
                        "candidate_ids": [c.sound.id for c in cands],
                    },
                )

                kept = gate_candidates(cands, use)
                _emit_step(
                    run,
                    "license_gate",
                    event_index=i,
                    detail={
                        "n_in": len(cands),
                        "n_kept": len(kept),
                        "rejected_ids": [
                            c.sound.id for c in cands if c.license_ok is not True
                        ],
                        "intended_use": asdict(use),
                    },
                )

                verified = _verify_kept(
                    run,
                    event,
                    kept,
                    event_index=i,
                    max_level=max_level,
                    judge=judge,
                    tau_clap=tau_clap,
                )

                decision = decide(
                    event,
                    kept,
                    verified,
                    tau_retrieve=tau_retrieve,
                    budget=budget,
                    loop=loop,
                )
                _emit_step(
                    run,
                    "decide",
                    event_index=i,
                    detail={
                        "action": decision.action.value,
                        "reason": decision.reason,
                        "chosen_id": decision.candidate.sound.id
                        if decision.candidate
                        else None,
                        "loop": loop,
                    },
                )

                if decision.action is DecideAction.USE:
                    chosen = decision.candidate
                    break
                if decision.action is DecideAction.REFINE and budget.refine_ok():
                    budget.spend_refine()
                    last_reason = decision.reason
                    loop += 1
                    continue
                if decision.action is DecideAction.GENERATE and budget.gen_ok():
                    budget.spend_gen()
                    chosen = _generate_and_reverify(
                        event,
                        use,
                        backend=backend,
                        judge=judge,
                        level=max_level,
                        library=library,
                        llm=llm,
                    )
                    if chosen is None and verified:
                        # Generation yielded nothing (backend unavailable/offline,
                        # QC-quarantined, or safety-refused): fall back to the best verified
                        # retrieval rather than dropping a usable clip — the same best-effort
                        # pick decide() makes when generation is off. Without this, per-event
                        # budgets would make results WORSE wherever generation can't run.
                        chosen = max(
                            verified,
                            key=lambda c: c.verdict.confidence if c.verdict else 0.0,
                        )
                    _emit_step(
                        run,
                        "generate",
                        event_index=i,
                        detail={"query": event.query, "accepted": chosen is not None},
                    )
                    break
                break  # DROP / exhausted → silence (a valid Foley choice)

            if chosen is not None:
                chosen.event = (
                    event  # attach provenance so plan() reads onset/layer/loop
                )
                item = place_in_timeline(
                    chosen,
                    onset=event.onset,
                    gain=0.0,
                    layer=event.layer.value,
                    loop=event.loop,
                )
                _emit_step(run, "place", event_index=i, detail=item.to_dict())
                yield chosen

        run.set_status("ok")


def plan(
    candidates: "list[Candidate]", *, transcript: "Optional[str]" = None
) -> SoundDesignTimeline:
    """Fold verified candidates into the SPARSE :class:`SoundDesignTimeline` (the SELECT→WEAVE bridge).

    One :class:`TimelineItem` per candidate (``onset·gain·layer·loop`` only, from its
    :class:`SoundEvent`), joined to the run-artifact via ``run_manifest_ref`` — the
    reserved #8 ``plan_ref`` slot is filled when called inside an active ``foley.obs``
    run scope (``None``-safe otherwise).

    Args:
        candidates: The candidates returned by :func:`find`.
        transcript: Optional narration transcript (WEAVE resolves the reference).
    """
    run = current_run()
    run_id = getattr(getattr(run, "manifest", None), "run_id", None)
    items = [
        place_in_timeline(
            c,
            onset=(c.event.onset if c.event else None),
            layer=(c.event.layer if c.event else Layer.sfx_fg),
            loop=(c.event.loop if c.event else False),
        )
        for c in candidates
    ]
    timeline = SoundDesignTimeline(
        items=items,
        run_manifest_ref=run_id,
        transcript_ref="narration" if transcript else None,
    )
    run.set_plan_ref({"n_items": len(items), "run_manifest_ref": run_id})
    return timeline
