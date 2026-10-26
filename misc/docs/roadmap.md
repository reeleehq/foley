# foley — Roadmap

A phased build order derived from [`design.md`](design.md) and the [`research/`](research/)
reports. The strategy is **retrieval-first**: get a searchable library working before
sources multiply or generation/weaving deepen — validate "find the right sound" end to
end early.

**Status (2026-10-13):** v1 shipped. Phases 1–5 are built, and most of phase 6 is too. What remains is marked open below, with the issue that tracks it. A box is checked only where the code exists on `main`. Where the shipped piece differs from the plan, the line says how.

## Phase 0: scaffold and research ✅

- [x] Name (`foley`), repo, wads setup, CI, `misc/docs/`
- [x] Five research reports (source APIs, generation, recognition, indexing, retrieval-agent)
- [x] Deep-research prompt library (Prompts 1–12)

## Phase 1 — Library & Index (the retrieval foundation)

*The keystone. Everything else plugs into this.*

- [x] `SoundRecord` + `LicenseRecord` schemas (`base.py`) — the canonical SSOT record
- [x] `SoundLibrary` façade over injected `dol` stores (blobs + metadata) — local-first
- [x] `Embedder` protocol + CLAP default (`laion/larger_clap_general`)
- [x] LanceDB `vindex`+`kindex`; hybrid search + RRF (`search.py`); sqlite-vec fallback
- [x] Ingestion pipeline (`ingest.py`): probe → PANNs tag → CLAP zero-shot → caption → embed. **No learned captioner ships:** the `Captioner` protocol is in place, but `foley.ingest()` runs no caption stage by default. The bootstrap, pull and generate paths caption from metadata (`MetadataCaptioner`). EnCLAP / Qwen2-Audio captioning is still open.
- [x] UCS + AudioSet taxonomy tables (`taxonomy/`)
- [x] `foley.ingest(folder)` and `foley.search(query)` working end to end
- [x] Seed corpus: FSD50K (CC0/CC-BY) as a starter library

**Done when:** `foley.ingest("~/sounds")` then `foley.search("thunder")` returns
ranked, license-tagged hits by keyword + semantics.

## Phase 2 — Sources (retrieve + generate adapters)

- [x] Source adapter contract (`SOURCE_CONFIG`, registry auto-discovery) — arioso pattern
- [x] **Freesound** retrieve adapter (CC0-filtered) — `foley.add_from("freesound", …)`
- [x] **Stable Audio Open** generate adapter (local default) with `commercial_ok` guardrail
- [x] **ElevenLabs Sound Effects** generate adapter (hosted default)
- [x] `foley.generate(prompt, backend=…)` with unified param vocabulary
- [ ] Stub adapters for partner-gated pro APIs (Epidemic/Storyblocks/…). **Not started.**

**Done when:** foley can pull CC0 sounds from Freesound and generate SFX locally/hosted,
all landing in the library with correct per-sound license flags.

## Phase 3 — The search agent (`find(context)`)

*The headline capability.*

- [x] `decompose_context` — LLM: story paragraph → salience-ranked diegetic sound-event list
- [x] `search_sounds` tool over the hybrid index
- [x] `verify_match` — CLAP-score → audio-LM listen-check → LLM-judge ladder (the Qwen2-Audio listen rung needs `foley[fit]`)
- [x] `decide` — generate-vs-retrieve policy; cache accepted generations back
- [x] `foley.find(context)` returns a verified shortlist of candidates

**Done when:** given a paragraph, foley returns the right sounds for its salient moments,
generating when the library has no match.

## Phase 4 — MCP server & preview UX

- [x] Expose the tool set as an MCP server via `py2mcp`
- [x] Preview / audition surface (shortlists, "more like this", human-in-the-loop pick)
- [x] CLI entry (`foley …`, `foley-mcp`)
- [x] `check_requirements` / setup-guidance (accompy-style) for optional deps & models

## Phase 5 — Weave (compose onto narration)

*Researched in report 06.*

- [ ] Forced-alignment of narration → word timestamps. **Partly done:** WhisperX is used when installed (`foley[align]`). It aligns its own transcription of the narration, not the given script. Without it, the default `FakeAligner` spaces the script's words evenly. In every case, `WeaveResult.notes` and the run manifest (`aligner`) say which was used. A script-aware forced aligner: #43.
- [x] Ducking/side-chain + stereo/distance placement + crossfades
- [x] LUFS/EBU-R128 mastering to platform targets
- [x] Editable, re-renderable **sound-design timeline** data model
- [x] `foley.weave(narration, timeline)` → mixed output (and `foley.score(text, audio=…)` end to end)

## Phase 6 — Evaluation, breadth & polish

- [x] Eval harness: audio QC → retrieval metrics (R@k, mAP) → LLM/audio-LM fit-judging (**Prompt 8**)
- [x] Golden eval set: (narrative-context → expected-sound) pairs (**Prompt 11**)
- [ ] More source & generation adapters (FSD50K, Clotho, BBC REMArc, Sonniss and FoleySet corpora ship); MS-CLAP/BEATs embedder upgrades are **not started**.
- [x] Provenance/attribution export; disclosure/watermarking (credits, AudioSeal behind an extra, a C2PA sidecar) (**Prompt 7, 12**)

## Parallel research track (Prompts 6–12)

The prompt library's remaining prompts feed the phases above; run them ahead of the
phase that needs them:

| Prompt | Feeds |
|--------|-------|
| 6 — weaving/mixing/mastering | Phase 5 |
| 7 — licensing/provenance | Cross-cutting, Phase 2/6 |
| 8 — evaluation | Phase 6 |
| 9 — audio I/O & storage foundation | Phase 1 |
| 10 — façade/architecture synthesis | Phase 1 (refines this design) |
| 11 — bootstrap corpora & benchmarks | Phase 1, 6 |
| 12 — meta-scan (what we're forgetting) | Ongoing |
