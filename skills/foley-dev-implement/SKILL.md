---
name: foley-dev-implement
description: Use when implementing (or planning to implement) any foley epic subtask — building the SOURCE / INDEX / SELECT / WEAVE stages or the cross-cutting layers of the foley SFX façade. Covers the build loop, the module layout, the canonical data models (SoundRecord, LicenseRecord, Candidate, SoundDesignTimeline), the non-negotiable invariants (license SSOT + fail-closed gate, cache_bytes_ok vs redistribute_standalone_ok, the eval PR gate, AI disclosure), the façade discipline (mirror arioso/accompy), and the branch→PR git flow. Triggers on foley implementation, foley subtask, foley adapter/index/agent/weave work, foley base.py / data models.
metadata:
  audience: developers
---

# Building a foley subtask

foley is a retrieval-first SFX façade (SOURCE → INDEX → SELECT → WEAVE + cross-cutting
layers). The whole plan is **[Epic #13](https://github.com/thorwhalen/foley/issues/13)**,
subtasks **#1–#12**. Read this before implementing any of them.

## First: orient (don't invent)

1. Read **`misc/docs/research/10-facade-architecture.md`** — the authoritative synthesis
   (component diagram, data models as code, façade API, protocols, module tree,
   dependency graph). It reconciles all 12 research reports; treat it as the spec.
2. Skim **`misc/docs/design.md`** (the readable map) and the specific research report(s)
   backing your subtask (each subtask issue lists them).
3. Look at how [`arioso`](https://github.com/thorwhalen/arioso) and
   [`accompy`](https://github.com/thorwhalen/accompy) do the same shape — foley mirrors
   their façade discipline.

## The build loop

1. **Pick a subtask** from Epic #13. Respect the dependency order — the keystone is
   **#1 Foundation → #2 Index → #3 Ingestion → #4 Bootstrap** (gets `ingest()` → `search()`
   working). Then a thin slice through Select (#7) → Weave (#8).
2. **Branch:** `git checkout -b <topic>` off `main`. Never commit foley code directly to
   `main` — open a **PR** that references the subtask (`Closes #N`).
3. **Implement against the layout & protocols** below — extend the SSOT data models, don't
   fork them. New optional dependency? Put it in an `optional-dependencies` extra
   (`foley[<capability>]`) and **lazy-import** it; the core stays zero-dep.
4. **Test** (economist / testing-trophy: cheap, stable API-level checks first — see
   `misc/docs/research/08-evaluation-quality.md`). Pure functions get unit tests; the
   retrieval path gets Tier-1 metrics.
5. **Eval gate** (once the harness from #10 exists): a change to the index/embedder/
   prompt must not drop **`nDCG@10` by > 0.02** on the frozen golden set.
6. **PR** into `main`; keep the subtask's task-list checkboxes updated.

## Module layout (from report 10 — build into this tree)

```
foley/
    __init__.py        # façade: find(), search(), generate(), ingest(), weave()
    base.py            # SoundRecord, LicenseRecord, Candidate, SoundEvent, Verdict,
                       #   IntendedUse, affordance registries — the SSOT types
    registry.py        # adapter auto-discovery + lazy loading
    audio.py           # I/O + DSP primitives (soundfile/soxr/librosa; loudness via mixing.loudness)
    sources/           # source adapters (config.py + adapter.py each) — see foley-dev-add-source
    index/             # embedders, taggers, captioners, library (dol + LanceDB), search, taxonomy
    agent/             # decompose, verify, policy(decide), tools, mcp
    weave/             # align, anchor, mix, master, timeline, render
    eval/              # qc (Tier-0), retrieval metrics (Tier-1), fit (Tier-2)
    provenance/        # LicenseRecord wiring, credits, watermark/disclosure
    obs/               # OpenTelemetry spans + run-manifest artifact
```

Optional-extras: `foley[freesound]`, `foley[stable-audio]`, `foley[elevenlabs]`,
`foley[clap]`, `foley[tag]`, `foley[caption]`, `foley[index]`, `foley[weave]`,
`foley[agent]`, `foley[all]`. `ffmpeg`/`rubberband` are **system** deps surfaced via a
`check_requirements`/`verify_and_setup` helper (accompy-style), never inherited by `pip`.

## Canonical data models (SSOT — live in `base.py`, never fork)

- **`SoundRecord`** — the metadata SSOT for one sound (report 04 schema + report 09
  storage fields + a nested `LicenseRecord` + a QC block + `named_cue` continuity). The
  audio bytes live in the `dol` blob store; the record holds a content-hash `uri`, never
  inline bytes.
- **`LicenseRecord`** — per-sound rights/provenance (report 07). Carries the derived
  flags used everywhere: `commercial_ok`, `embed_in_derivative_ok`,
  `redistribute_standalone_ok`, `modification_ok`, `ai_training_ok`, **`cache_bytes_ok`**,
  plus attribution/watermark/generation fields.
- **`Candidate` / `SoundEvent` / `Verdict`** — the SELECT agent's working types (report 05).
- **`SoundDesignTimeline` / `TimelineItem`** — the WEAVE render model (report 06); it is a
  **strict superset** of the SELECT plan. The agent emits the sparse plan; WEAVE resolves
  anchors and fills processing defaults. It is JSON-serializable, diffable, and
  re-renderable — the "editable sound-design timeline" (foley's snapshots/stories analog).

## Non-negotiable invariants

1. **`LicenseRecord` is the SSOT for two things:** the candidate license-filter *and*
   each `SoundRecord`'s storage mode. Wire both from it.
2. **`redistribute_standalone_ok` (copyright) ≠ `cache_bytes_ok` (TOS/operational).** e.g.
   Freesound CC0 is legally redistributable yet its API TOS forbids caching → store
   **by-reference**. Get this wrong and you either break the law or break the TOS.
3. **The license gate is fail-closed.** `keep(record, IntendedUse)` runs as a hard gate
   *before* verification/ranking in the agent's `decide()`; unknown rights → reject.
4. **AI-generated audio is disclosed & watermarked.** Watermark generations (AudioSeal),
   optionally write C2PA, and honor the **EU AI Act Art. 50** disclosure deadline
   (**2 Aug 2026**). Tracked in #9.
5. **The eval gate guards regressions** (once #10 lands): no silent `nDCG@10` drop.

## Reference

Depth for any subtask is in the matching research report in `misc/docs/research/`
(`01` sources · `02` generation · `03` recognition · `04` index · `05` agent · `06`
weave · `07` licensing · `08` eval · `09` audio/storage · `11` corpora · `12`
meta-scan · **`10` = authoritative architecture**). For adding a source, use the
**`foley-dev-add-source`** skill.
