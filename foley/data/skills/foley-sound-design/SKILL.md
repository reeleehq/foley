---
name: foley-sound-design
description: >-
  Use when sound-designing a NARRATION with the `foley` package — choosing sound effects for
  narrated/voiced text and weaving them under the voice. Triggers on: "add sound effects to this
  narration", "score this passage", "sound-design this audiobook/podcast/video script", "find a
  sound for this line", "weave SFX into the voiceover", "make a sound-design timeline", or any
  task that pairs narration text (or a transcript) with choosing + placing sounds. Covers the
  find→plan→weave loop, the one-call `foley.score()`, the MCP tool surface, and the taste
  heuristics (restraint, layering, ducking, licensing).
---

# Sound-designing a narration with `foley`

`foley` is a retrieval-first façade for sound effects: **find (or generate) the right sound for a
moment of narration and weave it in.** Your job with this skill is to turn narration text into a
**tasteful, license-clean** sound design — not to put a sound under every sentence.

## The one rule: restraint

Most sentences need **no** sound. A few well-placed, license-clean cues beat "sound soup." The
SELECT stage already enforces this (a salience/density budget, a fail-closed license gate, and a
verify ladder) — trust it, and prefer leaving quiet moments quiet.

## Fastest path — one call

```python
import foley

# Plan only (choose sounds, build an editable timeline):
result = foley.score("She pushed open the heavy oak door; rain hammered outside.")
print(result.rationale)  # what was chosen and why
result.timeline  # an editable SoundDesignTimeline

# Plan + render (weave under the actual narration audio):
result = foley.score(segments, audio="narration.wav")  # commercial use is the default
result.weave.audio  # mastered stereo mix (numpy)
result.weave.captions_vtt  # SDH captions (no speech text leaks)
result.weave.credits  # attribution (CREDITS.md + JSON)
```

`segments` is a string or a list of narration segments. `foley.score(...)` runs
`decompose → search → verify → decide → plan` per segment and, when `audio` is given, aligns +
weaves into a mastered mix. This is the stable contract downstream packages (`braidio`, `nw`) call.

## The full loop (when you want control)

| Step | Python | MCP tool |
|------|--------|----------|
| choose sounds for a passage | `foley.find(context)` | `foley_find` / `foley_score` |
| direct search / "more like this" | `foley.search(q)` / `foley.similar(id)` | `foley_search` / `foley_similar_to` |
| audition a candidate | — | `foley_preview(id)` (returns a store key) |
| steer with feedback | — | `foley_refine(picks, rejects, hint)` |
| accept / reject | — | `foley_pick(id, layer, onset)` / `foley_reject(id)` |
| fold picks → timeline | `foley.plan(cands)` | `foley_plan` |
| edit (non-destructive) | `foley.weave.timeline.*` | `foley_swap_clip` / `foley_set_gain` / `foley_nudge` / `foley_toggle` / `foley_set_master` |
| render | `foley.weave(narration, timeline)` | `foley_weave` |
| generate when nothing fits | `foley.generate(prompt, backend=...)` (see below) | `foley_generate` |
| what's the workflow / what's installed | — | `foley_guide` / `foley_capabilities` / `foley_status` |

**MCP is JSON-in / JSON-out**: tools take/return only JSON (ids, scores, license summaries,
timeline dicts, store keys) — audio is referenced by a byte-store key, never inlined. Call
`foley_guide` first if unsure.

## Generating a sound from a text description

Retrieval comes first: `foley.find` / `foley.score` search the library and generate only when nothing verified fits (pass `backend=` to choose what the fallback uses). When you already know nothing will fit (a specific foley moment for a film), generate directly:

```python
clip = foley.generate(
    "a single page of an old paper book being turned, crisp paper rustle, close-up",
    backend="fal_stable_audio_3",
    duration_s=1.5,
)
```

