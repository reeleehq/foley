"""foley — a retrieval-first façade for sound effects.

foley finds (or generates) the right sound effect for a moment of narration and
weaves it in. It is the SFX sibling of ``arioso`` (a unified façade over AI
music-generation backends): one simple surface over many sound *sources* (a
bring-your-own library, service APIs like Freesound, and generative-AI models),
a searchable *index* of every sound (by keyword *and* meaning, via CLAP
embeddings + hybrid search), an *agent* that selects the right sound for a
narrative context, and a *compositor* that places it under the voice.

Four stages::

    SOURCE  ->  INDEX  ->  SELECT  ->  WEAVE
    (get)      (find)      (choose)    (compose)

The façade (v1 — Epic #13 complete; the surface below is live — see
``misc/docs/design.md`` / ``misc/docs/roadmap.md`` for the roadmap)::

    import foley

    foley.find("She pushed open the heavy oak door; rain hammered outside.")
    foley.search("distant thunder rumble", k=10)
    foley.generate("a single wooden door creak", backend="stable_audio")
    foley.ingest("~/my_sounds/")

The design is grounded in the research reports under ``misc/docs/research/``.

The whole four-stage surface (source → index → select → weave) plus the MCP server and
the licensing/provenance, evaluation, and observability layers is implemented and
re-exported here (see ``__all__`` and the ``find`` / ``search`` / ``generate`` /
``ingest`` / ``weave`` façade functions below). The retrieval-agnostic **foundation**
every later stage stands on:

    * **Data models** (``foley.base``) — the SSOT dataclasses/enums shared across
      layers (:class:`SoundRecord`, :class:`LicenseRecord`, :class:`Candidate`,
      :class:`SoundEvent`, :class:`Verdict`, :class:`IntendedUse`), the two
      affordance registries, and generic dict/JSON (de)serialization.
    * **License policy** (``foley.licensing``) — the ``license_id`` -> flag-set
      SSOT (:data:`LICENSE_FLAGS`), flag derivation, and the fail-closed
      :func:`keep` gate.
    * **Storage** (``foley.stores``) — content-addressed byte store + metadata
      store built from ``dol``, and :func:`store_sound` (the by-value vs
      by-reference gate driven by ``LicenseRecord.cache_bytes_ok``).
    * **QC** (``foley.qc``) — Tier-0 deterministic audio checks
      (:func:`run_qc` -> :class:`QCReport`, thresholds in :class:`QCThresholds`).
    * **Audio** (``foley.audio``) — I/O + DSP primitives. Exposed as a submodule
      (``foley.audio``) with the key functions also re-exported here.

Import cost: ``import foley`` pulls only ``dol`` (a light core dependency used by
``foley.stores``); ``numpy``/``soundfile``/``soxr``/``librosa``/``mixing.loudness`` are
lazy-imported inside the audio/QC functions that need them (install via the
``foley[audio]`` extra), so a bare install imports cleanly.
"""

from . import audio
from .audio import (
    WORKING_SAMPLE_RATE,
    encode,
    ensure_channels,
    fade,
    load,
    loudness_normalize,
    resample,
    save,
    to_mono,
    to_working,
    trim_silence,
)
from .base import (
    GENERATION_AFFORDANCES,
    MASTER_PROFILES,
    QUERY_AFFORDANCES,
    SCHEMA_VERSION,
    AcquisitionMethod,
    Affordance,
    Anchor,
    Candidate,
    CandidateOrigin,
    IntendedUse,
    Layer,
    LicenseRecord,
    MasterProfile,
    Placement,
    Processing,
    Salience,
    SerializableMixin,
    SoundDesignTimeline,
    SoundEvent,
    SoundRecord,
    StorageMode,
    TimelineItem,
    Verdict,
    VerifyLevel,
    resolve_master,
)
from .licensing import (
    LICENSE_FLAGS,
    LICENSE_META,
    UNKNOWN_LICENSE_FLAGS,
    UNKNOWN_LICENSE_META,
    LicenseFlags,
    LicenseMeta,
    apply_license_flags,
    derive_license_flags,
    keep,
    keep_sound,
    license_id_from_cc_url,
    license_meta,
)
from .qc import (
    DEFAULT_QC_THRESHOLDS,
    QCReport,
    QCStatus,
    QCThresholds,
    dc_offset,
    detect_clipping,
    duration_s,
    estimate_snr,
    has_nan_inf,
    is_silent,
    measure_lufs,
    needs_edge_fade,
    run_qc,
    true_peak_dbtp,
)
from .stores import (
    DEFAULT_AUDIO_DIR,
    DEFAULT_GENERATIONS_DIR,
    DEFAULT_META_DIR,
    DEFAULT_RUN_DIR,
    FOLEY_DATA_DIR,
    GenerationsCache,
    content_key,
    make_byte_store,
    make_generations_store,
    make_meta_store,
    make_run_store,
    store_sound,
)

