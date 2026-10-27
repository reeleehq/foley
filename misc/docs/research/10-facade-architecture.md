# The Authoritative foley Architecture — One Coherent, Buildable Design

**Abstract.** This report synthesizes reports 01–12 into a single buildable architecture for **foley**, a retrieval-first façade that finds (or generates) the right sound effect for a moment of narration and weaves it under the voice. It fixes the four-stage spine (**SOURCE → INDEX → SELECT → WEAVE**) and the four cross-cutting layers the research surfaced — **licensing/provenance** (the `LicenseRecord` as single source of truth for *both* the candidate filter *and* the store's by-value/by-reference caching policy), **evaluation/QC**, **observability + a reproducible run-artifact**, and **`dol`-backed storage** (byte store + metadata + LanceDB vector/keyword index) — then reconciles the canonical data models, the public façade API and its unified vocabulary, the adapter/protocol contracts, the module tree and dependency-extras plan, a phased build order with a dependency graph, and closes with a concrete **EPIC + subtask breakdown** ready to seed a GitHub epic. It mirrors the façade discipline of the author's `arioso` (one entry function, config-driven plugin adapters, unified vocabulary translated per-backend, zero-dep core with lazy optional deps) and `accompy` (progressive-disclosure API, protocol-based extensibility, `check_requirements`/`verify_and_setup` onboarding) [32][33].

> Access date: 2026-07-22. This report is the map; depth and primary citations live in the eleven sibling reports [1]–[11]. Where a spec is date-sensitive it is flagged inline (notably the **EU AI Act Art. 50** disclosure duties that apply **2 August 2026** [21]).

---

## 1. Component architecture

### 1.1 The spine and the cross-cutting layers

foley is four sequential stages wrapped by four cross-cutting layers. The stages transform data; the layers observe, gate, and persist that data at every step.

```
                         ┌──────────────────────────────────────────────────────────────┐
                         │  OBSERVABILITY + RUN-ARTIFACT  (obs/)   [11][12]              │
                         │  OTel GenAI spans per tool · one run-manifest per find()/weave()│
   ┌─────────────────────┴──────────────────────────────────────────────────────────────┴──────────────┐
   │  LICENSING / PROVENANCE  (provenance/)   [1][7]                                                      │
   │  LicenseRecord = SSOT for (a) candidate keep/reject filter  AND  (b) by-value/by-reference caching   │
   │                                                                                                      │
   │   SOURCE ───────────► INDEX ──────────► SELECT ───────────► WEAVE                                    │
   │   sources/            index/            agent/              weave/                                    │
   │  ┌─────────────┐    ┌─────────────┐   ┌──────────────┐    ┌──────────────┐                           │
   │  │ retrieve:   │    │ probe→QC    │   │ decompose    │    │ align (Whisper│                          │
   │  │  Freesound  │───►│ →tag→caption│──►│  context     │───►│  X) → anchor  │                          │
   │  │  (CC0)      │    │ →embed(CLAP)│   │ → search     │    │ → mix/duck    │                          │
   │  │ generate:   │    │ →SoundRecord│   │ → verify     │    │ → master(LUFS)│                          │
   │  │  StableAudio│    │             │   │ → decide     │    │ → render      │                          │
   │  │  ElevenLabs │    │             │   │  (gen⇄retr.) │    │  (timeline)   │                          │
   │  └─────────────┘    └─────────────┘   └──────────────┘    └──────────────┘                           │
   │        │                  │                  │                    │                                  │
   │        ▼                  ▼                  ▼                    ▼                                  │
   │  ┌──────────────────────────────────────────────────────────────────────┐                          │
   │  │  STORAGE  (dol)   [4][9]   sounds:Mapping[key→bytes] · meta:Mapping[id→SoundRecord]              │
   │  │                            vindex:CLAP-512d · kindex:BM25  (one LanceDB table, local dir│s3://)  │
   │  └──────────────────────────────────────────────────────────────────────┘                          │
   │                                                                                                      │
   │  EVALUATION / QC  (eval/, qc)   [8][11]   Tier-0 audio-QC (every commit) · Tier-1 ranx retrieval     │
   │                                            metrics (frozen gold set) · Tier-2 fit-judging (nightly)  │
   └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 The four stages

**SOURCE — where sounds come from [1][2].** One adapter contract, two adapter *kinds*. **Retrieve adapters** pull existing sounds from services; **Freesound APIv2 (CC0-filtered) is the anchor** — the only source that is both self-serve-programmable *and* legally redistributable, with token search, OAuth2 download, and a built-in `laion_clap` similarity space [12]. Professional APIs (Epidemic, Storyblocks, Pond5, Pro Sound Effects) are partner-gated → ship as stub adapters. No-API web libraries (Zapsplat, Mixkit, Pixabay-audio) are link-out pointers. **Generate adapters** synthesize sounds (the `arioso` analog): default local = **Stable Audio Open 1.0** (commercial under $1M revenue; 47 s stereo) [17], default hosted = **ElevenLabs Sound Effects** (0.5–30 s, ~$0.12/min, clean commercial rights) [18]. Because most open SFX weights are CC-BY-NC, every generate adapter carries a **`commercial_ok` guardrail** [2][7].

**INDEX — making every sound findable [3][4].** A bring-your-own folder becomes searchable via a mostly-CPU, permissively-licensed ingestion pipeline: `probe → (optional) segment → supervised tag (PANNs CNN14) → zero-shot tag (CLAP vs UCS) → caption (EnCLAP) → embed (CLAP 512-d) → SoundRecord` [3]. Retrieval is **hybrid**: BM25 over tags+caption fused with CLAP vectors via **Reciprocal Rank Fusion (k=60)** — never averaging incompatible score scales [4][16]. Two taxonomies: **UCS** (82 cat / ~753 subcat, public-domain, the human browse tree and the normalization target) and the **AudioSet ontology** (632 classes, the auto ML-label layer) [15][3].

**SELECT — the right sound for a context [5].** Retrieval is a near-commodity dual-encoder, but **top-1 is right only ~30% of the time while R@10 ≈ 0.7** [5][8], so the value is in decomposition + verification, not the encoder. `decompose_context` (LLM → sparse, salience-ranked, correctly-diegetic sound-event list) → `search_sounds` (hybrid shortlist) → `verify_match` (3-tier ladder: CLAP score → audio-LM listen-check → LLM-judge) → `decide` (the one branch point: confident verified clip → use it; diegetic-no-match → **generate**, then re-verify; non-diegetic/mood → music route). Accepted generations are cached back into the library so the generate-rate decays — the **cost flywheel** [5][12].

**WEAVE — placing sound under the voice [6].** Forced-align the narration to word timestamps (**WhisperX** default, ≈±50 ms) [19], resolve each event's symbolic anchor (word/sentence/scene + pre-roll) to a sample onset, fit duration (one-shots play once; beds seamless-loop with equal-power crossfades), apply per-item processing (constant-power pan, distance→gain+LPF+reverb, ducking under speech), sum gain-staged buses, and master to a LUFS target with true-peak-safe limiting (default **−16 LUFS / −1 dBTP**) [6][20]. The deliverable is an **editable, re-renderable `SoundDesignTimeline`** — not a one-shot bake; `render(timeline, library)` is a pure function of data.

### 1.3 The four cross-cutting layers

**Licensing / provenance [1][7].** Every sound — retrieved or generated — carries a `LicenseRecord` (§2.2). It is the SSOT for two independent decisions that the research repeatedly conflates and this architecture deliberately separates:
1. **The candidate filter** — `keep(record, intended_use)` is a hard gate the SELECT stage runs *before* verification, failing closed on unverified rights [7].
2. **The store's caching policy** — whether foley persists the actual bytes (**by-value**) or only a URI + provenance (**by-reference**). Report 09 surfaced the crucial subtlety: a Freesound CC0 sound is *legally* redistributable yet its API TOS forbids "full copies of the database," so it must be stored **by-reference** [9][12]. That means `redistribute_standalone_ok` (a copyright flag) and `cache_bytes_ok` (a TOS/operational flag) are **distinct** — this architecture carries both, and `SoundRecord.storage_mode` is derived from `cache_bytes_ok`.

**Evaluation / QC [8][11].** A three-tier, testing-trophy harness: Tier-0 deterministic audio-QC on every commit (clipping/DC/silence/SNR/LUFS/edges — pure functions over a waveform); Tier-1 retrieval metrics (`ranx`: R@k, mAP@10, nDCG@10, MRR) against a **frozen gold set** on every index/model/prompt change, gating the PR on `Δ nDCG@10 ≥ −0.02`; Tier-2 audio-LM/LLM fit-judging + FAD-P/KAD backend comparison nightly/pre-release [8][29]. The gold set — the durable asset — is bootstrapped from Clotho + FSD50K + FoleySet via LLM-seeding + a short human gate [11][25][26].

**Observability + run-artifact [12].** Every tool call is an OpenTelemetry **GenAI** span (`gen_ai.request.model`, token/$ per step, the branch taken) [35]; every `find()`/`weave()` emits one **run-manifest** that is simultaneously the debug trace, the reproducible plan (maps to OTIO [24]), and the provenance/seed record. Without this the `decompose→search→verify→decide` loop is un-debuggable and un-evaluable — it is the substrate the eval harness measures.

**Storage (`dol`) [4][9].** Audio bytes live behind a `Mapping[key→bytes]` that is `dol.Files` locally and an S3 store in the cloud, **content-addressed** by `sha256` for free de-dup and immutability, kept **separate** from the light metadata/index so multi-GB blobs and small records scale independently [9][31]. The archive format is **FLAC** (lossless, 40–60% smaller than WAV, self-describing); the working representation is **`float32` NumPy @ 48 kHz** (what CLAP expects); delivery/preview is **Opus** [9].

### 1.4 Data flow (one `find()` call)

```
narration paragraph
   │  decompose_context  ──[LLM span]── plausibility/anachronism check           [5][12]
   ▼
[SoundEvent, SoundEvent, …]   (query · salience · diegetic · layer · onset · loop)
   │  for each salient event:
   │     refine_query ──► search_sounds ──► keep() license gate ──► verify_match
   │     (paraphrase-fuse)  (hybrid RRF)     (IntendedUse filter)    (CLAP→audioLM→judge)
   │                             │                                        │
   │                       [Candidate…]                              [Verdict]
   │     decide ──► retrieve (use) │ refine (loop) │ generate (fallback → re-verify → cache back)
   ▼
verified [Candidate]  ──► place_in_timeline ──► SoundDesignTimeline (sparse plan)
   ▼  (WEAVE)  align → resolve anchors → fit → mix/duck → master → render          [6]
finished mix + editable timeline + credits/C2PA + run-manifest                      [7][12]
```

Every arrow crosses the storage layer (hydrate `SoundRecord`s from `meta`, fetch bytes from `sounds` by-value or by-reference), is wrapped in an OTel span, and appends to the run-manifest. The license gate is the *only* place a candidate is rejected on rights; `decide` is the *only* place the pipeline branches on generate-vs-retrieve.

---

## 2. Reconciled canonical data models

These four models are the reconciliation of the schemas scattered across the reports. Rule of reconciliation: **`SoundRecord`** = report 04's schema, with report 09's storage fields folded in and its flat `license: str` promoted to the full **`LicenseRecord`** of report 07; **`Candidate`** = report 05's search-result shape wrapping a `SoundRecord`; **`SoundDesignTimeline`/`TimelineItem`** = report 06's schema, which is a strict superset of the SELECT stage's `place_in_timeline` output (report 05's `onset·gain·layer·loop` are the sparse subset the agent emits; WEAVE resolves the rest). All are `dataclass`es (Zod/pydantic-validatable at the persistence boundary); embeddings are referenced, not inlined, so list views stay light.

### 2.1 `LicenseRecord` — the rights + provenance SSOT

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LicenseRecord:
    """Per-sound rights + provenance. SSOT for BOTH the candidate keep()/reject
    filter (§3) AND the store's by-value/by-reference caching policy (report 09)."""

    # ── identity / origin ──────────────────────────────────────────────
    source: str  # adapter that produced it: 'freesound' | 'user' | 'stable_audio' ...
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    acquisition_method: str = "user"  # api | bulk | scrape_pointer | generated | user
    retrieved_at: Optional[str] = None  # ISO-8601
    adapter_version: Optional[str] = None
    content_sha256: Optional[str] = (
        None  # hash of canonical bytes (dedup + provenance key)
    )

    # ── rights (normalized) ────────────────────────────────────────────
    license_id: str = "unknown"  # SPDX where possible; else RemArc, Sonniss-GDC,
    #   ElevenLabs-SFX, Stability-Community, Proprietary-<vendor>
    license_name: Optional[str] = None
    license_version: Optional[str] = None
    license_url: Optional[str] = None
    rights_holder: Optional[str] = None
    creator_name: Optional[str] = None
    creator_url: Optional[str] = None

    # ── derived flags (looked up from license_id → flag-set table; SSOT for filtering) ──
    commercial_ok: bool = False  # fail-closed default
    embed_in_derivative_ok: bool = True  # ~always True (the normal case)
    redistribute_standalone_ok: bool = (
        False  # COPYRIGHT: raw-file re-exposure / sample pack
    )
    cache_bytes_ok: bool = False  # OPERATIONAL: may foley persist the bytes? (Freesound TOS ⇒ False even for CC0)
    modification_ok: bool = False
    ai_training_ok: bool = False  # feed a training/dataset pipeline
    revenue_cap_usd: Optional[int] = None  # e.g. 1_000_000 for Stability-Community

    # ── attribution ────────────────────────────────────────────────────
    requires_attribution: bool = False
    attribution_text: Optional[str] = None  # ready-to-print TASL credit line
    notice_text_required: Optional[str] = (
        None  # e.g. Stability NOTICE when redistributing weights
    )

    # ── provenance / transformation ────────────────────────────────────
    transformations: list = field(
        default_factory=list
    )  # ordered ops; non-empty ⇒ credit "(modified)"

    # ── generation (present iff AI-generated) ──────────────────────────
    is_ai_generated: bool = False
    generator_model: Optional[str] = (
        None  # "elevenlabs:eleven_text_to_sound_v2" | "stable_audio_open:1.0"
    )
    generator_version: Optional[str] = None
    generation_prompt: Optional[str] = None
    generation_seed: Optional[int] = (
        None  # None ⇒ non-deterministic backend (record it)
    )
    generation_params: dict = field(default_factory=dict)
    watermark: Optional[dict] = (
        None  # {"present": True, "method": "audioseal", "version": ...}
    )
    c2pa_manifest_ref: Optional[str] = None

    # ── safety / disclosure ────────────────────────────────────────────
    contains_recognizable_voice: bool = False
    potential_trademark: bool = False
    disclosure_recommended: bool = False  # EU AI Act Art.50 / platform label hint  [21]
    rights_verified: bool = False  # False ⇒ treated as unknown (fail-closed)
    verified_at: Optional[str] = None
```

Two maintainability rules [7]: (1) a **`license_id → flag-set` table is the SSOT** — adding a source means declaring its default `license_id`(s); the flags are looked up, never re-hand-coded (per-item license wins over source default). (2) **Never discard provenance** — even CC0 stores origin + hash + creator. The seed table (extend as sources are added): `CC0-1.0` → commercial ✓ / redistribute ✓ / cache ✓ / ai_train ✓ / attr ✗; `CC-BY-4.0` → ✓/✓/✓/✓/attr ✓; `CC-BY-NC-4.0` → commercial ✗; `Freesound-API` (per-item CC, but) → **cache_bytes_ok ✗** (TOS); `Sonniss-GDC` → commercial ✓ / redistribute ✗ / ai_train ✗; `RemArc` → commercial ✗; `Stability-Community` → commercial ✓ (revenue_cap 1M); `Proprietary-*`/unknown → all ✗ (fail-closed).

### 2.2 `SoundRecord` — the canonical per-sound record

```python
@dataclass
class SoundRecord:
    """Canonical SSOT per sound (report 04 + report 09 storage + report 07 license).
    Audio bytes and the CLAP vector live in SEPARATE stores keyed by the same id."""

    # ── identity ───────────────────────────────────────────────────────
    id: str  # stable UUID / content hash (primary key)
    content_sha256: Optional[str] = None  # content-address key into `sounds`
    hash_algo: str = "sha256"  # stored with key so mixed-hash libs stay coherent

    # ── storage (report 09) ────────────────────────────────────────────
    uri: Optional[str] = None  # blob-ref: content key | local path | s3://… | https://…
    storage_mode: str = (
        "by_reference"  # by_value | by_reference  (DERIVED from license.cache_bytes_ok)
    )
    archive_format: Optional[str] = (
        None  # 'flac' (archive) — distinct from delivered `format`
    )
    source_sample_rate: Optional[int] = None  # preserved native rate (often 96/192 kHz)
    source_bit_depth: Optional[int] = None

    # ── rights + provenance (report 07) ────────────────────────────────
    license: LicenseRecord = field(default_factory=lambda: LicenseRecord(source="user"))

    # ── descriptive text (feeds BM25 + human display) ──────────────────
    caption: Optional[str] = None
    tags: list = field(default_factory=list)  # free + controlled tags

    # ── controlled taxonomy (feeds filters & browse) ───────────────────
    ucs_category: Optional[str] = None  # UCS CatID, e.g. 'WEATHRain'
    ucs_subcategory: Optional[str] = None
    audioset_labels: list = field(
        default_factory=list
    )  # AudioSet MIDs / names (PANNs, ontology-expanded)

    # ── audio technical facts ──────────────────────────────────────────
    duration_s: Optional[float] = None
    sample_rate: Optional[int] = None  # working/delivered rate
    channels: Optional[int] = None
    loudness_lufs: Optional[float] = None  # ITU-R BS.1770-4 / EBU R128
    format: Optional[str] = None  # delivered: 'wav'|'flac'|'opus'|'mp3'

    # ── quality control (report 08; populated on ingest, becomes search filters) ──
    qc: Optional[dict] = (
        None  # {clipping, true_peak_dbtp, dc_offset, snr_db, edge_click, pass|warn|fail}
    )

    # ── retrieval index refs (NOT inlined in list views) ───────────────
    embedding_model: Optional[str] = None  # 'laion/larger_clap_general'
    embedding_dim: Optional[int] = None  # 512
    embedding_ref: Optional[str] = None  # id into vindex

    # ── cross-work continuity (report 12) ──────────────────────────────
    named_cue: Optional[str] = (
        None  # reusable motif id ("hero_door") for continuity across a work
    )

    schema_version: int = 1
```

### 2.3 `SoundEvent`, `Candidate`, `Verdict` — the SELECT-stage shapes

```python
@dataclass
class SoundEvent:
    """One salient, physically-audible event decomposed from a narrative passage."""

    query: str  # retrieval query ("heavy wooden door creaking open")
    layer: str = "sfx_fg"  # sfx_fg | ambience | stinger | music  (== timeline Layer)
    diegetic: bool = (
        True  # False ⇒ route to music/generation, judged on mood not literal content
    )
    salience: str = "medium"  # high | medium | low  (drives budget/pruning)
    onset: Optional[str] = (
        None  # symbolic anchor ("on 'pushed open'") — resolved later by WEAVE
    )
    loop: bool = False
    ucs_catid: Optional[str] = None
    audioset: list = field(default_factory=list)
    era_place: Optional[str] = (
        None  # plausibility context (anachronism guard, report 12)
    )


@dataclass
class Verdict:
    match: bool
    confidence: float  # 0..1
    reason: str = ""
    level: str = "clap"  # clap | listen | judge  (which ladder rung produced it)


@dataclass
class Candidate:
    """A ranked, license-checked, (optionally) verified sound for one SoundEvent.
    Retrieval and generation return the SAME shape (report 05) — origin is the only difference."""

    sound: SoundRecord
    origin: str = "retrieved"  # retrieved | generated
    event: Optional[SoundEvent] = None  # provenance: which event this answers
    clap_score: Optional[float] = None
    bm25_score: Optional[float] = None
    rrf_score: Optional[float] = None  # fused rank score (k=60)
    rerank_score: Optional[float] = None  # optional second-stage
    verdict: Optional[Verdict] = None
    license_ok: Optional[bool] = None  # result of keep(record, intended_use)
    preview_uri: Optional[str] = None  # short Opus preview for human audition
```

### 2.4 `SoundDesignTimeline` / `TimelineItem` — the WEAVE deliverable

Report 06's schema, verbatim in structure — a strict superset of the SELECT plan (the agent emits `onset·gain·layer·loop` per item; WEAVE resolves anchors, fills processing defaults, and reads the whole thing). Non-destructive, re-renderable, serialisable/diffable, layered, and anchor-preserving.

```python
from typing import Literal

Anchor = Literal["absolute", "word", "sentence", "scene", "paragraph"]
Layer = Literal["voice", "sfx_fg", "ambience", "stinger", "music"]


@dataclass
class Placement:  # WHERE/WHEN — symbolic anchor + resolved time
    anchor: Anchor = "absolute"
    ref: Optional[str] = None  # transcript word / sentence id / scene id
    onset: float = 0.0  # resolved start (s); filled by the aligner
    pre_roll: float = 0.0  # shift so the clip's transient lands on the anchor
    duration: Optional[float] = None  # None = full clip length
    loop: bool = False


@dataclass
class Processing:  # HOW it sounds — all optional, sensible defaults
    gain_db: float = 0.0  # relative to the voice bus
    pan: float = 0.0  # -1 (L) .. +1 (R), constant-power
    distance: float = 0.0  # 0 near .. 1 far → gain+LPF+reverb recipe
    reverb_send: float = 0.0  # 0 dry .. 1 wet (scene bus)
    fade_in: float = 0.008  # s, declick
    fade_out: float = 0.012
    duck_bed: bool = False


@dataclass
class TimelineItem:
    id: str
    clip_ref: str  # SoundRecord id in the dol library (by reference!)
    layer: Layer = "sfx_fg"
    placement: Placement = field(default_factory=Placement)
    processing: Processing = field(default_factory=Processing)
    event: Optional[SoundEvent] = None  # provenance from decompose_context
    enabled: bool = True  # non-destructive mute


@dataclass
class MasterProfile:
    target_lufs: float = -16.0  # podcast default (streaming=-14, ebu=-23, atsc=-24)
    true_peak_db: float = -1.0
    lra: float = 11.0


@dataclass
class SoundDesignTimeline:
    narration_ref: str  # the voice audio (dol ref)
    transcript: Optional[str] = None
    word_timeline: list = field(default_factory=list)  # from forced alignment (cached)
    items: list = field(default_factory=list)  # list[TimelineItem]
    master: MasterProfile = field(default_factory=MasterProfile)
    run_manifest_ref: Optional[str] = None  # join to the obs/ trace + seeds (report 12)
    schema_version: int = 1
```

---

## 3. The public façade API

Progressive disclosure (arioso/accompy discipline): the simple thing is one call with sensible defaults; every model/index/threshold is an optional keyword override (open-closed). The library itself is a `dol` `Mapping`.

```python
import foley

# ── The headline: right sounds for a narrative context (decompose→search→verify→decide) ──
candidates = foley.find(
    "She pushed open the heavy oak door; rain hammered outside.",
    *, max_events=6, intended_use=None, backend="auto", verify="listen", stream=False,
) -> list[Candidate]

# ── Direct hybrid search of the library (text query OR a reference clip) ──
hits = foley.search(
    "distant thunder rumble", *, k=10, filters=None, commercial_ok=True,
    ucs_category=None, min_snr=None, rerank=False,
) -> list[Candidate]
foley.similar(sound_id, *, k=10) -> list[Candidate]              # audio↔audio via CLAP

# ── Generate when nothing fits (arioso-style: backend + unified vocabulary) ──
clip = foley.generate(
    "a single wooden door creak", *, backend="stable_audio",
    duration_s=3, prompt_influence=0.5, negative_prompt="music, speech", seed=None,
) -> Candidate                                                    # commercial_ok guardrail enforced

# ── Grow the library: ingest auto-tags/captions/embeds; pull from a source ──
foley.ingest("~/my_sounds/", *, backend="local", qc=True) -> IngestReport
foley.add_from("freesound", *, query="ocean waves", license="cc0", limit=50) -> list[SoundRecord]

# ── Compose (WEAVE): resolve the plan onto a narration and render ──
timeline = foley.plan(candidates, *, transcript=None) -> SoundDesignTimeline
mix = foley.weave(narration_audio, timeline, *, master="podcast") -> WeaveResult   # audio + credits + captions

# ── The library IS a dol Mapping of SoundRecords ──
lib = foley.library                          # SoundLibrary facade
lib[sound_id]                                # -> SoundRecord   (from meta)
lib.audio(sound_id)                          # -> bytes         (by-value or fetched by-reference)
lib.array(sound_id, sr=48000, mono=True)     # -> float32 np    (lazy decode → working array)

# ── Onboarding (accompy-style) ──
foley.check_requirements() ; foley.verify_and_setup()
foley.mcp_server()                           # publish tools as MCP via py2mcp
```

### 3.1 The unified vocabulary (the `arioso` `AFFORDANCES` analog)

foley carries **two affordance registries** — a **query vocabulary** (for `find`/`search`) and a **generation vocabulary** (for `generate`, mirroring report 02) — each a `dict[str, Affordance]` exactly like `arioso.base.AFFORDANCES`, so every adapter maps foley's canonical names to its native params and no caller learns backend-specific spellings [32].

```python
@dataclass(frozen=True)
class Affordance:
    name: str
    type: type
    description: str
    default: object = None
    stage: str = "query"


QUERY_AFFORDANCES = {  # for search_sounds / find / library.filter
    "text": Affordance("text", str, "Natural-language query"),
    "semantic_text": Affordance(
        "semantic_text", str, "Query for CLAP semantic space", stage="query"
    ),
    "k": Affordance("k", int, "Number of results", 10),
    "filters": Affordance("filters", dict, "Metadata predicates (SQL-style)"),
    "ucs_category": Affordance("ucs_category", str, "UCS CatID facet"),
    "audioset_label": Affordance(
        "audioset_label", str, "AudioSet ontology facet (rolls up children)"
    ),
    "duration_range": Affordance("duration_range", tuple, "(min_s, max_s)"),
    "min_snr": Affordance("min_snr", float, "QC filter: min SNR dB"),
    "commercial_ok": Affordance("commercial_ok", bool, "License filter shorthand"),
    "license": Affordance("license", str, "Explicit license id constraint"),
    "sort": Affordance("sort", str, "score|duration|created|downloads", "score"),
    "rerank": Affordance(
        "rerank", bool, "Apply second-stage CLAP/cross-encoder rerank", False
    ),
}

GENERATION_AFFORDANCES = {  # for generate (translated per backend; report 02 §Recommendations)
    "prompt": Affordance("prompt", str, "Sound description", stage="generate"),
    "duration": Affordance(
        "duration", float, "Seconds; None ⇒ backend default", stage="generate"
    ),
    "prompt_influence": Affordance(  # None => the backend's native default (#70)
        "prompt_influence", float, "0..1 unified adherence", stage="generate"
    ),
    "negative_prompt": Affordance(
        "negative_prompt", str, "Content to exclude", stage="generate"
    ),
    "steps": Affordance("steps", int, "Diffusion/flow steps", stage="generate"),
    "seed": Affordance(
        "seed", int, "Reproducibility (capture in provenance)", stage="generate"
    ),
    "loop": Affordance("loop", bool, "Seamless-loopable clip", False, "generate"),
    "output_format": Affordance(
        "output_format", str, "wav|opus|mp3", "wav", "generate"
    ),
}

# translation example (report 02): duration → {elevenlabs: duration_seconds, stable_audio: audio_end_in_s,
#   audiogen: set_generation_params(duration=), fal: seconds_total}; prompt_influence → {elevenlabs: prompt_influence,
#   diffusers: guidance_scale, audiogen: cfg_coef}; negative_prompt dropped for elevenlabs/audiogen.
```

The caller's rights intent is a first-class object the license gate consumes (report 07):

```python
@dataclass
class IntendedUse:
    commercial: bool = True
    publish: bool = True
    redistribute_standalone: bool = False
    will_train: bool = False
    can_attribute: bool = True
    revenue_usd: int = 0
    allow_voice_or_trademark: bool = False
```

---

## 4. Adapter & protocol contracts

### 4.1 The `SOURCE_CONFIG` plugin pattern

Mirrors `arioso`'s `PLATFORM_CONFIG` exactly — a package under `foley/sources/<name>/` with a `config.py` (defining `SOURCE_CONFIG`) and an optional `adapter.py`, auto-discovered by `foley/sources/registry.py`, lazily loaded, with `register_source()` for out-of-tree plugins [1][32]. The reconciled config adds a first-class **`kind`** (retrieve|generate), a **`license`** block (report 01/07), a **`commercial_ok` guardrail** for generate adapters (report 02), and **`rate_limits`/`cost`/`offline_capable`/`data_egress`** metadata for the quota-orchestration + privacy dimensions (report 12).

```python
# foley/sources/freesound/config.py
SOURCE_CONFIG = {
    "name": "freesound",
    "kind": "retrieve",  # retrieve | generate
    "access_type": "rest_api",  # rest_api | partner_api | bulk_corpus | scrape | no_api
    "auth": {
        "type": "api_key",
        "env_var": "FREESOUND_API_KEY",
        "query_param": "token",
        "download_requires": "oauth2",
    },
    "dependencies": ["requests"],
    "optional_dependencies": ["freesound"],
    "capabilities": [
        "search",
        "text_similarity",
        "similarity",
        "preview",
        "download",
        "analysis",
    ],
    # unified vocabulary → this source's native params
    "query_map": {
        "text": {"native_name": "query"},
        "k": {"native_name": "page_size", "native_default": 15},  # max 150
        "duration_range": {
            "native_name": "filter",
            "to_native": lambda lo, hi: f"duration:[{lo} TO {hi}]",
        },
        "license": {
            "native_name": "filter",
            "to_native": lambda lic: f'license:"{LICENSE_TO_FREESOUND[lic]}"',
        },
        "semantic_text": {
            "native_name": "similarity_space",
            "native_default": "laion_clap",
        },
    },
    # license policy — resolved per item, gates BOTH filtering and caching
    "license": {
        "per_item": True,
        "field": "license",
        "default_id": None,
        "cache_bytes_ok": False,
    },  # TOS: no full DB copies ⇒ store by-reference
    "output": {
        "formats": ["wav", "aiff", "flac", "ogg", "mp3"],
        "preview_formats": ["mp3", "ogg"],
    },
    "api": {
        "base_url": "https://freesound.org/apiv2",
        "search_endpoint": {"method": "get", "path": "/search/"},
        "download_endpoint": {"method": "get", "path": "/sounds/{id}/download/"},
    },
    "rate_limits": {"per_minute": 60, "per_day": 2000},
    "cost": {"per_call_usd": 0.0},
    "offline_capable": False,
    "data_egress": {
        "sees_query_text": True,
        "sees_narration": False,
    },  # privacy declaration (report 12)
}
```

A **generate** config additionally carries `"commercial_ok": <bool>` and a `prompt_template` mapping the unified `decompose` output into the backend's preferred phrasing/tag order (report 02/12); e.g. `stable_audio_open` → `commercial_ok: True, revenue_cap_usd: 1_000_000`; `audiogen` → `commercial_ok: False` (CC-BY-NC). Bulk-corpus "sources" (FSD50K, Sonniss, BBC) implement the *same* adapter protocol over a local `dol` store instead of HTTP, so the caller sees one uniform interface whether audio is remote, cached, or local.

### 4.2 The key `Protocol`s

Structural interfaces (PEP 544), `@runtime_checkable`, dependency-injected by keyword — the accompy pattern [33]. Each has a zero-config sensible default; every one is swappable.

```python
from typing import Protocol, Optional, runtime_checkable


@runtime_checkable
class SourceAdapter(Protocol):
    """Retrieve OR generate. Both return the same Candidate/SoundRecord shape."""

    def search(self, query: str, **kw) -> list[Candidate]: ...  # retrieve
    def get(self, source_id: str) -> SoundRecord: ...
    def download(self, source_id: str) -> bytes: ...
    def generate(
        self, prompt: str, **kw
    ) -> Candidate: ...  # generate (guarded by commercial_ok)


@runtime_checkable
class Embedder(Protocol):
    """Joint text↔audio space. Default: laion/larger_clap_general (512-d, Apache-2.0)."""

    model_id: str
    dim: int

    def embed_text(self, text: str | list[str]) -> "ndarray": ...  # L2-normalized
    def embed_audio(self, wav: "ndarray", sr: int) -> "ndarray": ...


@runtime_checkable
class Tagger(Protocol):  # PANNs CNN14 default; BEATs/AST upgrade
    def tag(
        self, wav: "ndarray", sr: int, *, taxonomy: str = "audioset"
    ) -> list[tuple[str, float]]: ...


@runtime_checkable
class Captioner(Protocol):  # EnCLAP default; Qwen2-Audio richer
    def caption(self, wav: "ndarray", sr: int) -> str: ...


@runtime_checkable
class VectorIndex(Protocol):  # LanceDB default; Qdrant/pgvector cloud
    def upsert(self, id: str, vector: "ndarray", meta: dict) -> None: ...
    def knn(
        self, vector: "ndarray", k: int, *, where: dict | None = None
    ) -> list[tuple[str, float]]: ...


@runtime_checkable
class KeywordIndex(Protocol):  # LanceDB FTS (Tantivy) / sqlite FTS5
    def index(self, id: str, text: str, meta: dict) -> None: ...
    def bm25(
        self, query: str, k: int, *, where: dict | None = None
    ) -> list[tuple[str, float]]: ...


@runtime_checkable
class Store(Protocol):  # a dol Mapping; Files→S3
    def __getitem__(self, key: str) -> bytes: ...
    def __setitem__(self, key: str, value: bytes) -> None: ...
    def __contains__(self, key: str) -> bool: ...


@runtime_checkable
class Aligner(Protocol):  # WhisperX default; MFA/aeneas opt-in
    def word_timeline(
        self, audio_path: str, *, transcript: str | None = None, language: str = "en"
    ) -> list[dict]: ...  # [{'word','start','end'}, …]


@runtime_checkable
class Judge(Protocol):  # verify_match rung: CLAP|audio-LM|LLM
    def judge(
        self, event: SoundEvent, candidate: Candidate, *, level: str = "clap"
    ) -> Verdict: ...


@runtime_checkable
class ApplyStrategy(Protocol):  # how a chosen sound is realized in WEAVE
    """full | camera_only-equivalent (place-only) | diff-preview | transition — swappable render behaviors."""

    def apply(self, item: TimelineItem, buses: dict, library, *, sr: int) -> dict: ...
```

---

## 5. Module layout & dependency plan

```
foley/
    __init__.py          # façade: find(), search(), similar(), generate(), ingest(), add_from(),
                         #         plan(), weave(), library, check_requirements(), mcp_server()
    base.py              # SoundRecord, LicenseRecord, Candidate, SoundEvent, Verdict, IntendedUse,
                         #   QUERY_AFFORDANCES, GENERATION_AFFORDANCES, Affordance
    registry.py          # adapter auto-discovery + lazy loading + register_source()
    audio.py             # I/O + DSP primitives: soundfile/soxr/librosa/pyloudnorm; FLAC⟷float32@48k
    sources/             # source adapters (config.py + adapter.py each)
        registry.py      #   scans this package for SOURCE_CONFIG
        freesound/       #   retrieve (CC0-filtered, by-reference) — the anchor
        stable_audio/    #   generate (local default; commercial_ok guardrail)
        elevenlabs/      #   generate (hosted default)
        fsd50k/  clotho/  foleyset/   #   bulk-corpus "sources" over local dol stores
        epidemic/ storyblocks/ pond5/ pse/   #   partner stubs
    index/
        ingest.py        # probe → QC → tag → zero-shot → caption → embed → SoundRecord
        taggers.py       # Tagger / Captioner impls (PANNs, CLAP-zero-shot, EnCLAP, Qwen2-Audio)
        embedders.py     # Embedder impls (CLAP default; MS-CLAP/PANNs/GLAP swappable)
        library.py       # SoundLibrary facade (sounds/meta/vindex/kindex injected dol stores)
        search.py        # hybrid search + RRF; second-stage rerank
        indexes.py       # VectorIndex/KeywordIndex impls (LanceDB; sqlite-vec fallback)
        taxonomy/        # UCS + AudioSet ontology tables + tags→CatID resolver (EnvSound-UCS map)
    agent/
        decompose.py     # context → SoundEvent list (LLM) + anachronism/plausibility check
        refine.py        # query paraphrase/expansion + embedding fusion
        verify.py        # verification ladder + Judge impls
        policy.py        # decide() generate-vs-retrieve; semantic-cache admission
        tools.py         # the pure tool functions (Python API == agent == MCP surface)
        mcp.py           # py2mcp server (mk_mcp_server / mk_http_app / mk_mcp_from_store)
    weave/
        align.py         # forced-alignment adapters (Aligner: whisperx default; mfa/aeneas opt-in)
        anchor.py        # symbolic-anchor → onset heuristics (pure fns)
        mix.py           # gain, constant-power pan, distance, reverb, ducking, crossfade/declick
        master.py        # LUFS normalise (pyloudnorm) + true-peak limit; MasterProfile targets
        timeline.py      # SoundDesignTimeline / TimelineItem schemas
        render.py        # render(timeline, library) -> audio ; OTIO/EDL export adapter
        captions.py      # WebVTT/SRT SDH accessibility export from the event list (report 12)
    provenance/
        license.py       # license_id → flag-set table; keep()/IntendedUse gate; storage_mode derivation
        credits.py       # TASL attribution generator; CREDITS.md + JSON manifest
        disclosure.py    # AudioSeal watermark + C2PA manifest writers; EU AI Act Art.50 checklist
    eval/
        qc.py            # Tier-0 deterministic audio-QC (pure functions → QCReport)
        retrieval.py     # Tier-1 ranx metrics over frozen gold set (R@k, mAP@10, nDCG@10, MRR)
        fit.py           # Tier-2 audio-LM/LLM fit-judging; PAM/Audiobox-PQ; FAD-P/KAD
        golden.py        # golden (context → expected-sound) set builder + fixtures
    obs/
        trace.py         # OpenTelemetry GenAI spans around every tool
        run_artifact.py  # per-find()/weave() run-manifest (trace ⊕ plan ⊕ provenance/seeds)
```

**Optional-extras plan** (zero-dep core = façade + base types + registry + `dol`/`config2py` plumbing; everything else lazy, per arioso/accompy):

| Extra | Pulls in | Enables |
|---|---|---|
| *(core)* | `dol`, `config2py` (both light) | schemas, registry, library facade skeleton, `dol` stores |
| `foley[audio]` | `soundfile`, `soxr`, `numpy` | I/O + DSP primitives (FLAC⟷float32@48k), Tier-0 QC |
| `foley[clap]` | `transformers`, `torch` | CLAP `Embedder` (the retrieval engine) |
| `foley[index]` | `lancedb` | LanceDB vindex+kindex + hybrid RRF (`sqlite-vec` fallback needs no extra) |
| `foley[tag]` | `panns-inference`, `librosa` | supervised + zero-shot tagging on ingest |
| `foley[caption]` | `transformers`, `torch` | EnCLAP / Qwen2-Audio captioner |
| `foley[freesound]` | `requests` (+opt `freesound`) | Freesound retrieve adapter |
| `foley[stable-audio]` | `diffusers`, `torch`, `soundfile` | local Stable Audio Open generate adapter |
| `foley[elevenlabs]` | `elevenlabs` | hosted ElevenLabs SFX generate adapter |
| `foley[agent]` | an LLM client (+ opt `torch` for audio-LM verify) | decompose/verify/decide |
| `foley[align]` | `whisperx`, `torch` (`[align-mfa]`, `[align-aeneas]` variants) | WEAVE forced alignment |
| `foley[weave]` | `numpy`, `scipy`, `pyroomacoustics`, `pyloudnorm` | mix + master |
| `foley[provenance]` | `audioseal`, a C2PA writer | watermark + Content Credentials |
| `foley[eval]` | `ranx`, `pytrec_eval`, `pam`, `audiobox_aesthetics` | eval harness Tiers 1–2 |
| `foley[obs]` | `opentelemetry-sdk` | GenAI tracing + run-artifacts |
| `foley[mcp]` | `py2mcp` | MCP server |
| `foley[all]` | everything above | — |

**System deps (never bundled; surfaced via `check_requirements`)**: `ffmpeg` (MP3/AAC/Opus transcode — LGPL/GPL + patent risk), `rubberband` (hi-fi stretch — GPL) [9]. Both are optional external tools discovered at runtime, mirroring accompy's FluidSynth onboarding.

---

## 6. Phased build order & dependency graph

### 6.1 Dependency graph (what blocks what)

```
                       ┌─────────────────────────────────────────────┐
        base.py (models) ─┬─► dol stores ─┬─► SoundLibrary ─┬─► search.py ─┐
        [S1]              │  [S2]         │   [S6]          │   (in S6)     │
   audio.py (I/O+DSP) ────┤               │                 │               │
        [S3] ─────────────┼─► Embedder ───┴─► LanceDB idx ──┘               │
                          │   [S4]            [S5]                           │
        taxonomy [S7] ────┘                                                 │
                                                                            ▼
        qc [S9] ──► ingest [S8] ──► seed corpora [S10] ─────────────► search()  ◄══ KEYSTONE (Phase 1)
                                                                            │
   ┌────────────────────────────────────────────────────────────────────┐ │
   │ source contract [S11] ─► freesound [S12] / stable-audio [S13] /     │ │
   │                          elevenlabs [S14] ─► generate() [S15]       │ │  (Phase 2)
   └────────────────────────────────────────────────────────────────────┘ │
                                                                            ▼
        decompose [S17] ─► search_sounds [S18] ─► verify [S19] ─► decide [S21] ─► find() [S22]
                                        license gate [S20] ──────────┘                  │  (Phase 3)
                                                                                        ▼
        obs/run-artifact [S23] ·· provenance/credits/disclosure [S24] ·· eval [S25,S26]  (cross-cut)
                                                                                        │
        timeline [S27] ─► align [S28] ─► mix/master [S29] ─► render [S30] ─► weave() [S31]  (Phase 5)
        mcp [S32] · preview/audition [S33] · onboarding/degradation [S34] · offline/privacy [S35]  (Phase 4/UX)
```

**Build order (foundation → index → sources → select → weave → mcp/ux):**
1. **Foundation** (S1–S3): models, `dol` stores, audio I/O — nothing works without these; fully parallelizable.
2. **Index / keystone** (S4–S10): the retrieval library. *This is the keystone; everything plugs into it.*
3. **Sources** (S11–S16): retrieve + generate adapters landing sounds into the library.
4. **Select** (S17–S22): the headline `find()` agent.
5. **Cross-cutting** (S23–S26): observability, provenance/disclosure, eval — start S23/S24 alongside S17 (they wrap the agent), S25 alongside S10.
6. **Weave** (S27–S31): compositing.
7. **MCP / UX** (S32–S35): exposure and onboarding.

### 6.2 Smallest end-to-end vertical slice (proves the concept)

Two nested slices:

- **Keystone slice (proves INDEX — build first):** `base.py` models (S1) + content-addressed `dol` stores (S2) + audio I/O (S3) + CLAP `Embedder` (S4) + LanceDB hybrid search (S5) + `SoundLibrary` (S6) + minimal `ingest` (S8) → `foley.ingest("~/sounds")` then `foley.search("thunder")` returns license-tagged, ranked hits by keyword **and** semantics. This is the retrieval foundation the design calls the keystone.

- **Thin full-pipeline slice (proves the whole vision):** on top of the keystone, add a minimal `decompose_context` (S17, one LLM call → events), `search_sounds` + CLAP-only `verify` (S18–S19), a trivial `decide` (retrieve-only, no generation yet), and a *bare* WEAVE — align one narration with WhisperX (S28), place one one-shot at one word anchor, duck a bed, master to −16 LUFS (S29–S30). End-to-end: **paragraph → one verified sound → placed under a voice → mixed file + editable timeline.** This validates SOURCE→INDEX→SELECT→WEAVE before deepening any single stage — the retrieval-first strategy the roadmap mandates.

---

## 7. Proposed EPIC + subtask breakdown

**EPIC — Build foley: a retrieval-first SFX façade (SOURCE → INDEX → SELECT → WEAVE).**
*Scope:* implement the four-stage spine and four cross-cutting layers of this architecture, mirroring `arioso`'s façade discipline and `accompy`'s onboarding. Deliver in retrieval-first order: a searchable, license-aware library (keystone) → sources → the `find(context)` agent → weave → MCP/UX, with observability, provenance/disclosure, and a three-tier eval harness built in from the start. Definition of done for v1: `foley.find(paragraph)` returns verified, license-clean candidates and `foley.weave(narration, timeline)` renders a mastered mix with an editable timeline, credits, captions, and a reproducible run-artifact.

Subtasks (each: **title** — scope · *reports* · deps · size). Ordered; sizes S/M/L.

**Phase 1 — Foundation & Index (keystone)**
1. **Canonical data models (`base.py`)** — `SoundRecord`, `LicenseRecord`, `Candidate`, `SoundEvent`, `Verdict`, `IntendedUse` + `license_id→flags` table + both affordance registries. *[4][7][9]* · deps: — · **M**
2. **`dol` store layer** — content-addressed (`sha256`) byte store + `meta` store; by-value/by-reference gate driven by `LicenseRecord.cache_bytes_ok`; `~/.local/share/foley/`. *[9][7]* · deps: 1 · **M**
3. **Audio I/O + DSP primitives (`audio.py`)** — `soundfile`/`soxr`/`librosa`/`pyloudnorm`; FLAC archive ⟷ `float32`@48 kHz working; trim/fade/resample/mono/LUFS. *[9]* · deps: — · **M**
4. **`Embedder` protocol + CLAP default** — `laion/larger_clap_general` (512-d); stamps `embedding_model`/`dim`. *[3][4]* · deps: 1, 3 · **S**
5. **LanceDB `vindex`+`kindex` + hybrid search + RRF** — one table (vector + BM25); `RRFReranker` (k=60); `sqlite-vec`+FTS5 fallback. *[4]* · deps: 1, 4 · **M**
6. **`SoundLibrary` façade + `foley.search()`** — composes injected `sounds`/`meta`/`vindex`/`kindex`; `search`/`similar`/`filter`/`audio`/`array`; `dol` `Mapping` surface. *[4][9]* · deps: 2, 5 · **M**
7. **Taxonomy tables + `tags→CatID` resolver** — UCS (browse tree/normalization target) + AudioSet ontology; adopt EnvSound-UCS mapping tables. *[1][4][11]* · deps: 1 · **S**
8. **Ingestion pipeline (`ingest.py`)** — `probe→QC→PANNs tag→CLAP zero-shot→EnCLAP caption→embed→SoundRecord`; lazy-loaded, `dol.cache_this` memoized. *[3][8][9]* · deps: 3, 4, 6, 7, 9 · **L**
9. **Tier-0 audio-QC (`eval/qc.py`)** — pure-function clip/DC/silence/SNR/edge/LUFS/duration/NaN checks → `QCReport`; unit tests on defect fixtures. *[8]* · deps: 3 · **S**
10. **Seed-corpora bootstrap** — ship Clotho-eval + FoleySet (CC-BY, redistributable, self-testing); `foley bootstrap` fetches FSD50K CC0/CC-BY; quarantine Sonniss/BBC behind explicit opt-in (`ai_training_ok=False`). *[11]* · deps: 6, 8 · **M**

**Phase 2 — Sources (retrieve + generate)**
11. **Source-adapter contract + registry** — `SOURCE_CONFIG` (kind, license, rate/cost/egress), auto-discovery, `register_source()`; `SourceAdapter` protocol. *[1][2][12]* · deps: 1 · **M**
12. **Freesound retrieve adapter** — CC0-filtered search/preview/download; by-reference caching (TOS); per-item `LicenseRecord`. *[1][9]* · deps: 6, 11 · **M**
13. **Stable Audio Open generate adapter (local default)** — `diffusers`; `commercial_ok`+`revenue_cap` guardrail; seed capture. *[2]* · deps: 11 · **M**
14. **ElevenLabs SFX generate adapter (hosted default)** — `POST /v1/sound-generation`; clean commercial rights on paid tier. *[2]* · deps: 11 · **S**
15. **`generate()` façade + prompt-template layer** — unified `GENERATION_AFFORDANCES` → per-backend params; generate-per-event, negative-prompt defaults. *[2][12]* · deps: 13, 14 · **M**
16. **Partner-API stub adapters** — Epidemic/Storyblocks/Pond5/PSE wired-when-agreements-exist. *[1]* · deps: 11 · **S**

**Phase 3 — Select agent (`find`)**
17. **`decompose_context` + plausibility guard** — LLM: paragraph → salience-ranked, diegetic-tagged `SoundEvent`s under a density budget; LLM anachronism/cultural-temporal check. *[5][12]* · deps: 1 · **M**
18. **`search_sounds` + `refine_query` tools** — paraphrase-fuse CLAP text embeddings; hybrid retrieve top-k. *[5]* · deps: 6, 17 · **S**
19. **`verify_match` ladder + `Judge` impls** — CLAP-gate → audio-LM listen-check (Qwen2-Audio/AQAScore) → LLM-judge; cross-event scene consistency. *[5][8]* · deps: 18 · **M**
20. **License-compatibility gate** — `keep(record, IntendedUse)` hard gate *before* verification; fail-closed; push filter into source queries. *[7]* · deps: 1, 18 · **S**
21. **`decide()` policy + generation flywheel** — generate-vs-retrieve branch; re-verify generations; cache accepted generations back (semantic-cache admission via `verify_match`); track generate-rate decay. *[5][12]* · deps: 15, 19, 20 · **M**
22. **`find()` façade** — orchestrate decompose→search→verify→decide → verified `Candidate` shortlist; streamable. *[5]* · deps: 21 · **S**

**Cross-cutting (start alongside Phase 3)**
23. **Observability + run-artifact (`obs/`)** — OTel GenAI spans per tool; one run-manifest per `find()`/`weave()` (trace ⊕ plan ⊕ seeds). *[12]* · deps: 17–22 · **M**
24. **Provenance, credits & disclosure (`provenance/`)** — TASL attribution generator + `CREDITS.md`/JSON; AudioSeal watermark + C2PA manifest on generations; **EU AI Act Art. 50 checklist (deadline 2 Aug 2026)**. *[7][12]* · deps: 1, 15 · **M**
25. **Eval Tier-1 + golden set (`eval/`)** — `ranx` R@k/mAP@10/nDCG@10/MRR on a frozen gold set; PR gate `Δ nDCG@10 ≥ −0.02`; build the (context→expected-sound) golden fixture (LLM-seed + human gate). *[8][11]* · deps: 6, 10, 22 · **L**
26. **Eval Tier-2 (fit-judging + fidelity)** — audio-LM/LLM fit-judge on a stratified sample; PAM/Audiobox-PQ generation gates; FAD-P (PANNs)/KAD backend comparison; Krippendorff-α judge calibration. *[8]* · deps: 19, 25 · **M**

**Phase 5 — Weave**
27. **`SoundDesignTimeline` data model** — schemas (superset of the SELECT plan); named-cue continuity + persistent beds; seed/provenance capture. *[6][12]* · deps: 1 · **M**
28. **Forced alignment + anchor heuristics** — `Aligner` (WhisperX default; MFA/aeneas opt-in); word/sentence/scene→onset (+pre-roll) pure fns. *[6]* · deps: 3, 27 · **M**
29. **Mix + master** — gain/constant-power pan/distance/reverb/ducking/crossfade/declick + LUFS-normalize + true-peak limit; `MasterProfile` targets. *[6]* · deps: 3, 27 · **L**
30. **`render()` + OTIO export** — pure `render(timeline, library)`; incremental re-render; OTIO/EDL export adapter. *[6][12]* · deps: 27, 28, 29 · **M**
31. **`weave()` façade + accessibility captions** — orchestrate align→resolve→mix→master; WebVTT/SRT SDH export (bracket/present-tense/title-case) from the event list. *[6][12]* · deps: 30 · **M**

**Phase 4 — MCP & UX**
32. **MCP server via `py2mcp`** — `mk_mcp_server` (stdio) + `mk_http_app` (hosted); `mk_mcp_from_store` for the library. *[5]* · deps: 22 · **S**
33. **Preview / audition UX** — `preview`, `similar_to`, `refine` (relevance-feedback query re-weighting); persist accepted pick into the plan. *[5][12]* · deps: 22 · **M**
34. **Onboarding + graceful degradation** — `check_requirements`/`verify_and_setup` (accompy-style); per-adapter throttle/backoff/circuit-break; budget caps; degradation ladder (cloud gen → local gen → retrieval-only → link-out). *[12]* · deps: 11 · **M**
35. **Local-first/offline mode + data-egress** — offline path (local LLM + Stable Audio Open + local index) for sensitive narrations; per-adapter `data_egress` declaration; telemetry redaction policy. *[12]* · deps: 11, 17 · **M**

---

## Recommendations for foley

**Phased build order (the through-line).** Build **retrieval-first**: (1) the **keystone** — a `dol`-backed, license-aware, CLAP+BM25 hybrid `SoundLibrary` that `ingest`s a folder and `search`es it (subtasks 1–10) — *before* sources multiply or generation/weaving deepen; (2) **sources** (11–16) to fill it; (3) the **`find(context)` agent** (17–22), foley's headline, where decomposition + verification (not the swappable CLAP encoder) are the moat; (4) **weave** (27–31); (5) **MCP/UX** (32–35). Wire the four cross-cutting layers in from day one, not as polish: **licensing/provenance** (the `LicenseRecord` gating both the candidate filter *and* by-value/by-reference caching), **Tier-0 audio-QC** (nearly free, prevents the most embarrassing failures), **observability + run-artifact** (the substrate the eval harness and the editable-timeline vision both need), and the **`dol` byte/meta/index split**. Prove the concept with the **keystone slice** first (`ingest`→`search` returns ranked, license-tagged hits), then the **thin full-pipeline slice** (paragraph → one verified sound → placed under a voice → mastered mix + editable timeline).

**Highest-leverage / time-sensitive bets.** (a) The **gold set** is the durable asset (subtask 25) — a ~150-item (context→expected-sound) fixture makes every future model/index/prompt change measurable; spend the human hours once. (b) **Verification** (19) is what lets foley auto-accept without a human on every clip — invest here before chasing +2 mAP on the encoder. (c) The **generation flywheel** (21) turns every accepted generation into a future free retrieval — build the cache-back early since it changes the store schema. (d) **Disclosure/watermarking (24) is deadline-driven** — EU AI Act Art. 50 machine-readable-marking + deepfake-disclosure duties apply **2 August 2026** [21], inside the build window; land AudioSeal + C2PA + the Art. 50 checklist before shipping AI-generated SFX in published output.

**The epic and its 35 ordered subtasks above are ready to seed the GitHub epic** — grouped by phase, each tagged with the reports that back it, its dependencies, and a size estimate, and folding in report 12's flagged items: safety/disclosure/watermarking (24), observability + run-artifact (23), the caching flywheel (21), accessibility captioning (31), and the cultural/temporal plausibility guard (17).

---

## REFERENCES

Sibling research reports (this report synthesizes them; each carries its own primary-source citations):

1. foley research 01 — *SFX Source APIs & Sound Libraries.* [`research/01-sfx-source-apis.md`](01-sfx-source-apis.md)
2. foley research 02 — *Generative-AI SFX Generation: Local Models and Hosted APIs.* [`research/02-genai-sfx-generation.md`](02-genai-sfx-generation.md)
3. foley research 03 — *Sound Recognition, Auto-Tagging, Captioning & Segmentation.* [`research/03-sound-recognition-tagging.md`](03-sound-recognition-tagging.md)
4. foley research 04 — *Audio Embeddings, Indexing, Vector Search, Taxonomies & the Sound Metadata Schema.* [`research/04-embeddings-indexing-search.md`](04-embeddings-indexing-search.md)
5. foley research 05 — *Context-to-Sound Retrieval and the Search-Agent Architecture.* [`research/05-context-retrieval-and-agent.md`](05-context-retrieval-and-agent.md)
6. foley research 06 — *Weaving SFX into Narration: Alignment, Timing, Mixing & Mastering.* [`research/06-weaving-mixing-mastering.md`](06-weaving-mixing-mastering.md)
7. foley research 07 — *Licensing, Rights, Provenance & Attribution.* [`research/07-licensing-provenance.md`](07-licensing-provenance.md)
8. foley research 08 — *Evaluation & Quality.* [`research/08-evaluation-quality.md`](08-evaluation-quality.md)
9. foley research 09 — *Audio I/O, Formats, DSP Fundamentals & Storage.* [`research/09-audio-io-dsp-storage.md`](09-audio-io-dsp-storage.md)
10. foley research 11 — *Bootstrap Corpora & Benchmarks for a Starter Library.* [`research/11-bootstrap-corpora-benchmarks.md`](11-bootstrap-corpora-benchmarks.md)
11. foley research 12 — *Dimensions We Haven't Named Yet (Meta-Scan).* [`research/12-additional-dimensions.md`](12-additional-dimensions.md)

Key primary sources:

12. Freesound APIv2 — Resources (search, `filter=license:…`, `similarity_space=laion_clap`). [freesound.org/docs/api/resources_apiv2.html](https://freesound.org/docs/api/resources_apiv2.html) · TOS: [freesound.org/help/tos_api](https://freesound.org/help/tos_api/)
13. Wu Y. et al. *Large-Scale Contrastive Language-Audio Pretraining (LAION-CLAP)*, arXiv:2211.06687. [arxiv.org/abs/2211.06687](https://arxiv.org/abs/2211.06687) · model [laion/larger_clap_general](https://huggingface.co/laion/larger_clap_general)
14. LanceDB — embedded vector + BM25 (Tantivy) + `RRFReranker`; local dir or `s3://`. [github.com/lancedb/lancedb](https://github.com/lancedb/lancedb) · [docs.lancedb.com/search/hybrid-search](https://docs.lancedb.com/search/hybrid-search)
15. Universal Category System (UCS) — 82 cat / ~753 subcat, CatID + filename convention, public domain. [universalcategorysystem.com](https://universalcategorysystem.com/)
16. Cormack G.V., Clarke C.L.A., Büttcher S. *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods* (RRF, k=60), SIGIR 2009. [cormack.uwaterloo.ca/cormacksigir09-rrf.pdf](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
17. Evans Z. et al. *Stable Audio Open*, arXiv:2407.14358 · Community License. [arxiv.org/abs/2407.14358](https://arxiv.org/abs/2407.14358) · [huggingface.co/stabilityai/stable-audio-open-1.0](https://huggingface.co/stabilityai/stable-audio-open-1.0)
18. ElevenLabs — Create Sound Effect (API reference). [elevenlabs.io/docs/api-reference/text-to-sound-effects/convert](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)
19. Bain M. et al. *WhisperX: Time-Accurate Speech Transcription of Long-Form Audio*, Interspeech 2023. [github.com/m-bain/whisperX](https://github.com/m-bain/whisperX)
20. Steinmetz C., Reiss J. *pyloudnorm* (ITU-R BS.1770-4 / EBU R128), AES 2021. [github.com/csteinmetz1/pyloudnorm](https://github.com/csteinmetz1/pyloudnorm)
21. EU Artificial Intelligence Act — *Article 50: Transparency Obligations* (apply 2 Aug 2026). [artificialintelligenceact.eu/article/50](https://artificialintelligenceact.eu/article/50/) · EC FAQ: [digital-strategy.ec.europa.eu](https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act)
22. C2PA — *Content Credentials Technical Specification 2.x* (audio as first-class asset; AI-use assertions). [spec.c2pa.org](https://spec.c2pa.org/)
23. San Roman R. et al. *AudioSeal: Proactive Detection of Voice Cloning with Localized Watermarking*, ICML 2024 (MIT). [arxiv.org/abs/2401.17264](https://arxiv.org/abs/2401.17264) · [github.com/facebookresearch/audioseal](https://github.com/facebookresearch/audioseal)
24. Academy Software Foundation — *OpenTimelineIO* (modern EDL, audio tracks, adapters). [opentimelineio.readthedocs.io](https://opentimelineio.readthedocs.io/en/stable/)
25. Fonseca E. et al. *FSD50K: An Open Dataset of Human-Labeled Sound Events*, arXiv:2010.00475. [arxiv.org/abs/2010.00475](https://arxiv.org/abs/2010.00475) · [zenodo.org/records/4060432](https://zenodo.org/records/4060432)
26. Drossos K. et al. *Clotho: An Audio Captioning Dataset*, ICASSP 2020. [arxiv.org/abs/1910.09387](https://arxiv.org/abs/1910.09387) · [zenodo.org/records/4783391](https://zenodo.org/records/4783391)
27. *Sound Effects Dataset Unification With the Universal Category System (EnvSound-UCS)*, arXiv:2606.05571. [arxiv.org/abs/2606.05571](https://arxiv.org/abs/2606.05571)
28. *FoleySet: A Multi-Level Human-Annotated Foley Sound Dataset*, arXiv:2606.25980. [arxiv.org/abs/2606.25980](https://arxiv.org/abs/2606.25980)
29. Bassani E. *ranx: A Blazing-Fast Python Library for Ranking Evaluation and Comparison*, ECIR 2022. [github.com/AmenRa/ranx](https://github.com/AmenRa/ranx)
30. Chu Y. et al. *Qwen2-Audio Technical Report*, arXiv:2407.10759. [arxiv.org/abs/2407.10759](https://arxiv.org/abs/2407.10759)
31. Thor Whalen. *dol* — storage as a `Mapping`, local→cloud behind one interface. [github.com/i2mint/dol](https://github.com/i2mint/dol)
32. Thor Whalen. *arioso* — unified façade for AI music generation (config-driven adapters, `AFFORDANCES`). [github.com/thorwhalen/arioso](https://github.com/thorwhalen/arioso)
33. Thor Whalen. *accompy* — façade with protocol-based extensibility + `check_dependencies`/`verify_and_setup`. [github.com/thorwhalen/accompy](https://github.com/thorwhalen/accompy)
34. Thor Whalen. *py2mcp* — Python functions/stores → MCP tools (`mk_mcp_server`, `mk_http_app`, `mk_mcp_from_store`). [github.com/thorwhalen/py2mcp](https://github.com/thorwhalen/py2mcp)
35. OpenTelemetry — *Semantic Conventions for Generative AI* (LLM/agent spans, MCP tool calls, token/latency metrics). [opentelemetry.io/docs/specs/semconv/gen-ai](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
```
