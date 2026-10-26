# 16 — foley's facade interface, revised (October 2026): the common part, the escape hatches, and what to build next

*Synthesis of reports 13 (generation targets) [1], 14 (search, library and corpus targets) [2] and 15 (a facade audit of foley v0.0.26) [3], written on 2026-10-03. It applies a fleet-wide facade-design checklist distilled from ten provider facades (arioso, ocracy, scribed, voxy, falaw, illustration, foley, hearing, ef, aikb). It amends report 10 [4] and does not replace it: report 10's four-stage architecture (source → index → select → weave) stands.*

## Summary and recommendation

- **Keep foley as the fleet's SFX facade; do not start another.** The October research question ("we need a facade for sound effects") was answered by foley in July. What changed since then is the target landscape [1][2], and what the audit found is that foley's licence model is the strongest in the fleet while its facade mechanics are the weakest [3].
- **Fix the honesty layer before adding targets.** Unsupported parameters are dropped silently, offline mode leaks, there is no cost model, rights widen in four places, and the MCP and CLI have drifted from the Python API [3]. These are issues #53–#66. Every new target added before they are fixed inherits the same bugs.
- **Then add four targets, in this order:**
  - Stable Audio 3 Small-SFX as the local default: CPU-capable, 120 s, the same Community licence as today [1][5][6].
  - A `fal` source executed through `falaw`, which gives text-to-SFX from SA3, Mirelo, Sonilo and ElevenLabs, plus video-to-audio [1][7].
  - A "my licensed library" source that reads UCS filenames and BWF/iXML metadata [2][8].
  - Openverse / Wikimedia as keyless sources [2].