# --- repair: the QC-driven fixes generate() applies before quarantining (#107) ----
# stdlib-only at import (numpy loads inside repair.repair); ``foley.repair.repair`` is
# the default of ``generate(repair=...)``.
from . import repair
from . import index
from .index import (
    CLAP_SAMPLE_RATE,
    DEFAULT_CANDIDATE_K,
    DEFAULT_CLAP_DIM,
    DEFAULT_CLAP_MODEL_ID,
    RRF_K,
    Captioner,
    CatIdResolution,
    ClapEmbedder,
    ClapZeroShotTagger,
    Embedder,
    FusedHit,
    IngestReport,
    IngestResult,
    KeywordIndex,
    LanceIndex,
    MemoryIndex,
    PannsTagger,
    SoundLibrary,
    SqliteVecIndex,
    Tagger,
    VectorIndex,
    default_embedder,
    default_index,
    default_library,
    default_tagger,
    default_zeroshot_tagger,
    fuse_hits,
    hybrid_search,
    ingest_folder,
    ingest_one,
    restamp_rights,
    lancedb_available,
    parse_ucs_filename,
    reciprocal_rank_fusion,
    resolve_catid,
    sqlite_vec_loadable,
    vector_search,
)

# --- source: bulk-corpus bootstrap (stdlib-only at import; numpy is lazy) ------
from .bootstrap import bootstrap, demo

# --- source: live-source adapters (Freesound) + the add_from pull facade -------
# Auto-discovery is lazy, so the Freesound adapter (and requests) is not imported
# until first use — `import foley` stays dol-only.
from .sources import add_from, list_sources, register_source
from .sources.capabilities import capabilities_of, ledger, list_backends

# --- source: generation adapters (Stable Audio Open / ElevenLabs) — #6 ---------
# The generate facade + its helpers. The generator adapter packages (and their
# torch/requests deps) are auto-discovered lazily, so `import foley` stays dol-only.
from .sources import (
    GenerationError,
    RecognizableVoiceRefusal,
    SafetyRefusal,
    TrademarkRefusal,
    candidate_of,
)
from .sources import generate as _generate_backend

# --- eval: Tier-1 retrieval metrics + the nDCG PR gate (numpy lazy) -----------
from . import eval  # noqa: A004 - deliberate: foley.eval is the retrieval-eval subpackage

# --- provenance: TASL attribution / credits (stdlib-only; #9b disclosure later) --
from . import provenance
from .provenance import (
    CreditEntry,
    Credits,
    attribution_line,
    credit_entry,
    credits_for,
)

# --- obs: observability + reproducible run-artifact (#11) ----------------------
# The obs package is stdlib-only at import (opentelemetry loads lazily inside the
# OTel-backed tracer only, behind foley[obs]), so this keeps `import foley` dol-only.
# Off by default: a plain façade call is a byte-for-byte no-op until obs is enabled.
from . import obs
from .obs import RunManifest, SpanRecord

# --- agent: the SELECT stage — find() + the sparse plan (#7) --------------------
# The agent package is dol-only at import (the LLM rungs sit behind DI-seam
# protocols with deterministic fakes; anthropic — foley[agent] — is imported lazily
# inside the real impls only), so this keeps `import foley` dol-only.
from . import agent
from .agent import (
    Budget,
    Decision,
    Judge,
    decide,
    decompose_context,
    find,
    plan,
    refine_query,
    verify_match,
)

# --- weave: the WEAVE stage — weave() renders the finished, editable mix (#8) ----
# The weave package is dol-only at import (the aligner + apply-strategy sit behind
# DI-seam protocols with deterministic defaults; whisperx/mixing/opentimelineio/
# audioseal/c2pa are imported lazily inside methods only). ``weave`` here is the
# façade: the ``weave`` package is made *callable* (see foley/weave/__init__.py), so
# ``foley.weave(narration, timeline)`` runs the façade while ``foley.weave.<submodule>``
# (``foley.weave.render`` etc.) stays fully importable.
from . import weave
from .weave import WeaveResult

# --- score: the one-call AI-first entry — narration text → tasteful woven sound design ---
# (composes find → plan → weave; numpy/torch stay lazy inside them, so this stays dol-only.)
from .score import ScoreResult, ScoredEvent, score

# --- the shipped agent kit installer (skill + slash command + subagent) ----------
from .agent_kit import install_agent_kit

# --- #12: MCP surface, preview UX, onboarding & offline mode ---------------------
# All dol-only at import (py2mcp/fastmcp are imported lazily inside build_mcp_server;
# numpy/soundfile only inside preview's encode path). ``mcp_server`` is the report-10
# façade alias of the builder.
from .agent.mcp import build_mcp_server
from .agent.mcp import build_mcp_server as mcp_server
from .agent.mcp import make_http_app, serve_http
from .agent.preview import preview, refine, similar_to
from .agent.session import SessionStore
from .requirements import capability_report, check_requirements, verify_and_setup
from .runtime import RuntimeConfig, is_offline, offline
from .sources.base import using_source_accounts
from .stores import make_session_store

