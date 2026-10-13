# foley — Design

**Status: built (v1 shipped; see the [roadmap](roadmap.md) for what is still open).** This is the readable map of the architecture. The
**authoritative, fully-detailed synthesis** (all 12 research reports reconciled into
component diagram, data models, façade API, adapter/protocol contracts, module tree,
dependency graph, and the epic/subtask plan) lives in
[`research/10-facade-architecture.md`](research/10-facade-architecture.md) — read that
for depth. Where the code differs from this map, the code and the roadmap win.

> **Key reconciliation from report 10:** `redistribute_standalone_ok` (a copyright
> flag) and `cache_bytes_ok` (a TOS/operational flag) are **distinct** — e.g. Freesound
> CC0 is legally redistributable but its API TOS forbids caching, so it is stored
> by-reference. `LicenseRecord` is the SSOT for *both* the candidate license-filter
> *and* each `SoundRecord`'s storage mode.

## Mission

foley finds (or generates) the **right sound effect for a moment of narration** and
weaves it in. It is a **retrieval-first façade**: a single, simple surface over many
sound *sources*, a searchable *index* of every sound, an *agent* that picks the right
one for a narrative context, and a *compositor* that places it under the voice.

It is the SFX sibling of [`arioso`](https://github.com/thorwhalen/arioso) (unified
façade over music-generation backends) — same discipline (one entry function,
config-driven plugin adapters, a unified vocabulary translated per-backend, zero
required core deps with lazy optional-deps, `dol` storage), but centered on **search**
rather than generation, with generation as one of several sources.

## The four stages

```
        SOURCE                 INDEX                  SELECT                 WEAVE
  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │ bring-your-own   │  │ probe → segment  │  │ decompose context│  │ align to voice   │
  │ Freesound (CC0)  │→ │ → tag → caption  │→ │ → search (hybrid)│→ │ → duck → place   │
  │ generate (SFX AI)│  │ → embed (CLAP)   │  │ → verify → decide│  │ → master (LUFS)  │
  └──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘
     sources/               index/                 agent/                weave/         
```

### 1. SOURCE — where sounds come from  *(report 01, 02)*

One adapter contract, two adapter kinds:

- **Retrieve adapters** pull existing sounds from services. **Freesound APIv2 is the
  anchor** — the only source that is both self-serve-programmable *and* legally
  redistributable (via its per-sound **CC0** subset), with token search + OAuth2
  download and even built-in CLAP semantic search. Professional APIs (Epidemic,
  Storyblocks, Pond5, Pro Sound Effects) are partner/enterprise-gated → ship as
  **stub adapters** wired when agreements exist. No-API web libraries (Zapsplat,
  Mixkit, Pixabay-audio) are **link-out pointers**, not fetch-and-store backends.
- **Generate adapters** synthesize sounds (the arioso analog). Default **local =
  Stable Audio Open 1.0** (commercially usable under $1M revenue; 47s stereo;
  `diffusers`); default **hosted = ElevenLabs Sound Effects** (`POST
  /v1/sound-generation`, 0.5–30s, ~$0.12/min, clean commercial rights). ⚠️ Most open
  SFX weights are **CC-BY-NC** — so every generate adapter carries a **`commercial_ok`
  guardrail**.

Because licensing is **per-sound and heterogeneous**, every sound carries a
`LicenseRecord` with `commercial_ok` / `redistribute_ok` / `ai_training_ok` flags.

### 2. INDEX — making every sound findable  *(report 03, 04)*

A bring-your-own library becomes searchable via an ingestion pipeline of
**permissively-licensed, mostly-CPU** models:

```
probe → (optional) segment/separate → supervised tag → zero-shot tag → caption → embed → SoundRecord
        PANNs SED / FUSS               PANNs CNN14        CLAP vs UCS     (pluggable) CLAP 512-d
```