| backend | what it is | licence foley records | price (fal, 2026-10-25) |
|---|---|---|---|
| `fal_stable_audio_3` | Stable Audio 3 Small-SFX: the default pick, seeded, takes `negative_prompt` | Stability Community: commercial under US $1M revenue | $0.0206 per clip (to 120 s) |
| `fal_stable_audio_3_medium` | Stable Audio 3 Medium: better on hard prompts | Stability Community | $0.0376 per clip |
| `fal_elevenlabs` | ElevenLabs SFX v2 via fal: strong on human non-speech (sighs, breaths), `loop` | `fal-partner-unverified` (non-commercial until confirmed) | $0.002/s, ≤ 22 s |
| `fal_sonilo` | Sonilo v1.1 via fal | `fal-partner-unverified` | $0.0018/s |
| `fal_mirelo` | Mirelo SFX 2.0 via fal, to 600 s | `fal-partner-unverified` | $0.015/s (0.010 until 2026-12-13) |
| `fal_mmaudio` | MMAudio via fal | CC BY-NC 4.0 (attribution) | $0.001/s |
| `stable_audio` | Stable Audio Open 1.0, local (GPU, gated weights) | Stability Community | free |
| `elevenlabs` | ElevenLabs direct: **first in the generation order**; seconds come out of a paid plan's monthly allowance (10 credits/s, seen 2026-10-26), stereo 48 kHz PCM, `loop` | the account's plan (`$FOLEY_ELEVENLABS_PLAN`): paid = commercial, royalty-free, no attribution; free = non-commercial + attribution | $0.002/s once the allowance is used |