__all__ = [
    # --- base: constants + enums ---------------------------------------------
    "SCHEMA_VERSION",
    "StorageMode",
    "AcquisitionMethod",
    "CandidateOrigin",
    "Salience",
    "Layer",
    "VerifyLevel",
    # --- base: affordances ---------------------------------------------------
    "Affordance",
    "QUERY_AFFORDANCES",
    "GENERATION_AFFORDANCES",
    # --- base: serialization + models ----------------------------------------
    "SerializableMixin",
    "LicenseRecord",
    "SoundRecord",
    "SoundEvent",
    "Verdict",
    "Candidate",
    "IntendedUse",
    "TimelineItem",
    "SoundDesignTimeline",
    "Anchor",
    "Placement",
    "Processing",
    "MasterProfile",
    "MASTER_PROFILES",
    "resolve_master",
    # --- licensing: policy ---------------------------------------------------
    "LicenseFlags",
    "LICENSE_FLAGS",
    "UNKNOWN_LICENSE_FLAGS",
    "LicenseMeta",
    "LICENSE_META",
    "UNKNOWN_LICENSE_META",
    "license_meta",
    "license_id_from_cc_url",
    "derive_license_flags",
    "apply_license_flags",
    "keep",
    "keep_sound",
    # --- stores: content-addressed storage + the storage gate ----------------
    "content_key",
    "make_byte_store",
    "make_meta_store",
    "make_run_store",
    "store_sound",
    "FOLEY_DATA_DIR",
    "DEFAULT_AUDIO_DIR",
    "DEFAULT_META_DIR",
    "DEFAULT_RUN_DIR",
    # --- stores: the paid-generations cache (#59, #107) ------------------------
    "generations",
    "GenerationsCache",
    "make_generations_store",
    "DEFAULT_GENERATIONS_DIR",
    # --- repair: QC-driven fixes before quarantine (#107) -----------------------
    "repair",
    # --- qc: Tier-0 deterministic audio QC -----------------------------------
    "QCStatus",
    "QCThresholds",
    "DEFAULT_QC_THRESHOLDS",
    "QCReport",
    "run_qc",
    "has_nan_inf",
    "duration_s",
    "dc_offset",
    "is_silent",
    "detect_clipping",
    "true_peak_dbtp",
    "estimate_snr",
    "needs_edge_fade",
    "measure_lufs",
    # --- audio: I/O + DSP primitives -----------------------------------------
    "audio",
    "WORKING_SAMPLE_RATE",
    "load",
    "save",
    "encode",
    "resample",
    "to_mono",
    "ensure_channels",
    "trim_silence",
    "fade",
    "loudness_normalize",
    "to_working",
    # --- index: embeddings, hybrid search, library façade, taxonomy ----------
    "index",
    "SoundLibrary",
    "default_library",
    "search",
    "estimate",
    "similar",
    "Embedder",
    "ClapEmbedder",
    "default_embedder",
    "VectorIndex",
    "KeywordIndex",
    "MemoryIndex",
    "LanceIndex",
    "SqliteVecIndex",
    "default_index",
    "lancedb_available",
    "sqlite_vec_loadable",
    "hybrid_search",
    "vector_search",
    "reciprocal_rank_fusion",
    "fuse_hits",
    "FusedHit",
    "RRF_K",
    "DEFAULT_CANDIDATE_K",
    "DEFAULT_CLAP_MODEL_ID",
    "DEFAULT_CLAP_DIM",
    "CLAP_SAMPLE_RATE",
    "resolve_catid",
    "parse_ucs_filename",
    "CatIdResolution",
    "library",
    # --- index: taggers + ingestion ------------------------------------------
    "Tagger",
    "Captioner",
    "ClapZeroShotTagger",
    "PannsTagger",
    "default_tagger",
    "default_zeroshot_tagger",
    "ingest",
    "restamp_rights",
    "ingest_one",
    "ingest_folder",
    "IngestResult",
    "IngestReport",
    # --- source: bulk-corpus bootstrap ---------------------------------------
    "bootstrap",
    "demo",
    # --- source: live-source adapters + add_from pull facade -----------------
    "add_from",
    "list_sources",
    "list_backends",
    "capabilities_of",
    "ledger",
    "register_source",
    # --- source: generation adapters (Stable Audio Open / ElevenLabs) --------
    "generate",
    "candidate_of",
    "GenerationError",
    # --- provenance: generation disclosure / watermark / safety (#9b) --------
    "SafetyRefusal",
    "TrademarkRefusal",
    "RecognizableVoiceRefusal",
    "art50_checklist",
    "scan_prompt",
    # --- obs: observability + reproducible run-artifact (#11) -----------------
    "obs",
    "RunManifest",
    "SpanRecord",
    # --- agent: the SELECT stage — find() + sparse plan (#7) ------------------
    "agent",
    "find",
    "plan",
    "decompose_context",
    "refine_query",
    "verify_match",
    "decide",
    "Judge",
    "Budget",
    "Decision",
    # --- weave: the WEAVE stage — weave() (#8) --------------------------------
    "weave",
    "WeaveResult",
    # --- score: the one-call AI-first entry (narration → woven sound design) --
    "score",
    "ScoreResult",
    "ScoredEvent",
    "install_agent_kit",
    # --- #12: MCP surface, preview UX, onboarding & offline mode ---------------
    "mcp_server",
    "build_mcp_server",
    "make_http_app",
    "serve_http",
    "preview",
    "similar_to",
    "refine",
    "SessionStore",
    "make_session_store",
    "RuntimeConfig",
    "offline",
    "is_offline",
    "using_source_accounts",
    "check_requirements",
    "verify_and_setup",
    "capability_report",
    # --- eval: Tier-1 retrieval metrics + nDCG gate --------------------------
    "eval",
    "evaluate",
    # --- eval: Tier-2 fit-judge + fidelity + reliability (#10b) ---------------
    "evaluate_fit",
    # --- provenance: TASL attribution / credits ------------------------------
    "provenance",
    "credits",
    "Credits",
    "CreditEntry",
    "credits_for",
    "attribution_line",
    "credit_entry",
]


