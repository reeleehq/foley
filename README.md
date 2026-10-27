# foley

Find (or generate) the **right sound effect for a moment of narration** — and weave it in.

foley is a **retrieval-first façade for sound effects**: one simple surface over many
sound *sources* (your own library, service APIs, and generative-AI models), a searchable
*index* of every sound (by keyword **and** meaning), an *agent* that picks the right
sound for a narrative context, and a *compositor* that places it under the voice.

It's the SFX sibling of [`arioso`](https://github.com/thorwhalen/arioso) (a unified
façade over AI music-generation backends): same discipline — one entry function,
config-driven plugin adapters, a unified vocabulary translated per-backend, zero
required core deps with lazy optional-deps — but centered on **search** rather than
generation, with generation as just one of several sources.

> **Status: v1.** All four stages — source, index, select, weave — plus the MCP server
> and the licensing/provenance, evaluation, and observability layers are implemented
> (Epic #13 complete). The API below is live; see the [roadmap](misc/docs/roadmap.md)
> for what's next. Follow along in [`misc/docs/`](misc/docs/).

## The idea

```python
import foley

# The headline — right sounds for a narrative context:
# decompose the passage into salient sound events → search → verify → decide
candidates = foley.find("She pushed open the heavy oak door; rain hammered outside.")

# Direct hybrid search of your library (text query or a reference clip)
hits = foley.search("distant thunder rumble", k=10)  # commercial use is the default

# Generate a sound when nothing fits (arioso-style; pluggable backends)
# needs foley[stable-audio] and the gated stabilityai/stable-audio-open-1.0 weights
# (accept its license on Hugging Face, set HF_TOKEN); backend="elevenlabs" needs
# ELEVENLABS_API_KEY and is paid
clip = foley.generate(
    "a single wooden door creak", backend="stable_audio_3", duration_s=3
)  # local, CPU; setup: foley.check_requirements(verbose=True)

# No GPU? The fal-hosted backends (foley[fal] + FAL_KEY; paid, priced before the call):
# Stable Audio 3 Small-SFX at $0.0206 a clip, commercial use under $1M revenue
clip = foley.generate(
    "a single wooden door creak", backend="fal_stable_audio_3", duration_s=3
)

# Or let foley pick: with paid generation opted in (FOLEY_GENERATE_PAID=1) an unnamed
# backend walks the generation order, ElevenLabs direct first (ELEVENLABS_API_KEY or
# ELEVEN_API_KEY, plus FOLEY_ELEVENLABS_PLAN), then fal, then the local model; the
# notes say which backends were skipped and why
clip = foley.generate("a single wooden door creak", duration_s=3, level="sfx_fg")
clip.sound.qc["prompt_match"]  # CLAP prompt-vs-audio verdict, or 'unchecked'

# Sound timed to picture (video-to-audio): video= walks the V2A order (Mirelo SFX 2.0,
# then Sonilo, both on fal; FOLEY_V2A_ORDER replaces it). Their fal-route output terms
# are unverified, so name the backend (its licence is then gated by keep()) — #170
clip = foley.generate("", backend="fal_mirelo_v2a", video="shot.mp4", duration_s=6)
# Non-commercial V2A, named only: fal_mmaudio_v2a (CC BY-NC), fal_thinksound (research
# only), fal_hunyuan_foley (no grant in the EU, UK or KR: say where it is used)
use = foley.IntendedUse(commercial=False, territory="US")  # every place it is shown
clip = foley.generate(
    "rain on a tin roof",
    backend="fal_hunyuan_foley",
    video="shot.mp4",
    intended_use=use,
)

# Grow the library — ingest auto-tags and embeds every file (captioning is pluggable)
foley.ingest("~/my_sounds/", license="user-owned")  # omit it and rights stay unknown
foley.add_from(
    "freesound", query="ocean waves", license="cc0"
)  # needs FREESOUND_API_KEY

# Compose: place the sounds under the narration (find → plan → weave)
timeline = foley.plan(candidates)  # the editable sound-design plan
result = foley.weave("narration.wav", timeline)  # mastered mix + SDH captions + credits
result.notes  # how placements were timed, e.g. estimates when foley[align] is absent
```

## How it works — four stages

| Stage | What it does | Built on |
|-------|--------------|----------|
| **Source** | your own files · Freesound (CC0, or CC-BY when you can credit) · keyless: Openverse, Wikimedia Commons, Internet Archive (opt-in; licences unverified) · generate (Stable Audio 3 local on CPU; Stable Audio Open local; ElevenLabs; fal: Stable Audio 3, Mirelo, Sonilo, ElevenLabs, MMAudio) | config-driven adapters, per-sound license tracking |
| **Index** | probe → tag → caption → embed every sound; hybrid keyword+semantic search | PANNs · CLAP · LanceDB (local→cloud via `dol`); captions come from metadata until a learned captioner is plugged in |
| **Select** | decompose a narrative context → search → verify → generate-or-retrieve | CLAP retrieval + LLM decomposition + a verification ladder |
| **Weave** | align to the voice, duck, place, master → mastered mix + editable timeline + captions + credits | word timing (WhisperX transcription with `foley[align]`; otherwise evenly spaced script words; `notes` says which) · LUFS/EBU-R128 |

The selection tools publish as an **MCP server** (via `py2mcp`) so the same capabilities
drive the agent, a CLI, and external hosts.

## Music libraries

`foley.sources.music_library` acquires the free tracks a production credits (Kevin MacLeod's incompetech is built in; the paid Artlist and Epidemic Sound give wishlist rows, never downloads). Each title is fetched politely through foley's transport (paced per host, `429` / `Retry-After` honoured), from the library's server and then the Internet Archive's raw copy, checked to be audio, and recorded with a `LicenseRecord` read from the library's licence URL. Needs `foley[music-library]` and `ffprobe`.

```python
from foley.sources.music_library import acquire, attribution_text, kept_digests, titles_by_library, tracks_table

titles = titles_by_library(video_description)["incompetech"]  # or a list / {title: {metadata}}
rows = acquire("incompetech", titles, out="audio/macleod")      # one row per title: acquired / failed
table = tracks_table(rows)                                      # CSV; row.row() is the JSON-safe dict
print(attribution_text(rows))                                   # the blocks to paste under the video
rows = acquire("incompetech", titles, out="audio/macleod", kept=kept_digests(table))  # a rerun fetches only what is missing
```

## For AI agents

foley is **AI-first**: most callers are agents (directly, and via downstream packages like
`braidio` and `nw`). The headline is one call — hand it narration text and it chooses tasteful,
license-clean sounds and (given the audio) weaves them in:

```python
import foley

# Plan only — choose sounds, get an editable timeline + a rationale:
result = foley.score("She pushed open the heavy oak door; rain hammered outside.")
print(result.rationale)

# Plan + render — weave under the actual narration audio:
result = foley.score(segments, audio="narration.wav", commercial_ok=True)
result.weave.audio  # mastered mix   result.weave.captions_vtt   # SDH captions
result.weave.credits  # attribution    result.timeline             # still editable
```

`foley.score(...)` is the stable contract `braidio`/`nw` call. The same surface is available as
**MCP tools** (`foley_score`, `foley_guide`, `foley_search`, `foley_preview`, `foley_weave`, …) —
serve them over stdio (`foley-mcp`) or authenticated HTTP (`foley-mcp --http --token …`) — and as
**CLI commands** generated from the same verb table (`foley.agent.verbs.VERBS`), JSON in and out:

```
foley score "Rain on the roof, then thunder." --territory US
foley generate "a glass shatters" --no-commercial-ok
foley find --help
```

Ship the **agent kit** into your agent host (a `foley-sound-design` skill, a `/foley-score`
slash command, and a `sound-designer` subagent):

```
foley agent-install            # → ./.claude/{skills,commands,agents}/…
```

The **one rule** is restraint — most sentences need no sound. The design is grounded in the
research reports below; taste heuristics (layering, ducking, onset, licensing) live in the skill.

## Design & research

foley's design is grounded in five research reports (unified, cited):

- [Design](misc/docs/design.md) · [Roadmap](misc/docs/roadmap.md)
- [Research reports](misc/docs/research/) — sound sources, SFX generation, recognition/
  tagging, embeddings/indexing, and the context-retrieval agent
- [Deep-research prompt library](misc/docs/research/deep-research-prompts.md) — 12
  ready-to-run prompts covering every dimension of the project

## Install

```bash
pip install foley                         # core — dol-only, light; `import foley` stays minimal
pip install "foley[audio,clap,index]"     # the usual retrieval stack (CLAP + hybrid index)
foley demo                                # no-download smoke test on the bundled fixture
foley agent-install                       # drop the agent kit into ./.claude (skill + command + subagent)
```

foley is **zero-dep at its core** and grows by capability via optional extras — each imported
lazily, so a bare install stays light. What each adds:

| Extra | Adds |
|-------|------|
| `audio` | numpy/soundfile DSP + LUFS mastering |
| `clap` | the CLAP text↔audio retrieval engine |
| `index` / `index-sqlite` | the hybrid vector+keyword index (LanceDB / sqlite-vec) |
| `freesound` · `stable-audio` · `elevenlabs` · `fal` | live retrieve / generate sources (`fal`: the fal-hosted generators through `falaw`) |
| `agent` · `local-llm` | the SELECT LLM rungs (Claude / a local OpenAI-compatible endpoint) |
| `align` · `weave` · `provenance` · `c2pa` | word timing (WhisperX), OTIO/rubberband, watermarking, signed C2PA |
| `mcp` · `obs` | the MCP server · OpenTelemetry export |

**Nothing paid runs unless you ask for it.** Having `ANTHROPIC_API_KEY` set does not switch the SELECT rungs to Claude: pass `llm="anthropic"` to `find()` / `score()` or set `FOLEY_LLM=anthropic` (`llm="local"` uses `FOLEY_LLM_BASE_URL`). By default they run the free deterministic fakes, or your local endpoint if one is configured. `with foley.offline():` (or `FOLEY_OFFLINE=1`) blocks every external source and LLM call foley makes, on every surface, raising `foley.runtime.EgressBlocked` (model weights are never downloaded offline: a model not already cached raises `foley.runtime.ModelNotCached`, naming the command to fetch it while online).

**Every paid call is priced and capped.** `foley.estimate("generate", backend="elevenlabs", duration_s=3)` says what a call costs before it is made (`None` means unknown, never free). A `find` / `score` / `generate` run stops before the first paid call that would take it past its `Budget(max_usd=...)` (default $1, or $3 when you chose Claude with `llm="anthropic"` / `FOLEY_LLM=anthropic`, since a default `find` with Claude is bounded at about $2.52), and a call of unknown cost needs `Budget(approve_unknown_cost=True)`. Every paid response is kept in `~/.local/share/foley/generations/` before QC, so an identical request is served from there instead of paying twice. What a backend could not honour is never silent: a parameter that changes the result (`seed` on ElevenLabs) raises, and every other drop or clamp is listed in the returned candidate's `notes`.

**A paid clip is repaired before it is quarantined, and never lost.** A generation Tier-0 QC would refuse for a clipped run just over the gate (a 1 s bite at 0.0125 % clipped, with the edge click and the +0.5 dBTP peak such a clip carries) gets the report's own fixes — a 20 ms fade and a true-peak attenuation (`foley.repair`), which clear all three — is checked again and stored; the repair is on the candidate's `notes` and in its licence's `transformations`. Silence, NaN, a too-short clip and heavy clipping (a flat top over about a millisecond, or over 0.1 % of the clip) are still quarantined, with the reason noted. `repair=False` keeps the quarantine; a callable with `foley.repair.repair`'s signature replaces the policy (`functools.partial(foley.repair.repair, min_status=foley.QCStatus.pass_)` also declicks clips QC admits with a warning, which are otherwise stored as is). `store=False` previews a generation without indexing it: the candidate's `audio_bytes` carries the clip, and enrichment that needs an absent extra (`foley[clap]`) is skipped with a note instead of failing after the paid call. And when a generation is refused anyway, the `GenerationError`'s `cache_key` names the paid bytes: `foley.generations.get(err.cache_key)` returns them as received, `foley.repair.repair_bytes(raw)` applies the same fixes to them, and `foley.generations.find(prompt, backend=..., duration_s=...)` lists what was kept, newest first (entries kept by earlier versions carry no timestamp and come last).

`foley.check_requirements()` (and the `foley_capabilities` MCP tool) report what's installed and
what's degraded. Full docs: **[thorwhalen.github.io/foley](https://thorwhalen.github.io/foley)**.

## Changelog

Per-release changes are in [CHANGELOG.md](CHANGELOG.md).

## License

MIT