All `fal_*` backends need `foley[fal]` and `$FAL_KEY`; `elevenlabs` needs `foley[elevenlabs]`, `$ELEVENLABS_API_KEY` (or the fleet's `$ELEVEN_API_KEY`) and `$FOLEY_ELEVENLABS_PLAN`.

**The generation order.** With no `backend=`, `generate`, `find`'s fallback and `foley_generate` walk `elevenlabs` → `fal_stable_audio_3` → `fal_elevenlabs` → `stable_audio`: ElevenLabs direct first (same per-second price as the fal route, allowance first, and the plan's own licence instead of an unverified one). A backend with no key, no plan, offline, whose licence cannot serve the use (fal's ElevenLabs is non-commercial until its terms are confirmed), or whose provider refused the request with an HTTP error (nothing billed) is skipped, and the candidate's notes say why (`generation order: skipped ...`). Anything that may have been billed (a timeout, an undecodable response) is final, as is a QC or budget refusal: at most one backend bills per generation, and `foley.estimate` bounds it by the dearest backend the order would try. The paid entries run only after an explicit opt-in, `$FOLEY_GENERATE_PAID=1`: a key in the environment is not consent to spend (#58), so out of the box the order is the free local backend. `backend="elevenlabs"` uses that one with no fallback; `backend=("elevenlabs", "fal_sonilo")` is your own order; `$FOLEY_GENERATE_ORDER` replaces the default order and `$FOLEY_GENERATE_BACKEND` pins one. Every call is priced before it is made (`foley.estimate("generate", backend=..., duration_s=...)`), capped by the run's `Budget`, and kept in the generations cache: an identical request replays for free, `reuse_cached=False` pays for a fresh take. The licence, prompt, native request and the seed the model used are on `clip.sound.license`.

**Check what came back.** A clean clip can still be the wrong sound (fal Stable Audio 3 answered "a flintlock musket placed into a hand" and "a page turn" with unrelated sounds, and nothing caught it). `generate` scores each clip against its prompt with the library's CLAP embedder and puts the verdict in `sound.qc['prompt_match']` and the notes: `mismatch` is flagged (listen before using it), and where CLAP is not installed the verdict is `unchecked`, never a silent pass. Treat `unchecked` as "listen to it".

**Level what you export.** Models disagree by 10 dB or more. `generate(..., level="sfx_fg")` (or `foley.level.level_bytes(bytes, "sfx_fg")` on a clip you already have) scales a clip to its class target: the WEAVE layer gain under a -16 LUFS voice, so a one-shot is -25 LUFS and an ambience bed -37 LUFS. A clip under 0.4 s cannot be measured and is left alone. The default stores clips at their generated level because the WEAVE render applies the layer gains itself.

Prompt craft that worked: name the material and the action ("leather shoes on old wooden floorboards"), the count ("four clear footsteps", "a single page"), the space ("quiet indoor room, dry"), and the mic ("close-up"). Ask for the length the moment needs (1.5 s for a page turn, 8 s for a clock bed). Generate two or three backends for a sound and pick by ear. Never synthesize an effect from oscillators and noise when a model or a recording can give a real one.

## Taste heuristics

- **Layers.** `sfx_fg` = a spot effect on a trigger word; `ambience` = a bed under a
  sentence/scene (loops, kept low, **ducked** under the voice); `stinger` = a sharp accent on a
  boundary; `music` sparingly.
- **Onset.** Place a spot effect **on** its trigger word; a bed **spans** its sentence. The weave
  stage resolves symbolic anchors ("on 'door'") against the forced-aligned narration.
- **Salience.** Score a moment only if the sound adds meaning. Leave silence where silence works.
- **Loudness.** Pick a master profile for the delivery target: `podcast` (-16 LUFS), `streaming`
  (-14), `broadcast_ebu` (-23). The mix is loudness-normalized + true-peak-limited.

## Audience reactions: the crowd answers, it does not coincide

A cheer, laugh or applause synced to the *instant* of the on-screen event sounds like a track pasted on the cut. Place it with `foley.weave.reaction` (`reaction_cue`, `reaction_plan`, `hush_plan`):

- **Time it from when the event is legible, not when it starts.** An entrance is legible when the figure is mostly in frame; a reveal when the new face has settled. Then add the latency: gasp ~0.2 s, whistle ~0.45, cheer ~0.5, applause ~0.55, laugh ~0.6 (the gag has to land first). These are craft defaults, not measurements: published latency data is thin, so tune by ear with `latency=`.
- **Shape it: attack, peak, tail.** Claps ripple in (about 1 s) and never start at full density; a cheer swells fast and thins slowly; laughter swells shortest.
- **Repeats are smaller.** A second cheer is ~0.65x the first: the crowd "dies down" and bumps again, it does not climb.
- **Ask for the right kind.** Cheers (voices, surprise and delight) are not applause (claps); a clapping clip is not a cheer. Say which you want.
- **Silence needs a cause.** To quiet a crowd, place a "shh" after the applause has peaked (`hush_plan`) and fade the applause out under it over ~0.7 s, rather than cutting it.
- **Trim the clip's own lead-in.** A stock clip's audible onset is not its file start; trim silence first or the latency is wrong by the lead-in.

## Licensing is load-bearing (foley's output gets published)

- Only `license_ok` candidates are ever placed — the gate is **fail-closed** (unknown license →
  refused). Every verb and tool assumes **commercial publishing** by default; pass
  `commercial_ok=False` (or an explicit `IntendedUse`) only for a non-commercial project.
- Sounds you ingest yourself have **unknown** rights until you say otherwise:
  `foley.ingest(path, license="user-owned")` for your own recordings.
- Read each candidate's `license` row: full TASL (`creator_name`, `source_url`, `license_url`) and
  every flag (`commercial_ok`, `requires_attribution`, `redistribute_standalone_ok`,
  `ai_training_ok`, `is_ai_generated`, …). `foley.credits(sounds)` builds the attribution
  (a `CREDITS.md` + JSON) — always ship it.
- Generated audio (`foley.generate`) is disclosed (EU AI Act Art. 50) and watermarked when the
  provenance extra is installed; the mix carries a C2PA content credential.

## Offline / sensitive narration

For confidential scripts, run the offline posture: external sources **and** telemetry are
disabled, redaction is on, and generation stays on local backends. `foley_status` reports it;
`foley-mcp --offline` serves it. A local LLM (Ollama/llama.cpp/vLLM via `FOLEY_LLM_BASE_URL`) can
drive the SELECT rungs so nothing leaves the device.

## Degraded modes

`foley` works out of the box and degrades gracefully: without the CLAP/index extras it still runs
a keyword search; without an aligner it uses evenly-spaced word timings; without `ffmpeg` the
master runs in-process. Call `foley_capabilities()` to see what's installed and what's degraded,
and `foley.check_requirements()` for setup guidance.