def evaluate(*, golden=None, k: int = 10):
    """Run the Tier-1 retrieval eval over the golden set (nDCG@10 / recall / mAP / MRR).

    Scores every golden query through the real :meth:`SoundLibrary.search` path
    against a deterministic, CLAP-free Ring-0 library — the same computation the
    PR gate asserts on. See :mod:`foley.eval`.

    Args:
        golden: Optional path to a golden-set JSON (default: the frozen seed).
        k: Retrieval cutoff and metric ``@k``.

    Returns:
        A :class:`foley.eval.RetrievalReport`.
    """
    from .eval.golden import run_ring0_retrieval_eval

    kw = {"k": k}
    if golden is not None:
        kw["golden_path"] = golden
    return run_ring0_retrieval_eval(**kw)


def evaluate_fit(
    *,
    golden=None,
    sample=None,
    level=VerifyLevel.judge,
    fit_judge=None,
    embedder=None,
    seed: int = 0,
    k: int = 10,
    llm=None,
):
    """Run the Tier-2 **fit** eval over the golden set — "does the accepted clip fit?" (#10b).

    The judge-based sibling of :func:`evaluate`: over a seeded stratified sample it runs
    the SELECT pipeline and audits each license-clean candidate with the authoritative
    fit-judge, returning a :class:`foley.eval.FitReport` (fit-precision / recall / F1 +
    fit-score + auto-accept-rate + per-stratum breakdown). Works out of the box on the
    Ring-0 fixture with the deterministic fake judge — no network, key, or heavy deps.
    **Nightly / pre-release and cost-gated**: report-only — gating is the caller's job via
    :meth:`FitReport.gate`. It never touches the retrieval ranking (the Tier-1 nDCG gate).

    Args:
        golden: Optional golden-set JSON path (default: the frozen Ring-0 seed).
        sample: Optional stratified sample cap (default: the whole set — the cost gate).
        level: The verify rung the fit-judge audits at — ``'listen'`` or ``'judge'``
            (default ``VerifyLevel.judge``); ``'clap'`` is rejected.
        fit_judge: An injected authoritative judge (default: the ``llm`` provider's judge
            — the hermetic :class:`~foley.agent.StringOverlapJudge` fake unless ``llm``
            opts in; the audio-LM :class:`~foley.agent.AudioLMJudge` is injection-only).
        embedder: The Ring-0 embedder (default: the CLAP-free ``HashingBowEmbedder``).
        seed: The sampling RNG seed.
        k: Retrieval shortlist depth per event.
        llm: The fit-judge's provider when ``fit_judge`` is not given —
            ``'anthropic'`` for the nightly arbiter (or ``$FOLEY_LLM``); ``None``
            keeps the deterministic fake (a local endpoint is never picked implicitly).

    Returns:
        A :class:`foley.eval.FitReport`.
    """
    from .eval.fit import run_fit_eval

    kw = dict(
        sample=sample,
        level=level,
        fit_judge=fit_judge,
        embedder=embedder,
        seed=seed,
        k=k,
        llm=llm,
    )
    if golden is not None:
        kw["golden_path"] = golden
    return run_fit_eval(**kw)


def credits(
    sounds, *, title: str = "Credits", only_required: bool = False, write_to=None
):
    """Build the TASL attribution :class:`~foley.provenance.Credits` for ``sounds``.

    Works standalone today (given any iterable of sounds), and is what the WEAVE
    stage will call at render time. Inspect ``.markdown`` (a ``CREDITS.md``
    document) / ``.manifest`` (a JSON-serializable dict) on the result.

    Args:
        sounds: An iterable of :class:`SoundRecord` / :class:`Candidate` /
            :class:`LicenseRecord` (e.g. the result of :func:`search`, or the
            sounds placed in a timeline).
        title: The credits heading.
        only_required: Keep only legally-required attributions (drops CC0 /
            user-owned courtesy credits). Default credits everything.
        write_to: Optional directory; when given, writes ``CREDITS.md`` and
            ``credits.json`` into it (created if missing).

    Returns:
        A :class:`~foley.provenance.Credits`.
    """
    result = provenance.credits_for(sounds, title=title, only_required=only_required)
    if write_to is not None:
        from pathlib import Path

        out = Path(write_to)
        out.mkdir(parents=True, exist_ok=True)
        (out / "CREDITS.md").write_text(result.markdown, encoding="utf-8")
        (out / "credits.json").write_text(result.to_json(indent=2), encoding="utf-8")
    return result


