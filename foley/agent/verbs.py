"""foley's JSON-safe verbs: the one table the MCP server and the CLI are built from (#62).

Each verb is a plain function, JSON in and JSON out, a thin call into the façade: it
takes and returns only JSON (ids, scores, licence summaries, timeline dicts, store keys),
never a :class:`~foley.base.Candidate`, a :class:`~foley.weave.WeaveResult` or numpy
audio. :data:`VERBS` lists them with the surfaces they are on: :mod:`foley.agent.mcp`
serves them as MCP tools, :func:`foley.cli.build_parser` as ``foley`` commands, and
:func:`surface_snapshot` pins what both expose.

The verbs share one injectable state (the library, the session factory, the byte store,
the bound runtime, the server's spend budget), set by :func:`_configure`. Nothing here
imports a surface library: ``py2mcp`` / ``fastmcp`` load inside
:func:`foley.agent.mcp.build_mcp_server` only, ``cw`` inside the CLI.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ..licensing import DEFAULT_INTENDED_USE, intended_use_for

# ---------------------------------------------------------------------------
# injectable shared state (a default library + session factory; overridden in tests)
# ---------------------------------------------------------------------------

_STATE: dict = {
    "library": None,
    "session_factory": None,
    "byte_store": None,
    "runtime": None,
    "max_usd": None,  # the server's spend cap; None -> foley.cost.DEFAULT_MAX_USD
    "budget": None,  # ONE budget for the server's lifetime: every paid tool call (#57)
}


def _configure(
    *, library=None, session_factory=None, byte_store=None, runtime=None, max_usd=None
):
    """Set the shared library / session-factory / byte-store / runtime / spend cap (seam)."""
    for key, val in (
        ("library", library),
        ("session_factory", session_factory),
        ("byte_store", byte_store),
        ("runtime", runtime),
        ("max_usd", max_usd),
    ):
        if val is not None:
            _STATE[key] = val
    if max_usd is not None and _STATE["budget"] is not None:
        _STATE["budget"].max_usd = max_usd


_BUDGET_LOCK = threading.Lock()


def _server_budget():
    """The server's one spend budget: every paid call any tool makes counts against it.

    Keyed on the server, not on the ``session`` argument (which the calling agent
    chooses, so a per-session cap could be dodged by inventing session ids). The cap
    is set by whoever starts the server (``build_mcp_server(max_usd=...)``) and lasts
    for the server's lifetime; restart the server to reset it. Unset, it is
    :func:`foley.cost.default_max_usd` ($1, or $3 under ``$FOLEY_LLM=anthropic``, #88).
    """
    from ..cost import default_max_usd
    from .policy import Budget

    with _BUDGET_LOCK:  # tools run in a threadpool: one budget, even on a first burst
        if _STATE["budget"] is None:
            cap = _STATE["max_usd"]
            _STATE["budget"] = Budget(max_usd=default_max_usd() if cap is None else cap)
        return _STATE["budget"]


def _lib():
    if _STATE["library"] is not None:
        return _STATE["library"]
    from ..index.library import default_library

    return default_library()


def _session(session_id: str):
    if _STATE["session_factory"] is not None:
        return _STATE["session_factory"](session_id)
    from .session import SessionStore

    return SessionStore(session_id)


def _byte_store():
    if _STATE["byte_store"] is not None:
        return _STATE["byte_store"]
    from ..stores import make_byte_store

    _STATE["byte_store"] = make_byte_store()
    return _STATE["byte_store"]


def _runtime():
    if _STATE["runtime"] is not None:
        return _STATE["runtime"]
    from ..runtime import current_runtime

    return current_runtime()


# ---------------------------------------------------------------------------
# JSON-safe projections (compact — never the leaky full to_dict())
# ---------------------------------------------------------------------------


def _enum(x):
    return x.value if hasattr(x, "value") else x


#: The rights fields every MCP candidate row carries (#63): the full TASL attribution
#: (title is the row's caption) plus every derived permission flag, so an MCP caller can
#: attribute and decide without a second lookup.
_LICENSE_ROW_FIELDS = (
    "license_id",
    "license_name",
    "license_url",
    "creator_name",
    "creator_url",
    "source",
    "source_id",
    "source_url",
    "attribution_text",
    "requires_attribution",
    "commercial_ok",
    "embed_in_derivative_ok",
    "redistribute_standalone_ok",
    "cache_bytes_ok",
    "modification_ok",
    "ai_training_ok",
    "ai_training_scope",
    "revenue_cap_usd",
    "rights_verified",
    "is_ai_generated",
    "generator_model",
    "disclosure_recommended",
)


def _license_summary(lic) -> dict:
    """A JSON-safe licence row: full TASL + every derived flag (see ``_LICENSE_ROW_FIELDS``).

    ``license_name`` / ``license_url`` fall back to the licence table's display row
    when the source did not supply them, so attribution always has a deed to link.
    """
    from ..licensing import license_meta

    row = {f: _enum(getattr(lic, f, None)) for f in _LICENSE_ROW_FIELDS}
    meta = license_meta(row["license_id"] or "unknown")
    row["license_name"] = row["license_name"] or meta.display_name
    row["license_url"] = row["license_url"] or meta.url
    return row


def _candidate_row(c) -> dict:
    """Project a :class:`~foley.base.Candidate` to a compact JSON row.

    Deliberately omits the leaky internals (``storage_mode`` / ``uri`` / QC block /
    embeddings) — only what an agent needs to audition and decide.
    """
    s = c.sound
    verdict = None
    if c.verdict is not None:
        verdict = {
            "match": getattr(c.verdict, "match", None),
            "confidence": getattr(c.verdict, "confidence", None),
            "level": _enum(getattr(c.verdict, "level", None)),
        }
    return {
        "id": s.id,
        "caption": s.caption,
        "tags": list(s.tags or []),
        "duration_s": s.duration_s,
        "ucs_category": s.ucs_category,
        "origin": _enum(c.origin),
        "scores": {
            "clap": c.clap_score,
            "bm25": c.bm25_score,
            "rrf": c.rrf_score,
            "rerank": c.rerank_score,
        },
        "verdict": verdict,
        "license": _license_summary(s.license),
        "license_ok": c.license_ok,
        "preview_uri": c.preview_uri,
    }


def _weave_result_row(result) -> dict:
    """Project a :class:`~foley.weave.WeaveResult` to JSON: audio by store key, no ndarray."""
    audio_ref = None
    try:
        from ..audio import encode
        from ..stores import content_key

        data = encode(result.audio, result.sr, fmt="flac")
        audio_ref = content_key(data)
        _byte_store()[audio_ref] = data
    except Exception:
        audio_ref = None
    credits = getattr(result.credits, "entries", ())
    return {
        "audio_ref": audio_ref,
        "sr": result.sr,
        "timeline": result.timeline.to_dict(),
        "credits": [e.to_dict() if hasattr(e, "to_dict") else e for e in list(credits)],
        "captions_vtt": result.captions_vtt,
        "captions_srt": result.captions_srt,
        "master_report": result.master_report,
        "watermark": result.watermark,
        "content_credential": result.content_credential,
        "run_manifest_ref": result.run_manifest_ref,
        "notes": list(getattr(result, "notes", ())),
    }


# ---------------------------------------------------------------------------
# the tools (module-level, JSON in/out) — the MCP surface
# ---------------------------------------------------------------------------


def foley_find(
    context: str,
    max_events: int = 6,
    verify: str = "listen",
    commercial_ok: bool = DEFAULT_INTENDED_USE.commercial,
    k: int = 10,
    session: str = "default",
    territory: Optional[str] = None,
) -> list:
    """Find verified, license-clean sound candidates for a narrative passage.

    Caches the full candidates in the session so ``foley_plan`` / ``foley_weave`` can
    rehydrate them by id. Returns compact candidate rows. ``territory``: where the
    sound is used (an ISO country code, or ``"WORLD"`` for online publishing); a
    licence that excludes territories is refused while it is unstated.
    """
    from .. import find
    from ..cost import BudgetExceeded, spend_scope

    try:
        use = intended_use_for(commercial_ok=commercial_ok, territory=territory)
    except ValueError as exc:  # a territory that is not a code: a JSON row, no raise
        return [_invalid(exc)]
    try:
        with spend_scope(_server_budget()):
            cands = list(
                find(
                    context,
                    max_events=max_events,
                    verify=verify,
                    k=k,
                    intended_use=use,
                    library=_lib(),
                )
            )
    except BudgetExceeded as exc:
        # Refused before any paid call: say why, as a JSON row (like foley_generate).
        return [{"ok": False, "status": "refused", "error": str(exc)}]
    _session(session).cache_candidates(cands)
    return [_candidate_row(c) for c in cands]


def foley_search(
    query: str,
    k: int = 10,
    commercial_ok: bool = DEFAULT_INTENDED_USE.commercial,
    ucs_category: Optional[str] = None,
    rerank: bool = False,
    session: str = "default",
) -> list:
    """Hybrid (CLAP + keyword) search of the library for a text query; returns candidate rows."""
    hits = _lib().search(
        query,
        k=k,
        commercial_ok=commercial_ok or None,
        ucs_category=ucs_category,
        rerank=rerank,
    )
    _session(session).cache_candidates(hits)
    return [_candidate_row(c) for c in hits]


def foley_similar_to(
    sound_id: str,
    k: int = 10,
    commercial_ok: bool = DEFAULT_INTENDED_USE.commercial,
    session: str = "default",
) -> list:
    """ "More like this" — the library neighbours of a sound (by id); returns candidate rows."""
    from .preview import similar_to

    hits = similar_to(sound_id, k=k, library=_lib())
    if commercial_ok:
        hits = [
            c
            for c in hits
            if c.sound.license.commercial_ok and c.sound.license.rights_verified
        ]
    _session(session).cache_candidates(hits)
    return [_candidate_row(c) for c in hits]


def foley_preview(sound_id: str, seconds: int = 6, session: str = "default") -> dict:
    """Produce a short audition of a sound; returns its store key (never audio bytes)."""
    from .preview import preview

    cand = preview(sound_id, seconds=seconds, library=_lib(), byte_store=_byte_store())
    return {
        "sound_id": sound_id,
        "preview_uri": cand.preview_uri,
        "duration_s": cand.sound.duration_s,
        "caption": cand.sound.caption,
    }


def foley_refine(
    session: str = "default",
    query: Optional[str] = None,
    picked_ids: Optional[list] = None,
    rejected_ids: Optional[list] = None,
    hint: Optional[str] = None,
    k: int = 10,
) -> dict:
    """Relevance-feedback refinement: expand the query, boost picks, drop rejects, re-rank."""
    from .preview import refine

    sess = _session(session)
    res = refine(
        sess,
        query=query,
        picked_ids=tuple(picked_ids or ()),
        rejected_ids=tuple(rejected_ids or ()),
        hint=hint,
        k=k,
        library=_lib(),
    )
    sess.cache_candidates(res.results)
    return {"queries": res.queries, "results": [_candidate_row(c) for c in res.results]}


def foley_pick(
    sound_id: str,
    session: str = "default",
    layer: Optional[str] = None,
    onset: Optional[float] = None,
) -> dict:
    """Accept a sound into the session (persisted); ``foley_plan`` folds picks into a timeline."""
    n = _session(session).add_pick(sound_id, layer=layer, onset=onset)
    return {"ok": True, "sound_id": sound_id, "n_picks": n}


def foley_drop_pick(sound_id: str, session: str = "default") -> dict:
    """Remove a previously-picked sound from the session."""
    n = _session(session).drop_pick(sound_id)
    return {"ok": True, "sound_id": sound_id, "n_picks": n}


def foley_reject(
    sound_id: str, session: str = "default", reason: Optional[str] = None
) -> dict:
    """Reject a sound (feeds ``foley_refine`` relevance feedback)."""
    n = _session(session).add_reject(sound_id, reason=reason)
    return {"ok": True, "sound_id": sound_id, "n_rejects": n}


def foley_list_picks(session: str = "default") -> list:
    """The sounds picked in this session (the 'persist picks' read side)."""
    return _session(session).list_picks()


def foley_generate(
    prompt: str,
    backend: str = "auto",
    commercial_ok: bool = DEFAULT_INTENDED_USE.commercial,
    session: str = "default",
    territory: Optional[str] = None,
) -> dict:
    """Generate a sound from a text prompt (local backends only when offline).

    ``backend='auto'`` tries the host's generation order (ElevenLabs direct first, then
    the fal backends, then the local Stable Audio Open; the paid ones only when the
    host opted in with ``$FOLEY_GENERATE_PAID=1``; ``$FOLEY_GENERATE_ORDER`` /
    ``$FOLEY_GENERATE_BACKEND`` change it), skipping what is not configured or not
    allowed offline; name one to choose (``fal_stable_audio_3``, ``elevenlabs``, ...).

    A clip QC would quarantine for a clipped run just over the gate is repaired and
    stored (the repair is in the result's notes). A refused generation's dict carries
    ``cache_key``: where its paid bytes are in the generations cache
    (``foley.generations.get(cache_key)``, on the host — bytes never travel over MCP).
    ``territory``: where the sound is used (an ISO country code, or ``"WORLD"``); a
    backend whose licence excludes territories (HunyuanVideo-Foley) needs it stated.
    """
    from .. import GenerationError, generate
    from ..cost import BudgetExceeded, spend_scope
    from ..runtime import EXTERNAL, EgressBlocked
    from ..sources._dispatch import UnsupportedParameter
    from ..sources.base import SourceConfigurationError
    from ..sources.generate import (
        backend_is_paid,
        first_runnable_backend,
        generate_backend_order,
        generation_rights_refusal,
        paid_generation_opted_in,
    )
    from ..sources.registry import source_egress

    try:
        use = intended_use_for(commercial_ok=commercial_ok, territory=territory)
    except ValueError as exc:  # a territory that is not a code
        return _invalid(exc)

    # The bound server runtime may differ from the call's context (a server built with
    # runtime= but not run under offline_scope), so check it here too; undeclared
    # egress counts as external (fail-closed), as in the registry.
    def allowed(name):
        return _runtime().allows(source_egress(name) or EXTERNAL)

    auto = backend in ("auto", "", None)
    order = generate_backend_order() if auto else (backend,)
    paid_ok = not auto or paid_generation_opted_in()
    order = tuple(
        name
        for name in order
        if allowed(name) and (paid_ok or name == order[-1] or not backend_is_paid(name))
    )
    if not order:
        return {
            "ok": False,
            "error": f"backend {backend!r} is external and disallowed in offline mode",
        }
    backend = first_runnable_backend(order, paid_ok=paid_ok)  # reported if refused
    if len(order) == 1:  # a single backend is judged here; an order, per backend
        refusal = generation_rights_refusal(order[0], use)
        if refusal is not None:
            return {
                "ok": False,
                "status": "refused",
                "error": refusal,
                "backend": backend,
            }

    # The public façade returns the stored Candidate (a re-searchable, by-value
    # SoundRecord) and RAISES GenerationError on any non-success outcome (QC-quarantined,
    # rights-blocked, safety-refused, or an empty result). Surface both as JSON so the
    # agent gets the real generated id on success — and a structured error, never an
    # escaping exception, on failure — honoring the module's JSON-in/JSON-out contract.
    try:
        with spend_scope(_server_budget()):
            cand = generate(
                prompt,
                backend=order if len(order) > 1 else order[0],
                library=_lib(),
                intended_use=use,
            )
        backend = cand.sound.license.source or backend  # the one that served it
    except (
        EgressBlocked,
        BudgetExceeded,
        SourceConfigurationError,
        UnsupportedParameter,
    ) as exc:
        # Refused before a billed call (an earlier backend in the order may have been
        # refused by its provider, unbilled): say why, as JSON.
        return {
            "ok": False,
            "status": "refused",
            "error": str(exc),
            "backend": backend,
            "skipped_backends": getattr(exc, "skipped_backends", None),
        }
    except GenerationError as exc:
        return {
            "ok": False,
            "status": getattr(exc, "status", None),
            "error": str(exc),
            "backend": backend,
            # The paid bytes, when kept: foley.generations.get(cache_key) (#107).
            "cache_key": getattr(exc, "cache_key", None),
        }
    from ..licensing import keep

    usable = keep(cand.sound.license, use)
    return {
        "ok": True,
        "sound_ids": [cand.sound.id],
        "backend": backend,
        "license_ok": usable,  # under this call's intent (commercial_ok, territory)
        "license": _license_summary(cand.sound.license),
        "notes": list(cand.notes),
        "cost_estimate_usd": cand.cost_estimate_usd,
        "cost_actual_usd": cand.cost_actual_usd,
        "session_spent_usd": _server_budget().spent_usd,
    }


def foley_plan(
    session: str = "default",
    transcript: Optional[str] = None,
    candidate_ids: Optional[list] = None,
) -> dict:
    """Fold picks (or explicit candidate ids) into a JSON sound-design timeline.

    Each pick's explicit ``layer`` / ``onset`` (set via :func:`foley_pick`) is overlaid
    onto its candidate's :class:`~foley.base.SoundEvent` so ``plan`` honors the agent's
    placement choices — a numeric ``onset`` becomes an absolute-seconds anchor (see
    :func:`foley.weave.anchor.parse_symbolic_anchor`).
    """
    from .. import plan
    from ..base import Layer, SoundEvent

    sess = _session(session)
    ids = candidate_ids if candidate_ids is not None else sess.picked_ids()
    cands = sess.rehydrate(ids)
    for c in cands:
        sid = getattr(getattr(c, "sound", None), "id", None)
        pick = sess.picks.get(sid) if sid is not None else None
        if not pick:
            continue
        layer, onset = pick.get("layer"), pick.get("onset")
        if layer is None and onset is None:
            continue
        if c.event is None:
            c.event = SoundEvent(query=c.sound.caption or "", audioset=[])
        if layer is not None:
            c.event.layer = Layer(layer)
        if onset is not None:
            c.event.onset = str(onset)  # numeric → absolute-seconds anchor in WEAVE
    return plan(cands, transcript=transcript).to_dict()


def foley_weave(narration: str, timeline: dict, session: str = "default") -> dict:
    """Render a timeline under the narration; returns the mix by store key + captions + credits."""
    from .. import weave as _weave

    try:
        tl = _timeline_of(timeline)
    except (TypeError, ValueError) as exc:  # the input, not the render: a JSON row
        return _invalid(exc)
    lib = _lib()
    missing = sorted(
        {it.clip_ref for it in tl.items if not _in_library(lib, it.clip_ref)}
    )
    if missing:
        return _invalid(ValueError(f"clip_ref(s) not in the library: {missing}"))
    return _weave_result_row(_weave(narration, tl, library=lib))


def _in_library(lib, sound_id: str) -> bool:
    try:
        lib[sound_id]
    except KeyError:
        return False
    return True


def _timeline_of(timeline):
    """The :class:`~foley.base.SoundDesignTimeline` a tool was given as JSON.

    Raises:
        TypeError: If it is not a JSON object (a list, a string), or its fields are
            not a timeline's.
    """
    from ..base import SoundDesignTimeline

    if not isinstance(timeline, dict):
        raise TypeError(
            f"timeline must be a JSON object (a timeline's to_dict()), got "
            f"{type(timeline).__name__}"
        )
    return SoundDesignTimeline.from_dict(timeline)


def _invalid_on_bad_input(fn):
    """A pure timeline tool answers a bad timeline or item id with an ``invalid`` row
    (#194): its ``KeyError`` / ``TypeError`` / ``ValueError`` can only be the input's."""
    import functools

    @functools.wraps(fn)
    def tool(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (KeyError, TypeError, ValueError) as exc:
            return _invalid(exc)

    return tool


def _tl_op(op, timeline: dict, *args) -> dict:
    return op(_timeline_of(timeline), *args).to_dict()


@_invalid_on_bad_input
def foley_swap_clip(timeline: dict, item_id: str, sound_id: str) -> dict:
    """Swap a timeline item's clip; returns the new timeline."""
    from ..weave.timeline import swap_clip

    return _tl_op(swap_clip, timeline, item_id, sound_id)


@_invalid_on_bad_input
def foley_set_gain(timeline: dict, item_id: str, gain_db: float) -> dict:
    """Set a timeline item's gain (dB); returns the new timeline."""
    from ..weave.timeline import set_gain

    return _tl_op(set_gain, timeline, item_id, gain_db)


@_invalid_on_bad_input
def foley_nudge(timeline: dict, item_id: str, delta_s: float) -> dict:
    """Shift a timeline item's onset by ``delta_s`` seconds; returns the new timeline."""
    from ..weave.timeline import nudge

    return _tl_op(nudge, timeline, item_id, delta_s)


@_invalid_on_bad_input
def foley_toggle(timeline: dict, item_id: str, enabled: bool) -> dict:
    """Mute/unmute a timeline item; returns the new timeline."""
    from ..weave.timeline import toggle

    return _tl_op(toggle, timeline, item_id, enabled)


@_invalid_on_bad_input
def foley_set_master(
    timeline: dict,
    target_lufs: Optional[float] = None,
    peak_dbfs: Optional[float] = None,
) -> dict:
    """Set the timeline's master target (LUFS / true-peak); returns the new timeline.

    Either field may be set independently — omitting one keeps the podcast default for
    that field (so ``peak_dbfs=-2.0`` alone tightens only the true-peak ceiling).
    """
    from ..base import MasterProfile
    from ..weave.timeline import set_master

    if target_lufs is None and peak_dbfs is None:
        profile = "podcast"
    else:
        profile = MasterProfile(
            target_lufs=target_lufs if target_lufs is not None else -16.0,
            true_peak_db=peak_dbfs if peak_dbfs is not None else -1.0,
        )
    return set_master(_timeline_of(timeline), profile).to_dict()


@_invalid_on_bad_input
def foley_timeline_captions(timeline: dict, fmt: str = "vtt") -> dict:
    """Export SDH captions for a timeline (``fmt='vtt'`` | ``'srt'``)."""
    from ..weave.timeline import to_srt, to_webvtt

    if fmt not in ("vtt", "srt"):
        raise ValueError(f"fmt must be 'vtt' or 'srt', got {fmt!r}")
    tl = _timeline_of(timeline)
    return {"vtt": to_webvtt(tl)} if fmt == "vtt" else {"srt": to_srt(tl)}


def foley_score(
    context: str,
    commercial_ok: bool = DEFAULT_INTENDED_USE.commercial,
    verify: str = "listen",
    max_events: int = 6,
    session: str = "default",
    territory: Optional[str] = None,
) -> dict:
    """Score a narration passage → an editable sound-design timeline + a per-event rationale.

    The one-call SELECT→plan entry for an agent: pass the narration text and get back a JSON
    timeline plus a rationale for each chosen sound. Weaving (rendering the mastered mix) is a
    **separate** step (``foley_weave``) so you can review / edit the timeline first — swap a
    clip, nudge an onset, drop a cue — before committing to a render. ``territory``:
    where the sound is used (an ISO country code, or ``"WORLD"`` for online publishing);
    a licence that excludes territories is refused while it is unstated.
    """
    from .. import score
    from ..cost import spend_scope

    try:
        use = intended_use_for(commercial_ok=commercial_ok, territory=territory)
    except ValueError as exc:  # a territory that is not a code
        return _invalid(exc)

    with spend_scope(_server_budget()):
        res = score(
            context,
            library=_lib(),
            intended_use=use,
            verify=verify,
            max_events=max_events,
            weave=False,
        )
    return {
        "timeline": res.timeline.to_dict(),
        "events": [e.to_dict() for e in res.events],
        "n_sounds": res.n_sounds,
        "rationale": res.rationale,
    }


#: The operating playbook returned by :func:`foley_guide` (agent runtime guidance).
_GUIDE = """\
foley — sound-designing a narration (operating guide)

GOAL: choose the RIGHT sounds for a narration and weave them in TASTEFULLY. Restraint is the
craft: most sentences need NO sound. Prefer a few well-placed, license-clean cues over "sound
soup".

THE LOOP (each tool is JSON-in/JSON-out; audio is referenced by store key, never inlined):
  1. foley_score(context)      → a sound-design timeline + a rationale (SELECT does the tasteful
                                  decompose→search→verify→decide; it already exercises restraint,
                                  the fail-closed license gate, and the verify ladder).
     OR, interactively:
       foley_search / foley_find → candidate rows; foley_preview(id) to audition;
       foley_similar_to(id) for "more like this"; foley_refine(picks, rejects, hint) to steer;
       foley_pick(id, layer, onset) / foley_reject(id); foley_plan() to fold picks into a timeline.
  2. REVIEW + EDIT the timeline (all return a new timeline; nothing is destructive):
       foley_swap_clip / foley_set_gain / foley_nudge / foley_toggle / foley_set_master.
  3. foley_weave(narration, timeline) → the mastered mix (by store key) + SDH captions + credits.
  4. foley_generate(prompt) ONLY when nothing fits — it adds the clip to the library (re-searchable).

TASTE HEURISTICS:
  - Layers: `sfx_fg` = spot effects on a word; `ambience` = a bed under a sentence/scene (loops);
    `stinger` = a sharp accent on a boundary; keep beds low and duck them under the voice.
  - Salience: score a moment only if the sound adds meaning; leave quiet moments quiet.
  - Onset: place a spot effect ON its trigger word; a bed spans its sentence.
  - Licensing is load-bearing: only `license_ok` candidates are placed. Every tool assumes
    commercial publishing (commercial_ok=True); pass commercial_ok=False only for a
    non-commercial project. Each row's `license` carries full TASL + every rights flag.
    Some licences exclude territories (HunyuanVideo-Foley: EU, GB, KR): foley_find,
    foley_score and foley_generate refuse them unless territory= names where the sound is
    used (an ISO code like "US"; "WORLD" for online publishing, which they refuse).
  - Loudness: the master profile ('podcast'/'streaming'/'broadcast_ebu') sets the delivery target.

OFFLINE / SENSITIVE narration: run with the offline posture (foley_status shows it) — external
sources + telemetry are disabled; generation stays on local backends.
Call foley_capabilities() to see what's installed/degraded here.
"""


def _invalid(exc: Exception) -> dict:
    """The JSON row of an argument the tool refuses (a tool never raises for one)."""
    message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
    return {"ok": False, "status": "invalid", "error": str(message)}


def foley_guide() -> dict:
    """How to sound-design a narration with foley — the operating playbook for an agent.

    Call this first if you are unsure of the workflow: it returns the tool order, the taste
    heuristics (restraint, layering, ducking, licensing), and the offline posture.
    """
    return {"guide": _GUIDE}


def foley_capabilities() -> dict:
    """What foley can do here — keys / extras / system deps / offline / sources / degraded."""
    from ..requirements import capability_report

    return capability_report(runtime=_runtime())


def foley_status(session: str = "default") -> dict:
    """The current runtime posture + this session's pick/reject counts."""
    from ..obs import is_enabled
    from ..obs import recorder as _obs_recorder
    from ..sources.registry import list_sources

    cfg = _runtime()
    sess = _session(session)
    return {
        "offline": cfg.offline,
        "sources": list_sources(egress_allow=cfg.data_egress_allow),
        "telemetry_enabled": bool(is_enabled()),
        # The *effective* recorder redaction mode (not the aspirational RuntimeConfig
        # value), so status can never affirmatively misstate the real posture.
        "redaction_mode": _enum(_obs_recorder._CONFIG.redaction_mode),
        "spent_usd": _server_budget().spent_usd,
        "max_usd": _server_budget().max_usd,
        "n_picks": len(sess.list_picks()),
        "n_rejects": len(sess.list_rejects()),
    }


@dataclass(frozen=True)
class Verb:
    """One verb of foley's JSON-safe surface: the function and the surfaces it is on (#62).

    The function is the verb: JSON in, JSON out, a thin call into the façade. MCP serves
    it as the tool ``fn.__name__``; the ``foley`` CLI as the command of that name
    without its ``foley_`` prefix (:func:`foley.cli.build_parser`). Adding a verb here
    adds it to both, with no surface code.
    """

    fn: Callable
    mcp: bool = True
    cli: bool = True
    #: Why a surface is off (said where the flag is set, so it is never a silent gap).
    why: str = ""

    @property
    def name(self) -> str:
        return self.fn.__name__

    @property
    def command(self) -> str:
        """The CLI command name: ``foley_similar_to`` -> ``similar-to``."""
        return self.name.removeprefix("foley_").replace("_", "-")


#: The verb table (SSOT), in a stable order: MCP's tools and the CLI's generated
#: commands are both read from it.
VERBS = (
    Verb(foley_find),
    Verb(
        foley_search,
        cli=False,
        why="the CLI's own `foley search` prints readable rows (it predates the table)",
    ),
    Verb(foley_similar_to),
    Verb(foley_preview),
    Verb(foley_refine),
    Verb(foley_pick),
    Verb(foley_drop_pick),
    Verb(foley_reject),
    Verb(foley_list_picks),
    Verb(foley_generate),
    Verb(foley_plan),
    Verb(foley_weave),
    Verb(foley_swap_clip),
    Verb(foley_set_gain),
    Verb(foley_nudge),
    Verb(foley_toggle),
    Verb(foley_set_master),
    Verb(foley_timeline_captions),
    Verb(foley_score),
    Verb(foley_guide),
    Verb(foley_capabilities),
    Verb(foley_status),
)

#: The MCP tool surface at import, in the table's order (kept for callers that read it;
#: the server reads :data:`VERBS` when it is built).
TOOLS = [v.fn for v in VERBS if v.mcp]


def surface_snapshot(verbs=None) -> dict:
    """``{tool name: {parameter: default}}`` of the MCP tools, plus the CLI commands.

    What an agent or a script binds to by name, without py2mcp: a test pins it, so a
    renamed tool or a changed default is a decision, never an accident (#62). A
    parameter with no default maps to ``"<required>"``.
    """
    import inspect

    verbs = VERBS if verbs is None else verbs

    def params(fn):
        return {
            name: "<required>" if p.default is inspect.Parameter.empty else p.default
            for name, p in inspect.signature(fn).parameters.items()
        }

    return {
        "mcp": {v.name: params(v.fn) for v in verbs if v.mcp},
        "cli": sorted(v.command for v in verbs if v.cli),
    }