- **The common interface stays small:** `search`, `generate`, `edit` (new), `find`/`score`/`weave` (unchanged), `export` (new), `list_backends`, `estimate`. The vocabulary grows only by the two-provider promotion rule (§2), and everything else goes through three escape-hatch rungs (§3).
- **First customer:** a cut-out animated film made with `an`. It needs `export()` (#66) so that a sound reaches `an`'s sounds store with its rights intact, and the V2A mode (#74) for sound timed to picture.

## 1. What changed since July 2026 (one paragraph each)

**Generation [1].** Stable Audio 3 (May 2026) ships an open Small-SFX model that runs on a laptop CPU [5][6]. Two open SFX models with commercially permissive weights appeared (MOSS-SoundEffect v2, Apache-2.0; Dasheng-AudioGen, Apache-2.0) [9]. Video-to-audio became a cheap hosted mode, with ten or more endpoints on fal at $0.001–$0.01 per output second [7]. Two dedicated SFX vendors arrived (Mirelo, Sonilo). ElevenLabs is unchanged (`eleven_text_to_sound_v2`) [10]. Licence traps:
- fal labels MMAudio commercial, but its weights are CC-BY-NC.
- HunyuanVideo-Foley's licence excludes the EU, UK and South Korea [11].
- ThinkSound's weights are tagged Apache-2.0, but its README says research-only.

**Sources [2].** Freesound deprecated the search endpoint foley calls [12], and its API terms reserve commercial use for case-by-case negotiation [13]. Openverse is keyless and licence-rich, but weak for SFX. Epidemic Sound and Splice now expose search through official MCP servers that a subscriber can use [14]. No commercial SFX library allows AI training. A CC BY-SA sound synced to picture makes the whole film an adaptation [15]. And foley's Clotho adapter stamps non-commercial material as CC-BY (#68).

## 2. The common part: verbs and canonical vocabulary

### Verbs (one per job; the backend is one keyword with a free, working default)

```python
foley.search(query, *, k=10, sources=None, kind="sfx", duration_range=None, license=None,
             commercial_ok=None, ucs_category=None, similar_to=None, page=None, **provider_kwargs) -> list[Candidate]
foley.generate(prompt, *, backend=None, duration_s=None, n=1, seed=None, prompt_influence=None,
               negative_prompt=None, loop=None, model=None, output_format=None, video=None,
               provider_params=None, **provider_kwargs) -> list[Candidate]           # n>1 → variations
foley.edit(audio, *, op, backend=None, prompt=None, strength=None,                    # new verb: inpaint | extend | audio-to-audio
           inpaint_start_s=None, inpaint_end_s=None, **provider_kwargs) -> list[Candidate]
foley.find(context, ...) / foley.score(segments, ...) / foley.weave(...)              # unchanged (report 10)
foley.export(sound_id, *, fmt="wav") -> tuple[bytes, dict, dict]                      # new: bytes, rights (lacing.Rights names), provenance (#66)
foley.list_backends(*, kind=None, supports=None) -> list[str]                         # new: capability query (#60)
foley.estimate(verb, **same_kwargs) -> float | None                                   # new: None = unknown → approval (#57)
```

- `backend=None` resolves to the free local default: `stable_audio_3` once #72 lands, `stable_audio` until then. It is never a paid backend unless the operator opts in to paid generation (`FOLEY_GENERATE_PAID=1`, added 2026-10-26: the generation order then tries ElevenLabs direct first, then fal); a key in the environment is not that opt-in. An unknown name raises.
- `commercial_ok` gets **one default for every verb and surface** (#63). The audit found `find` defaulting to commercial use while `score` and MCP default to non-commercial.

### Canonical vocabulary (promotion rule: a concept is canonical only when at least two targets share it)

| Canonical | Native names (examples) | Notes |
|---|---|---|
| `prompt` | EL `text`, Mirelo `text_prompt`, most `prompt` | have |
| `duration_s` | EL `duration_seconds`, SA `duration`, MOSS `seconds`, diffusers `audio_end_in_s` | rename from `duration`. `None` = backend auto. Always measure and store the actual duration |
| `prompt_influence` (0–1) | EL `prompt_influence`, SA `cfg_scale`, fal `guidance_scale`, MMAudio `cfg_strength` | **default `None`** (native default), with a per-backend `coerce` and a `distilled` flag (#70) |
| `negative_prompt` | SA3, fal-SA3, MMAudio, diffusers | absent on the Stability hosted API (report 02's table is wrong) |
| `seed` | most | store the seed the backend **echoes**, and record "not reproducible" for EL, Sonilo and Kling |
| `n` | SA3 `batch_size`, Mirelo `num_samples`, diffusers `num_waveforms_per_prompt` | new. Returns a list, which feeds selection |
| `model` | EL `model_id`, SA `model`, fal endpoint id | new. Stored as `generator_version` |
| `loop` | EL `loop`, Mirelo `ambience` | have (now two providers) |
| `output_format`, `sample_rate` | EL `output_format` enum, fal `audio_format` | requested values; the actual rate is reported back. EL `wav` → `pcm_48000` (#71) |
| `video` | MMAudio, Mirelo, Sonilo, HunyuanVideo-Foley: `video_url` | new mode (#74). Return the audio track only |
| `keep_source_audio` | Sonilo `keep_speech_vocal`, PixVerse `original_sound_switch` | new |
| `init_audio`, `strength` | SA-API `audio` + `strength`, SA3 `init_audio` + `init_noise_level` | `edit()` only |
| `inpaint_start_s`, `inpaint_end_s` | SA-API `mask_start/end`, SA3 `inpaint_mask_*_seconds` | `edit()` only |
| `expand_prompt` | fal SA3 / LTX `enable_prompt_expansion` | store `prompt_sent` and `prompt_used` separately |
| `preset` | jsfxr / pyfxr / rFXGen | procedural kind only (#76) |
| `query` | Freesound `query`, Openverse `q`, Epidemic `term`, Wikimedia `srsearch` | unify with `QUERY_AFFORDANCES['text']` (#75) |
| `page`, `sort` ∈ {relevance, newest, popular, duration} | Freesound `page`/`sort`, Openverse `page`, Epidemic `offset` | convert offsets at the adapter |
| `duration_range` | Freesound `filter=duration:[a TO b]`, Openverse `length` buckets | Openverse reports `duration` in **ms** |
| `license`, `commercial_ok` | Freesound `license` filter, Openverse `license` / `license_type` | normalised ids. Normalisation never widens rights |
| `similar_to` | Freesound `similar_to`, Openverse `/related/`, Epidemic `SearchSimilarToSoundEffect` | new |
| `ucs_category` | Freesound BST category, Epidemic `categoryId` | map each native taxonomy onto UCS [8] |
| `kind` (sfx \| music) | Openverse `category`, IA `mediatype` | **never merged with the taxonomy `category`**: same word, different meaning |
| `include_explicit` | Openverse `mature`, Epidemic `includeExplicit` | new |

**Stays native (one provider; reach it through the escape hatches):** Sonilo time-ranged `segments`, Kling's separate SFX and music prompts, synthesis parameters, sampler internals (`sigma_shift`, `sync_mode`, `enable_safety_checker`), and Freesound's audio descriptors (`ac_brightness`, …).

### Result (common shape, honest about itself)

`Candidate` / `GeneratedClip` keep today's fields, plus:
- `notes`: every dropped parameter, every clamp and every fallback, never silent (#53).
- `cost_estimate_usd` and `cost_actual_usd` (`None` = unknown) (#57).
- `raw`: the native payload (#61).
- On the licence record: `licence_basis`, `territory_excludes`, `vendor_trains_on_output`, and the vendor's watermark statement (#77).

## 3. Escape hatches: three rungs, then `raw`

1. **Canonical kwargs**, portable across backends.
2. **Per-provider params:** `**provider_kwargs` when one backend is chosen, or `provider_params={"freesound": {"ac_brightness": ...}}` on a fan-out. They pass through untranslated, after the canonical translation, and are recorded in `generation_params` / `query_params` (#61).
3. **The native call:** `foley.services.<source>.invoke_native(**native)` returns the provider's response with no translation (#61).

And out of the result: `candidate.raw`. A caller never has to leave foley to read a field the provider returned.

## 4. Capability honesty: what must be declared, enforced and tested

- **One dispatch path** (`foley/sources/_dispatch`) interprets each source's `param_map`, applies the unsupported-parameter policy and writes `notes`. Python, `services`, CLI and MCP all go through it (#53). Meaning-carrying parameters raise rather than drop: `seed` on a non-reproducible backend, `video` on a text-only backend.
- **`capabilities` per source config:** `modes` (`t2a`, `v2a`, `edit`), `emits` (the fields the adapter really fills), `deterministic`, `loopable`, `max_duration_s`, `sample_rates`, `vendor_watermark`, `offline`. Tests check each one against the fakes, and `list_backends(supports=...)` reads them (#60).
- **A ledger of targets** (`foley/data/targets.json`) generated from reports 13 and 14's inventory cards, with `implemented` computed from the registry. It replaces the stale roadmap as the "what's next" list (#60, #65).
- **Cost:** `pricing` in each config (unit, price, `seen` date, source). fal prices are read live from its pricing endpoint [7]. A cumulative `Budget.max_usd` stops a run before the first paid call that would exceed it (#57). Live-API tests need `FOLEY_LIVE_API_TESTS=1`, and the suite scrubs keys (#58).
- **Licence:** the fail-closed gate stays. Fix the four widening paths (#55, #56, #68, #69), and add the schema fields above (#77). The AI-generation block survives export (#66).

## 5. What to build next (v-next seam table)

| # | Seam | Default (no new dependency) | Replacement already in view |
|---|---|---|---|
| 1 | generate backend | `stable_audio_3` small-sfx, local CPU (#72) | `fal` via falaw (#73), `stability_api`, `elevenlabs` |
| 2 | retrieve source | the user's own indexed library | `freesound` (CC0 + CC-BY, #78), `my_library` with UCS/BWF (#80), `openverse` / `wikimedia` (#79), `epidemic_sound` via MCP (#81) |
| 3 | generation mode | text-to-audio | `video=` V2A (#74), `edit()` ops (#75) |
| 4 | cost gate | `estimate()` → `None` forces approval | `Budget.max_usd` cumulative (#57) |
| 5 | export target | `export()` → `lacing.Rights`-shaped dict | an's `fetcher=` intake (an#318), UCS/BWF file export (#80) |

**NOT seams:** the CLI and MCP tool list (generated from one verb table, #62); the licence normalisation table (data, not a strategy); log format.

**One-command test for the next milestone:** `foley generate "a heavy wooden door creaks open" --duration-s 3` runs offline on CPU with Stable Audio 3, returns a `Candidate` with a licence record, notes and provenance, and `foley export <id>` yields WAV bytes plus a rights dict that `an sounds add` accepts.

## 6. Issue map

- **Audit (report 15):** #53–#66.
- **Research delta:** #67–#71 (bugs: Freesound endpoint, Clotho licence, `gen_ai_preference`, guidance default, ElevenLabs PCM) and #72–#81 (targets and capabilities).
- **Companions in other repos:** [thorwhalen/an#332](https://github.com/thorwhalen/an/issues/332) (honour `cacheable=False`; Stable Audio and versioned CC-NC licence rows), [thorwhalen/lacing#61](https://github.com/thorwhalen/lacing/issues/61) (how a generated artifact records its generator's terms), [thorwhalen/an#318](https://github.com/thorwhalen/an/issues/318) (sound from a URL with provenance), and [thorwhalen/ocracy#7](https://github.com/thorwhalen/ocracy/issues/7) (the facade kit that foley's translator should come from, once it exists).

## 7. Open questions for the maintainer

1. **Order:** honesty fixes (#53, #55–#59, #63) before new targets? *Recommended: yes.*
2. **Commercial intent default:** should every verb default to `commercial_ok=True` (fail closed on NC), as `find` does today? *Recommended: yes for a film pipeline, with the NC opt-in explicit.*
3. **Spend:** what cumulative ceiling per run, and per day? *Recommended: $1 per run by default, with unknown cost requiring approval.*
4. **Subscriptions:** does the production hold an Epidemic Sound, Splice, ElevenLabs (which tier?) or Mirelo plan? This decides #81 and the ElevenLabs licence row (#56).
5. **Freesound commercial API use:** email UPF for the production, as ToS §3 suggests [13]? *Recommended: yes, before any release that ships Freesound-sourced sounds.*

## REFERENCES

1. [foley report 13 — SFX generation targets: the delta since July 2026](13-generation-targets-2026-10.md)
2. [foley report 14 — SFX search, library and corpus targets, client libraries, and the shared vocabulary](14-source-targets-2026-10.md)
3. [foley report 15 — facade audit of foley v0.0.26](15-facade-audit-2026-10.md)
4. [foley report 10 — facade architecture (July 2026)](10-facade-architecture.md)
5. [GitHub — Stability-AI/stable-audio-3 (models, hardware, performance)](https://github.com/Stability-AI/stable-audio-3)
6. [Stability AI — Community License](https://stability.ai/community-license-agreement)
7. [fal Platform API — model search and pricing (`GET /v1/models`, `GET /v1/models/pricing`), queried 2026-10-03](https://api.fal.ai/v1/models)
8. [Universal Category System — official site (UCS 8.2.1)](https://universalcategorysystem.com/)
9. [Hugging Face — OpenMOSS-Team/MOSS-SoundEffect-v2.0 (Apache-2.0)](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0)
10. [ElevenLabs — OpenAPI spec (`/v1/sound-generation`)](https://api.elevenlabs.io/openapi.json)
11. [GitHub — Tencent-Hunyuan/HunyuanVideo-Foley LICENSE](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley/blob/main/LICENSE)
12. [Freesound APIv2 — Resources (search, filters, fields, gen_ai_preference, download)](https://freesound.org/docs/api/resources_apiv2.html)
13. [Freesound — API Terms of Use](https://freesound.org/help/tos_api/)
14. [Epidemic Sound — MCP server documentation](https://developers.epidemicsound.com/docs/mcp)
15. [Creative Commons — BY-SA 4.0 legal code (sound synched to moving image is Adapted Material)](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en)