def search(
    query: str,
    *,
    k: int = 10,
    filters=None,
    commercial_ok=None,
    ucs_category=None,
    min_snr=None,
    duration_range=None,
    rerank: bool = False,
):
    """Hybrid (CLAP vector ⊕ BM25) search of the default library.

    Convenience wrapper over ``foley.library.search(...)`` — see
    :meth:`foley.index.SoundLibrary.search`. Constructs the process-wide default
    library (local stores + CLAP + best available index) on first use.

    ``commercial_ok`` defaults to the one rights intent every verb shares
    (:data:`foley.licensing.DEFAULT_INTENDED_USE`: commercial), so only commercially
    usable sounds come back; pass ``commercial_ok=False`` to include the rest.
    """
    from .licensing import intended_use_for

    commercial = intended_use_for(commercial_ok=commercial_ok).commercial
    lib = default_library()
    kw = dict(
        k=k,
        filters=filters,
        ucs_category=ucs_category,
        min_snr=min_snr,
        duration_range=duration_range,
        rerank=rerank,
    )
    hits = lib.search(query, commercial_ok=commercial or None, **kw)
    if commercial and not hits:
        _warn_if_hidden(lib.search(query, commercial_ok=None, **kw))
    return hits


def similar(sound_id: str, *, k: int = 10, commercial_ok=None):
    """Find sounds similar to a stored sound (audio<->audio) in the default library.

    See :meth:`foley.index.SoundLibrary.similar`. Like :func:`search`, only sounds
    cleared for the default (commercial) intent are returned unless
    ``commercial_ok=False``.
    """
    from .licensing import intended_use_for

    hits = default_library().similar(sound_id, k=k)
    if not intended_use_for(commercial_ok=commercial_ok).commercial:
        return hits
    kept = [
        c
        for c in hits
        if c.sound.license.commercial_ok and c.sound.license.rights_verified
    ]
    if not kept:
        _warn_if_hidden(hits)
    return kept


def _warn_if_hidden(hidden) -> None:
    """Say why a commercial-default search came back empty when it did not have to."""
    if hidden:
        import warnings

        warnings.warn(
            f"{len(hidden)} match(es) hidden: not cleared for commercial use (unverified "
            "or non-commercial rights — e.g. files ingested without a licence). Pass "
            "commercial_ok=False to see them, or assert rights with "
            "foley.ingest(path, license='user-owned') / foley restamp-rights.",
            UserWarning,
            stacklevel=3,
        )