- **Embedding: CLAP** (`laion/larger_clap_general`, 512-d, Apache-2.0) — one joint
  text↔audio space gives *both* text→audio retrieval and audio↔audio similarity.
  Behind an `Embedder` protocol; every record stamps `embedding_model`/`dim` so
  MS-CLAP / PANNs stay drop-in.
- **Store: LanceDB** as the local-first index that runs byte-identical on local disk
  or `s3://` — the exact `dol` "swap local→cloud with no code change" property. The
  `SoundLibrary` façade composes four injected stores: `sounds` (audio blobs, `dol`
  Files→S3), `meta` (the canonical `SoundRecord` SSOT), and `vindex`+`kindex` (CLAP
  vectors + BM25 over tags/captions, both from one LanceDB table). Ultra-minimal
  fallback: `sqlite-vec` + FTS5 in one file. FAISS rejected as default (ANN-only).
- **Search is hybrid**: BM25(tags+caption) fused with CLAP vectors via **Reciprocal
  Rank Fusion** (rank-fuse, k=60 — don't average raw scores). Pure-vector misses
  literal tokens (UCS CatIDs, library/product names, onomatopoeia).
- **Taxonomy**: **UCS** (82 cat / ~753 subcat, public-domain, filename convention) as
  the human browse tree; **AudioSet ontology** (632 classes) as the auto ML-label
  layer. UCS is the normalization target for Freesound/AudioSet/vendor tags.

The canonical `SoundRecord` schema (id, source, uri blob-ref, license, attribution,
provenance, caption, tags, ucs_category, audioset_labels, embedding refs, duration,
sample_rate, channels, loudness_lufs, format) is specified in report 04.

### 3. SELECT — the right sound for a context  *(report 05)*

Retrieval is a near-commodity (CLAP dual-encoder), but **top-1 is right only ~30% of
the time while R@10 ≈ 0.7** — so retrieval yields a *shortlist*, and the value is in
decomposition + verification:

- **`decompose_context`** — an LLM turns a story paragraph into a *sparse,
  salience-ranked, correctly-diegetic* list of sound events (query · layer · onset ·
  loop · diegetic-flag), with a per-window budget so scenes don't overcrowd.
- **`search_sounds`** — hybrid CLAP+BM25 over the `dol`-backed index → shortlist.
- **`verify_match`** — a 3-tier ladder, cheapest first: CLAP score → audio-LM
  listen-check ("does this clip contain {event}?", Qwen2-Audio/AQAScore) → LLM-judge.
- **`decide`** — the *one* branch point: confident verified clip → use it;
  diegetic-but-no-match → **generate** (fall back to a generate adapter), then
  re-verify; non-diegetic/mood → music route. Accepted generations are cached back
  into the library so the generate-rate falls over time.

Published as an **MCP server via `py2mcp`** so the same tools drive the agent, the CLI,
and external hosts.

### 4. WEAVE — placing sound under the voice  *(report 06; built)*

Alignment (forced-align narration → word timestamps), ducking/side-chain, stereo/
distance placement, crossfades, and LUFS/EBU-R128 mastering. Design target: an
**editable, re-renderable sound-design timeline** (conceptually like cosmograph
"snapshots/stories" applied to a narration's SFX layer) — not a one-shot bake. Run
**Prompt 6** in the research library to seed this. *(Done: report 06. Shipped in `foley/weave/`. Forced alignment uses WhisperX when installed. Otherwise a fake aligner spaces words evenly, and the result says so.)*

## Public façade API (implemented; see `foley/__init__.py` for the current signatures)

```python
import foley

# The headline: right sounds for a narrative context (decompose → search → verify → decide)
candidates = foley.find("She pushed open the heavy oak door; rain hammered outside.")

# Direct hybrid search of the library (text query or a reference clip)
hits = foley.search("distant thunder rumble", k=10, commercial_ok=True)

# Generate when nothing fits (arioso-style; backend + unified params)
clip = foley.generate("a single wooden door creak", backend="stable_audio", duration=3)

# Grow the library: ingest auto-tags, captions, and embeds
foley.ingest("~/my_sounds/")  # a folder (dol store)
foley.add_from("freesound", query="ocean waves", license="cc0")

# Compose: plan the picks into an editable timeline, then render it under the narration
timeline = foley.plan(candidates)
result = foley.weave(
    "narration.wav", timeline, transcript="..."
)  # result.notes says how placements were timed

# The library itself is a dol Mapping of SoundRecords
lib = foley.library
```

## Module layout (arioso-style)

```
foley/
    __init__.py        # façade: find(), search(), generate(), ingest(), weave()
    base.py            # Sound, Candidate, SoundRecord, LicenseRecord, AFFORDANCES
    sources/           # source adapters (config.py + adapter.py each)
        registry.py    #   adapter auto-discovery + lazy loading
        freesound/     #   retrieve (CC0-filtered) — the anchor
        stable_audio/  #   generate (local, default)
        elevenlabs/    #   generate (hosted, default)
        ...            #   bulk corpora (FSD50K, Clotho, BBC REMArc, Sonniss, FoleySet); no pro-API stubs yet
    index/
        ingest.py      # probe → tag → caption → embed → SoundRecord
        taggers.py     # PANNs / CLAP-zero-shot / captioner (protocol-based)
        embedders.py   # CLAP Embedder protocol
        library.py     # SoundLibrary (dol stores + LanceDB vindex/kindex)
        search.py      # hybrid search + RRF
        taxonomy/      # UCS + AudioSet ontology
    agent/
        decompose.py   # context → sound-event list (LLM)
        verify.py      # verification ladder
        policy.py      # generate-vs-retrieve decide()
        tools.py       # tool functions
        mcp.py         # py2mcp server
    weave/             # alignment, anchoring, ducking, mixing, mastering, render
```

**Optional-extras plan:** `foley[freesound]`, `foley[stable-audio]`, `foley[elevenlabs]`,
`foley[clap]`, `foley[tag]`, `foley[caption]`, `foley[index]` (lancedb), `foley[agent]`,
`foley[all]`. The zero-dep core holds only the façade, base types, registry, and the
`dol`/`config2py` plumbing (mirrors arioso).

## Adapter contract (source plugins)

Every source (retrieve or generate) is a subfolder with a config + optional adapter,
exactly like arioso's `PLATFORM_CONFIG`. A `SOURCE_CONFIG` declares kind
(`retrieve`|`generate`), auth, the param map from foley's unified vocabulary to native
names, supported affordances, output format, and a **license policy** (default flags,
whether commercial/redistribute/ai-training is permitted). Adapters expose a small
protocol: `search` / `get` / `download` for retrieve; `generate` for generate.

## Cross-cutting

- **Licensing & provenance** (report 01/07) — first-class per-sound; the agent filters
  candidates by license compatibility with the user's intended use. *(Deepen: Prompt 7.)*
- **Evaluation** — layered: audio QC (clipping/silence/LUFS) → retrieval metrics
  (R@k, mAP) → LLM/audio-LM fit-judging. *(Deepen: Prompt 8.)*
- **Foundation** — canonical working audio format + `dol` byte-store/metadata-store
  split. *(Deepen: Prompt 9.)*

## Open questions

- Store-by-reference vs store-by-value for library sounds (Freesound TOS forbids some
  caching; per-source policy needed).
- How much of `weave` (timeline model, mastering) to build vs delegate to ffmpeg.
- Real-time/interactive authoring vs batch rendering budgets (Prompt 12).

## See also

The five seeded reports in [`research/`](research/) and the
[deep-research prompt library](research/deep-research-prompts.md) (Prompts 6–12 are the
next fan-out: weave, licensing, evaluation, foundation, architecture-synthesis,
bootstrap corpora, and the "what are we forgetting" scan).