def generate(
    prompt: str,
    *,
    backend: "str | tuple[str, ...] | list[str] | None" = None,
    library=None,
    store: bool = True,
    adapter=None,
    watermark=None,
    on_flagged: str = "refuse",
    watermarker=None,
    provenance_store=None,
    on_unsupported=None,
    reuse_cached: bool = True,
    budget=None,
    repair=True,
    level=None,
    check_prompt: bool = True,
    intended_use=None,
    provider_params=None,
    **affordances,
):
    """Generate a sound effect for ``prompt`` and add it to the library (by-value).

    Progressive disclosure: ``foley.generate("a single wooden door creak")`` works
    out of the box (the local Stable Audio Open backend, into the process-wide
    default library). The generated audio is stored **by-value** with a content-hash
    id, so it becomes a first-class, re-searchable library entry — every generation
    is a future free retrieval (the generation flywheel). It flows through the SAME
    :func:`~foley.index.ingest.ingest_one` pipeline as every other source, with
    operator consent for the generator license's AI-training restriction (the record
    keeps ``ai_training_ok=False``, so :func:`keep` still refuses it for
    training uses).

    Args:
        prompt: The natural-language sound description.
        backend: A registered generate source, or a sequence of them to try in
            order. ``None`` (default) tries the generation order
            (:func:`foley.sources.generate.generate_backend_order`): ElevenLabs
            direct first (``"elevenlabs"``: ``foley[elevenlabs]``,
            ``$ELEVENLABS_API_KEY`` or ``$ELEVEN_API_KEY``, and
            ``$FOLEY_ELEVENLABS_PLAN``), then fal's ``"fal_stable_audio_3"`` (Stable
            Audio 3 Small-SFX, commercial under $1M revenue) and ``"fal_elevenlabs"``
            (``foley[fal]`` + ``$FAL_KEY``), then the local ``"stable_audio_3"``
            (Stable Audio 3 Small-SFX on the CPU, no GPU or token; one-time setup:
            ``foley.check_requirements(verbose=True)`` prints it) and last
            ``"stable_audio"`` (``foley[stable-audio]``). The paid ones are tried only once paid
            generation is opted in (``$FOLEY_GENERATE_PAID=1``; a key in the
            environment is not consent to spend, #58), so out of the box this is the
            free local backend. A backend with no key, not configured, offline,
            whose licence cannot serve ``intended_use``, or whose provider refused the
            request (an HTTP error, nothing billed) is skipped, and the candidate's
            ``notes`` say why; a failure that may have been billed is final.
            ``$FOLEY_GENERATE_ORDER`` (comma-separated) replaces the order;
            ``$FOLEY_GENERATE_BACKEND`` pins one backend. A named backend is used
            alone, with no fallback. Others: ``"fal_sonilo"``, ``"fal_mirelo"``,
            ``"fal_stable_audio_3_medium"``, ``"fal_mmaudio"`` (non-commercial).
        library: Target library (default: the process-wide default library).
        store: If ``False``, synthesize + QC a preview without adding it: the returned
            candidate's ``audio_bytes`` carries the clip (the archive bytes the library
            would have stored), and enrichment that needs an absent extra
            (``foley[clap]``) is skipped with a note instead of failing after the paid
            call (#107).
        adapter: Optional pre-built adapter (the DI seam; production omits it and the
            registry lazily builds one).
        watermark: ``True`` require an AudioSeal watermark, ``False`` never, ``None``
            (default, auto) watermark iff ``foley[provenance]`` is installed (#9b).
        on_flagged: ``'refuse'`` (default, fail-closed) or ``'warn'`` for a prompt
            that trips the trademarked-audio / recognizable-voice safety gate (#9b).
        watermarker: An injected watermarker (the DI seam; tests pass a fake).
        provenance_store: A ``MutableMapping`` for content-credential sidecars
            (default: :func:`foley.stores.make_provenance_store`).
        on_unsupported: A parameter the backend cannot honour: ``None`` (default)
            raises for a meaning-carrying one (``seed``, ``negative_prompt``) and drops
            the rest with a note; ``'warn'`` drops everything with a note + warning;
            ``'note'`` silently-but-recorded; ``'raise'`` raises for any.
        reuse_cached: Serve an identical paid request from the generations cache
            (default ``True``): a paid sound is never paid for twice (#59).
        budget: A :class:`Budget` for this call (default: the active run's, else a
            fresh one — a $1 cap; an unknown cost needs approval) (#57).
        repair: What to do with a generation QC would quarantine for a clipped run
            just over the gate (#107). ``True`` (default) applies the report's own
            fixes (:func:`foley.repair.repair`: a 20 ms fade and a true-peak
            attenuation, which also clear the edge click and the over-ceiling peak such
            a clip carries), checks again and stores the repaired clip, recording the
            repair on the candidate's ``notes`` and in the licence's
            ``transformations``; unrepairable faults (silence, NaN, too short, heavy
            clipping) are still quarantined, with the reason in the error's report.
            ``False`` quarantines as before; a callable with
            :func:`foley.repair.repair`'s signature replaces the policy (an ffmpeg one;
            ``functools.partial(foley.repair.repair, min_status=QCStatus.pass_)`` also
            declicks clips QC admits with a warning, which are otherwise stored as is).
        level: Level the clip to a loudness target before storing it: a layer name
            (``'sfx_fg'`` -25 LUFS, ``'ambience'`` -37 LUFS, … : the WEAVE layer gains
            under a -16 LUFS voice, see :func:`foley.level.class_target_lufs`) or a LUFS
            number. ``None`` (default) keeps the generated level.
        check_prompt: Score the clip against its prompt with the library's text-audio
            embedder (CLAP) and flag a mismatch in the notes and
            ``sound.qc['prompt_match']``; ``'unchecked'`` (with the reason) when no
            capable embedder is available. Default ``True``.
        intended_use: The :class:`IntendedUse` the clip must serve when an order is
            walked (default: commercial): a backend whose licence cannot serve it is
            skipped before anything is paid for. A single named backend is used as
            asked (its licence is gated downstream by :func:`keep`).
        provider_params: Vendor-native params foley has no unified affordance for
            (#61). For a named ``backend``, a flat dict, e.g.
            ``{"num_inference_steps": 50}``; when the call may try several backends
            (``backend`` unnamed, ``'auto'`` or a list), per backend, e.g.
            ``{"stable_audio": {"num_inference_steps": 50}}`` (a flat dict raises),
            and each backend gets only its own. Merged by the backend over its
            translated native params (a provider param wins), recorded in the
            licence's ``generation_params``, and part of the generations-cache key.
            A key the backend's config ``provider_params`` policy reserves (the
            prompt, an output path) or prices (``duration_s``, the model) raises
            ``ValueError`` before anything is paid for: use the unified argument.
        **affordances: Unified generation affordances (``duration_s``,
            ``prompt_influence``, ``negative_prompt``, ``steps``, ``seed``, ``loop``,
            ``output_format`` — see :data:`GENERATION_AFFORDANCES`).

    Returns:
        The stored :class:`Candidate` (``origin=generated``) — its ``sound`` is the
        canonical, by-value :class:`SoundRecord` (a content-hash id); its ``notes``
        list every dropped, clamped or substituted parameter, and
        ``cost_estimate_usd`` / ``cost_actual_usd`` what it cost (``None`` = unknown).

    Raises:
        SafetyRefusal: If the prompt trips a safety gate and ``on_flagged='refuse'``
            (a :class:`GenerationError` subclass — ``TrademarkRefusal`` /
            ``RecognizableVoiceRefusal``).
        GenerationError: If the backend yields no stored sound (QC-quarantined,
            rights-blocked, or a synthesis/ingest error). The message carries the root
            cause and the exception is chained to it; it also carries the full
            ``report`` and terminal ``status`` so callers can react distinctly, and
            ``cache_key`` — where the paid bytes are in the generations cache
            (``foley.generations.get(err.cache_key)``), since they were billed either
            way (#107).
        SourceConfigurationError: If the backend is not configured (a missing key or
            plan) — the message names the env var and where to get the key.
        UnsupportedParameter: For a meaning-carrying parameter the backend cannot
            honour (see ``on_unsupported``).
        BudgetExceeded / CostApprovalRequired: Before a paid call the budget refuses.
        EgressBlocked: For an external backend under :func:`offline`, or
            :class:`~foley.runtime.ModelNotCached` for a local one whose weights are
            not on this machine.
    """
    from .cost import spend_scope
    from .sources.generate import (
        default_generate_backend,
        generate_backend_order,
        generate_in_order,
        paid_generation_opted_in,
        provider_params_by_backend,
    )

    paid_ok = True  # a named backend or order is the caller asking for it
    if adapter is not None:  # an injected adapter is one backend, named by its config
        if isinstance(backend, (list, tuple)):
            raise ValueError("adapter= is one backend: pass a single backend= name")
        named = (getattr(adapter, "config", None) or {}).get("name")
        order = (
            backend
            if backend not in (None, "", "auto")
            else named or default_generate_backend(),
        )
    elif isinstance(backend, (list, tuple)):
        order = tuple(backend)  # the caller's own order
        if not order:
            raise ValueError("backend= is an empty sequence: name at least one backend")
    elif backend not in (None, "", "auto"):
        order = (backend,)  # named: that backend, no fallback
    else:
        order, paid_ok = generate_backend_order(), paid_generation_opted_in()
    # Native params are one vendor's: an order that may try several backends takes
    # them per backend, and each backend gets only its own (#61).
    may_fall_back = adapter is None and (
        isinstance(backend, (list, tuple)) or backend in (None, "", "auto")
    )
    by_backend = provider_params_by_backend(
        provider_params, order, per_backend=may_fall_back
    )
    with spend_scope(budget):
        report, backend, skipped = generate_in_order(
            prompt,
            order,
            paid_ok=paid_ok,
            intended_use=intended_use,
            library=library,
            store=store,
            adapter=adapter,
            watermark=watermark,
            on_flagged=on_flagged,
            watermarker=watermarker,
            provenance_store=provenance_store,
            on_unsupported=on_unsupported,
            reuse_cached=reuse_cached,
            repair=repair,
            level=level,
            check_prompt=check_prompt,
            provider_params=by_backend,
            **affordances,
        )
    results = report.results
    if results and skipped:
        results[0].notes[:0] = [f"generation order: skipped {line}" for line in skipped]
    res = results[0] if results else None
    if res is None:
        raise GenerationError(
            f"generation via {backend!r} produced no result", report=report, status=None
        )
    if res.status in ("pass", "warn"):
        return _with_call_facts(candidate_of(res), res)
    if res.status == "skipped_dup":
        # A byte-identical regeneration is already in the library — return it (the
        # desirable flywheel behavior: never store byte-twins).
        lib = library if library is not None else default_library()
        cand = Candidate(sound=lib[res.id], origin=CandidateOrigin.generated)
        return _with_call_facts(cand, res)
    cause = res.error or "; ".join(res.notes) or res.status
    tried = f" (skipped first: {'; '.join(skipped)})" if skipped else ""
    raise GenerationError(
        f"generation via {backend!r} yielded no stored sound ({res.status}): {cause}{tried}",
        report=report,
        status=res.status,
        cache_key=res.cache_key,
    ) from report.exception


def _with_call_facts(candidate, result):
    """Copy a generation's notes, cost, raw payload and (for a preview) bytes from its ingest result."""
    candidate.notes = list(result.notes)
    candidate.cost_estimate_usd = result.cost_estimate_usd
    candidate.cost_actual_usd = result.cost_actual_usd
    candidate.audio_bytes = result.audio_bytes  # set only by store=False (#107)
    candidate.raw = result.raw  # the provider's payload beside the audio (#61)
    return candidate


def ingest(
    path,
    *,
    library=None,
    backend: str = "local",
    qc: bool = True,
    recursive: bool = True,
    **kw,
):
    """Ingest a folder (or single file) of sounds into the default library.

    ``probe -> QC -> tag -> zero-shot -> caption -> embed -> SoundRecord`` for
    each file, returning an :class:`~foley.index.IngestReport`. See
    :func:`foley.index.ingest_folder` / :func:`~foley.index.ingest_one` for the
    per-file options (``license``, taggers, ``min_status``, …).

    Args:
        path: A folder (walked) or a single audio file.
        library: Target library (default: the process-wide default library).
        backend: ``"local"`` ingests filesystem audio; other backends (a source
            adapter pull) route through ``add_from`` (subtask #5), where ``license`` is
            a search constraint (a CC licence id), not a rights assertion.
        qc: Run the Tier-0 QC gate (quarantines failing clips).
        recursive: Recurse into sub-folders.
        **kw: Forwarded to :func:`foley.index.ingest_one` — notably ``license``:
            omit it and the files' rights are **unknown** (indexed, but
            :func:`keep` refuses them for every use); pass ``license="user-owned"``
            to assert you own them (#55).
    """
    if backend != "local":
        # A non-local backend names a live source adapter (#5): treat ``path`` as
        # the query and route through the add_from pull facade (search -> license
        # gate -> download -> the shared ingest_one pipeline). There ``license`` is a
        # SEARCH constraint, not the rights assertion it is for local files (#153).
        from .licensing import is_cc_license_token

        if isinstance(kw.get("license"), str) and not is_cc_license_token(
            kw["license"]
        ):
            raise ValueError(
                f"license={kw['license']!r} asserts rights on local files; for "
                f"backend={backend!r} it is a search constraint ('cc0', a CC licence id "
                "such as 'CC-BY-4.0', or 'any'). Use backend='local' to assert rights."
            )
        return add_from(backend, query=path, library=library, **kw)
    if isinstance(kw.get("license"), str):
        from .index.ingest import resolve_ingest_license

        resolve_ingest_license(
            kw["license"]
        )  # an unknown id fails before any file is read
    return ingest_folder(
        path,
        library=library if library is not None else default_library(),
        recursive=recursive,
        do_qc=qc,
        **kw,
    )


def estimate(verb: str, **kwargs):
    """What a call would cost in USD before making it — ``None`` when it cannot be known (#57).

    ``None`` is never "free": it means the price is unknown (no pricing declared, a
    remote LLM endpoint, an unlisted model), and such a call needs the run's approval
    (``Budget(approve_unknown_cost=True)``). Paid amounts are upper bounds.

    Args:
        verb: ``'generate'`` (``backend=``, plus the generation affordances — priced
            exactly as the call would be: same drops, same clamp); ``'find'`` /
            ``'score'`` (the run's upper bound: every generation and LLM call it could
            make — what ``find`` checks against its budget before the first paid call;
            pass ``context=`` / ``segments=`` so the decomposer's prompt is sized, and
            ``score`` sums one ``find`` per segment);
            ``'search'`` / ``'similar'`` / ``'ingest'`` (local: ``0.0``);
            ``'add_from'`` (``source=``).
        **kwargs: The same keywords the verb takes.

    Raises:
        ValueError: For an unknown verb.
        KeyError: For an unknown backend / source.
    """
    from .agent.tools import estimate_find_usd
    from .cost import estimate_call
    from .sources._dispatch import estimate_generation
    from .sources.registry import SOURCE_REGISTRY, discover_sources, get_source as _get

    if verb in ("search", "similar", "ingest"):
        return 0.0
    if verb == "add_from":
        discover_sources()
        name = kwargs["source"]
        if name not in SOURCE_REGISTRY:
            _get(name)
        return estimate_call(SOURCE_REGISTRY[name]["config"])
    if verb == "generate":
        from .sources.generate import estimate_order

        return estimate_order(kwargs.pop("backend", None), **kwargs)
    if verb in ("find", "score"):
        keys = ("max_events", "backend", "llm", "k", "verify", "max_refine_loops")
        kw = {key: kwargs[key] for key in keys if key in kwargs}
        text = kwargs.get("context") or kwargs.get("segments") or ""
        segments = [text] if isinstance(text, str) else list(text)
        if verb == "find" or not segments:
            return estimate_find_usd(
                **kw, context_chars=len(segments[0]) if segments else 0
            )
        # score runs one find per segment
        per = [estimate_find_usd(**kw, context_chars=len(seg)) for seg in segments]
        return None if any(p is None for p in per) else sum(per)
    raise ValueError(
        f"estimate() knows generate, find, score, search, similar, ingest, add_from; got {verb!r}"
    )


def __getattr__(name: str):
    """Lazily expose ``foley.library``, ``foley.generations`` + the #9b disclosure helpers.

    ``library`` is kept lazy so ``import foley`` never constructs the CLAP model or
    the index; ``generations`` — the paid-generations cache, a
    :class:`~foley.stores.GenerationsCache` (``foley.generations.get(key)`` /
    ``.find(prompt, ...)``, #107) — is resolved through the dispatch path's default so
    a cache injected there (a test's in-memory one) is the one you read; the
    disclosure helpers are lazy so the (stdlib-only)
    :mod:`foley.provenance.disclosure` module is not imported until first use,
    keeping the eager ``import foley`` graph minimal.
    """
    if name == "library":
        return default_library()
    if name == "generations":
        # A fresh handle each access (cheap: two dol stores over one on-disk cache);
        # hold it in a variable for repeated use. Resolved through the dispatch path
        # so an injected default (a test's in-memory cache) is the one you read.
        from .sources._dispatch import _default_cache

        return _default_cache()
    if name in ("art50_checklist", "scan_prompt", "build_content_credential"):
        from .provenance import disclosure

        return getattr(disclosure, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
