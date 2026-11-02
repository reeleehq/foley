# Licensing, Rights, Provenance & Attribution — the legal/traceability layer for foley

**Research brief for `foley`** — a retrieval-first façade that finds (or generates) sound effects and weaves them into **published** narrations. Because the output ships, every sound — sourced or generated — carries rights obligations that must be tracked *per sound* and enforced *before* a clip reaches a render. This report defines the license landscape foley must reason over (Creative Commons, "royalty-free", rights-managed, and the AI-generation terms), the attribution mechanics it must automate, the provenance/watermarking/disclosure layer it should record, and the voice-likeness / trademarked-sound pitfalls it must guard against. It closes with a concrete **`LicenseRecord`** field spec and a **license-compatibility filter policy** the agent applies to keep or reject candidates for a given intended use.

> **Access date:** 2026-07-22. License texts and platform policies change; every clause below is dated to its source version and drawn from primary texts (CC legal code/deeds, official terms pages, model licenses, standards specs) wherever possible. This report is engineering guidance, **not legal advice** — foley should surface obligations to users, not adjudicate them.

This report builds on **report 01** (Freesound/CC0 as the redistributable anchor; the per-sound `LicenseRecord` idea) and **report 02** (per-model output/weight licenses). It deepens the cross-cutting rights layer flagged in `design.md`.

---

## 1. The two axes that actually matter

Almost every licensing question foley faces collapses onto **two independent axes**, plus a few secondary flags. Getting these straight prevents the most common mistake — conflating "free" with "unrestricted."

1. **Commercial use** — may the finished narration be monetized (ads, sponsorship, paid product, brand work)?
2. **Redistribution mode** — two very different things share the word "redistribute":
   - **(a) Embedded-in-a-derivative** — the sound baked into a narrated video/podcast. *Nearly every* license (CC, royalty-free, rights-managed, AI-output) permits this; it is the normal case.
   - **(b) Standalone redistribution** — re-exposing the raw file as a downloadable asset, sample pack, dataset, or corpus. *Most* licenses **forbid** this (all the "royalty-free" libraries; ElevenLabs SFX; Sonniss; PSE). Only **CC0 / CC-BY / public-domain** permit it.

Secondary flags foley must also carry: **attribution required?**, **AI-training/dataset use allowed?**, **modification allowed?**, **revenue cap?**, and (for generated audio) **synthetic-media disclosure required?**.

"Royalty-free" and "rights-managed" are **not** license identities — they are *pricing models* layered on a proprietary license:

- **Royalty-free (RF)** — pay once (or nothing), then reuse in unlimited projects with **no per-use royalty**. It is **not** public-domain and **not** standalone-redistributable: the raw file must stay embedded in a finished work, the license is usually non-transferable, and "free" refers to *royalties*, not *price*. (Pixabay, Storyblocks, Mixkit, Sonniss all fit here.) [1][20][21]
- **Rights-managed (RM)** — licensed for a **specific** use, scope, medium, duration, and territory, priced per use; using it outside that scope is infringement. Rare in SFX, common in premium music/footage. Highest friction; foley should treat any RM sound as **use-locked** metadata.

---

## 2. License comparison table

Legend — **Commercial**: may the finished narration be monetized. **Embed**: may the sound be baked into a derivative (the normal case). **Standalone redist.**: may the raw file be re-exposed as a downloadable/corpus. **Attribution**: credit required. **AI-train**: may it feed a training/dataset pipeline. All CC "4.0" rows are the versions Freesound actually serves. [2]

| License / terms | Commercial | Embed in derivative | Standalone redist. | Attribution | AI-train | Notes / source |
|---|---|---|---|---|---|---|
| **CC0 1.0** | ✅ | ✅ | ✅ | ❌ none | ✅ | Public-domain dedication; **no** trademark/publicity waiver [3] |
| **CC-BY 4.0** | ✅ | ✅ | ✅ | ✅ TASL | ✅ | Must credit + link license + note changes [4][5] |
| **CC-BY-NC 4.0** | ❌ | ✅ (non-comm only) | ✅ (non-comm) | ✅ | ⚠️ non-comm | NonCommercial kills monetized narration [4] |
| **CC Sampling+ 1.0** (retired) | ⚠️ *sample only* | ✅ if transformed | ❌ verbatim-commercial barred | ✅ | ⚠️ | Retired 2011-09-12; legacy Freesound sounds; commercial **only as a creatively-transformed sample**, no ads [6][7] |
| **Royalty-free** (Pixabay, Storyblocks, Mixkit, Sonniss) | ✅ | ✅ | ❌ | usually ❌ | usually ❌ (Sonniss/Pixabay bar it) | Pricing model, not a public license [1][20][21] |
| **Rights-managed** | scope-locked | scope-locked | ❌ | per-contract | ❌ | Per-use license; treat as use-locked |
| **BBC RemArc** | ❌ | non-comm only | ❌ | ✅ | ❌ | Personal/education/research only [22] |
| **ElevenLabs SFX** (paid) | ✅ | ✅ | ❌ standalone barred | ❌ | n/a (your output) | Own outputs; **no isolated-file resale**; sublicensed to other users unless "Disable" [8][9] |
| **ElevenLabs SFX** (free) | ❌ | ✅ non-comm | ❌ | ✅ credit ElevenLabs | n/a | Free tier = non-commercial + attribution [8][10] |
| **Stability Stable Audio** (hosted, paid) | ✅ | ✅ | ❌ | ❌ | n/a | Commercial; Enterprise adds indemnification; trained on licensed data [11][12] |
| **Stable Audio Open 1.0/Small** (weights) | ✅ **< $1M rev** | ✅ | ❌ (of weights) | ⚠️ *for the model, not outputs* | ❌ improve foundation model | Community License; **you own outputs**; notice only when redistributing the *model* [13][14] |
| **AudioGen / AudioLDM(2) / Tango(2) / Auffusion / MMAudio** (weights) | ❌ | — | ❌ | ✅ | ❌ | **CC-BY-NC** weights → treat outputs as non-commercial [15] (report 02) |
| **Make-An-Audio 1** (weights) | ✅ | ✅ | permissive | ✅ (MIT notice) | ✅ | MIT — rare permissive open SFX model (report 02) |

Key reading: the **only rows that are both commercial-safe and standalone-redistributable are CC0, CC-BY, and public-domain.** That is exactly report 01's finding that **CC0 is foley's redistributable anchor** — this report just widens the frame to generation and the professional tiers.

---

## 3. Creative Commons & "royalty-free", precisely

### 3.1 CC0 1.0 — the anchor, with a sharp caveat
CC0 is a **public-domain dedication**: the uploader waives copyright and related rights "to the extent possible under law," so reusers may "distribute, remix, adapt, and build upon the material in any medium or format, with no conditions" and **no attribution**. [3] This is why CC0 is the one tier foley can freely cache, redistribute, and even train on.

**The caveat that matters for a publishing product:** CC0 waives the *uploader's* copyright — it does **not** grant or waive **trademark or publicity rights**, and cannot waive rights the uploader never held. A sound uploaded as CC0 that happens to *be* a trademarked audio logo (say, a recording of the NBC chimes) is still trademark-encumbered — the CC0 dedication is powerless over NBC's mark. CC0 removes the *copyright* obstacle, not the *trademark/likeness* one (see §7). foley should still keep CC0 attribution/provenance data even though credit is optional — it is cheap insurance and good etiquette.

### 3.2 CC-BY 4.0 — commercial + redistributable, *if you credit*
CC-BY 4.0 permits commercial use, remix, and redistribution (including standalone) **provided you attribute**. The 4.0 attribution standard is **TASL**: **T**itle, **A**uthor, **S**ource, **L**icense — plus a link to the license and an **indication if you modified** the work. [4][5] Attribution must be "reasonable to the medium" (see §4). For foley this is fully automatable: every CC-BY sound already carries title, uploader, URL, and license id, so the credit string is a template fill.

### 3.3 CC-BY-NC 4.0 — the monetization trap
Identical to CC-BY **except NonCommercial**. Because foley's narrations are frequently monetized, **CC-BY-NC is disqualified whenever `commercial_ok` is requested** — and NC is subtle: NC bars use "primarily intended for or directed toward commercial advantage," which most ad-supported/sponsored content triggers. Treat NC as **non-commercial-only** and filter it out of any commercial pipeline. (Freesound and FSD50K both mix ~12% CC-BY-NC into result sets, per report 01.)

### 3.4 CC Sampling+ 1.0 — retired, still lurking
Creative Commons **retired the Sampling family on 2011-09-12** (low adoption, non-interoperability), and "does not recommend that it be applied to works" — but **legacy Freesound sounds still carry it.** [2][6][7] Its terms are unusual: you may **sample/transform commercially**, and distribute the *whole* work only **non-commercially**; you may **not** use the work to advertise anything but your own derivative, and **verbatim commercial redistribution is barred.** [6] Practical rule for foley: **treat Sampling+ as commercial-OK only when the sound is used as a transformed sample inside a larger work, never verbatim, never in ads** — and, because that nuance is hard to guarantee automatically, **default to excluding Sampling+ from commercial results** unless the user explicitly opts in.

### 3.5 Royalty-free ≠ free ≠ redistributable
The single most common misunderstanding. RF libraries (Pixabay audio, Storyblocks, Mixkit, Sonniss GDC) grant broad commercial embed rights with **no per-use royalty and usually no attribution**, but **forbid standalone redistribution** and often **forbid AI-training/dataset compilation** (Sonniss and Pixabay explicitly). [1][20][21] foley must never treat "royalty-free" as a green light to cache-and-serve raw files or to train on them — those are exactly the standalone/AI-train flags that RF licenses withhold.

### 3.6 CC BY-SA synced to picture — the film becomes an adaptation
The CC 4.0 legal code defines **Adapted Material** so that, "where the Licensed Material is a musical work, performance, or sound recording, Adapted Material is always produced where the Licensed Material is synched in timed relation with a moving image" (Section 1(a)). [32] Laying a CC BY-SA sound under a film, a video or an animated narration therefore makes the whole audiovisual work an adaptation of that sound, and ShareAlike (Section 3(b)) then requires, once the film is shared, the adapter's licence for it to be BY-SA 4.0 or a BY-SA-compatible licence: one share-alike footstep can force the film itself under a copyleft licence. The same definition is why a NoDerivatives sound cannot be synced to picture at all (sharing Adapted Material is not licensed). This is why foley maps every share-alike and no-derivatives licence to `unknown` and refuses it (`license_id_from_cc_url`, `is_share_alike`, `derivative_refusal`): a picture use is the normal case for its output, not an edge case.

---

## 4. Attribution mechanics — auto-generating correct credit

### 4.1 The canonical credit string
For CC-BY (and CC-BY-NC in non-commercial contexts), the CC-recommended and Freesound-required shape is **TASL**. Freesound's own FAQ gives the template [2]:

> "This [video/podcast/...] uses these sounds from freesound: **'{title}'** by **{username}** ( {sound_url} ) licensed under **{license_name+version}**"

A machine-generated, TASL-complete credit line foley should emit:

```
"{title}" by {creator} — {source_url} — licensed under {license_name} {license_version} ({license_url}){changed_note}
```

- `{changed_note}` = `" (modified)"` whenever the transformation log is non-empty (CC-BY 4.0 requires indicating changes). [5]
- For **CC0**: attribution is optional; foley should still be able to emit a courtesy line (`"{title}" by {creator} — {source_url} — CC0/public domain`) but must not *require* it.
- For **long lists**, Freesound explicitly permits a consolidated pointer: "uses many sounds from freesound, for the full list see {credits_url}." [2] foley should generate **both** an inline short form and a full machine-readable credits manifest (JSON + rendered `CREDITS.md`).

### 4.2 Where credits must appear
Attribution must be "reasonable to the medium" [5] — foley should place it in *all* channels it can reach:

- **Video** — end-credits card **and** the description box (YouTube/Vimeo). Description-box credit is the de-facto standard and is where Freesound's template points. [2]
- **Podcast/audio-only** — show notes and episode description.
- **Any format** — an embedded `CREDITS.md` / attribution sidecar shipped with the render, plus (ideally) file-level metadata (see §5.3, C2PA/ID3).

**Per-provider extras** foley must add to the credit block:
- **ElevenLabs free tier** — must credit ElevenLabs ('elevenlabs.io'). Paid: no attribution. [8][10]
- **Stable Audio Open** — "Powered by Stability AI" + the notice text are required **only if you redistribute the *model/weights*, not for using outputs** [13][14] (see §5.3). foley does not redistribute weights, so this is normally **not** a credit obligation — but foley should record it so a user who *does* ship the model is warned.

### 4.3 Implementation
Attribution generation is a **pure function of the `LicenseRecord`** — no per-source special-casing beyond a small `license_id → template` table. Store the *ready-to-print* string at ingest (report 01's `attribution` field), regenerate on demand from structured fields, and append the `(modified)` flag from the transformation log. This makes "emit a correct credits list for this render" a one-call operation over the set of sounds actually used.

---

## 5. AI-generated audio — output ownership, usage terms, and weight licenses

### 5.1 ElevenLabs Sound Effects (`/v1/sound-generation`)
Terms last updated **2026-02-12**. [8]
- **Ownership:** users own the generated output. [10]
- **Commercial use:** **paid plans → full commercial rights**, retained **perpetually** for already-generated audio even after cancellation; **free plan → non-commercial only, must attribute ElevenLabs.** [8][10]
- **Hard SFX restriction:** you may **not** sell, redistribute, or "commercially exploit any Output generated using Sound Effects **on a standalone basis** … as isolated files, audio samples, … libraries, or other collections of sounds." [8] I.e. embed-in-narration ✅, ship-as-a-sample-pack ❌. This maps directly to `redistribute_standalone_ok = False`.
- **Sublicensing / opt-out:** by default your SFX outputs are **sublicensed to third parties** (other ElevenLabs users may receive them); you may **opt out prospectively** via the **"Disable"** control on the product page — it does not revoke sublicenses already granted. [8] foley should surface this to users who care about exclusivity.

### 5.2 Stability — hosted Stable Audio (2.5/3.0 API)
Commercial use granted on the developer platform; **Enterprise license adds legal indemnification**; Stability markets it as **trained on fully licensed data** (486,492 CC0/CC-BY/CC-Sampling+ recordings for the *open* model; licensed catalog for the hosted models). [11][12] This is the pick when a user needs **indemnified, provenance-clean** generated audio. Standalone redistribution of raw outputs is not part of the model → `redistribute_standalone_ok = False`.

### 5.3 Stable Audio Open 1.0 / Small — the **Community License** (weights)
Community License **v. 2024-07-05**. [13][14] The crucial distinctions for foley:
- **You own your outputs** ("You own any outputs generated from the Models … to the extent permitted by applicable law"). [13]
- **Commercial use is free under US $1,000,000 annual revenue**; at/above that, you must obtain an **Enterprise license**. [13][14] → carry a **`revenue_cap`** flag.
- **Attribution/notice obligations attach to distributing the *model or a derivative work of the model*, not to using outputs**: keep a NOTICE reading *"This Stability AI Model is licensed under the Stability AI Community License, Copyright © Stability AI Ltd. All Rights Reserved,"* provide the license to downstream recipients, and **"prominently display 'Powered by Stability AI'"**. [13][14] Since foley ships *outputs*, not weights, these do **not** bind normal narration use — but foley must **record** them (`notice_text_required`) so a user who redistributes the model is warned.
- **You may not use it to train/improve a competing foundation model.** [13] → `ai_training_ok = False` for the *foundation-model* sense (fine to cache outputs into foley's retrieval index).

### 5.4 Open **CC-BY-NC** weights (AudioGen, AudioLDM/2, Tango/2, Auffusion, MMAudio)
These weights are **CC-BY-NC-4.0/-SA** (report 02, [15]). A model license governs the **weights**, but using an NC-licensed model to produce **commercial** output is itself a commercial use of the model → **disqualified for monetized narration.** foley's rule: **outputs of NC-licensed generators inherit `commercial_ok = False`.** Keep them for non-commercial/experimental use, hard-flagged. The lone permissive open exception is **Make-An-Audio 1 (MIT)** → commercial-OK with an MIT notice.

### 5.5 The generation-provenance obligation
Every generated clip is **synthetic media** and must record **model + version + prompt + seed + params** (for reproducibility, disclosure, and dispute defense) and, ideally, a **watermark** and **C2PA manifest** (§6). This is non-negotiable for a publishing product: if a platform or rights-holder later asks "where did this sound come from," foley must answer from stored provenance, not memory.

---

## 6. Provenance, watermarking & disclosure

### 6.1 Per-sound provenance chain
For **every** sound (retrieved or generated) foley must persist, as a sidecar keyed to the audio blob (report 01's `dol` manifest pattern):
- **Origin** — `source`, `source_id`, `source_url`, `acquisition_method` (`api|bulk|scrape-pointer|generated`), `retrieved_at`, adapter name+version.
- **Rights** — the full `LicenseRecord` (§8).
- **Content identity** — `content_sha256` of the canonical bytes (content-addressing → dedup, tamper-evidence, and a stable provenance key).
- **Transformation log** — an ordered list of ops applied in `weave`/ingest (`trim`, `normalize_lufs`, `pitch_shift`, `time_stretch`, `resample`, `fade`, `mix`) with params. This both (a) drives the CC-BY "(modified)" flag and (b) lets a render be **re-derived** from originals (the editable-timeline goal in `design.md`).
- **Generation block** (if AI) — `is_ai_generated`, `generator_model`, `generator_version`, `prompt`, `seed`, `params`.

### 6.2 AI-audio watermarking — Meta **AudioSeal**
**AudioSeal** (Meta) is the leading open watermarking scheme for AI audio: a jointly-trained generator/detector that embeds an **imperceptible, localized** watermark and detects it **per-sample (≈1/16000 s)** — robust to compression, re-encoding, and noise, and up to two orders of magnitude faster than prior detectors. It is now **MIT-licensed** (code *and* model). [16][17][18] For foley this is a cheap, embeddable step: **watermark every *generated* clip on the way out** (`watermark = {present: true, method: "audioseal", version}`), so downstream systems (and foley itself) can later verify a clip was machine-made. (Watermarking *retrieved* real-world sounds is neither needed nor appropriate.)

### 6.3 Content provenance — **C2PA / Content Credentials**
**C2PA** (Coalition for Content Provenance and Authenticity) is the cross-industry standard for cryptographically-bound provenance manifests, and it **explicitly covers audio assets** (WAV/MP3 streams as first-class asset types; example manifests include "an audio stream that has been shortened"). [19] A C2PA **Content Credential** is a signed manifest of **assertions** — origin, edits, and **"use of AI."** Current spec line is **2.x** (2.1 → 2.4, 2024–2025), adding **durable Content Credentials** (metadata + soft-binding via watermark/fingerprint so the manifest survives re-export). [19] foley should, at least optionally, **write a C2PA manifest** into rendered outputs recording: which sounds were used, their licenses, and which were AI-generated — turning foley's internal provenance store into a portable, verifiable credential. Pair it with AudioSeal as the soft-binding fallback.

### 6.4 Platform synthetic-media disclosure rules
foley's outputs land on platforms that now **require disclosure** of realistic AI media — foley should compute a `disclosure_recommended` flag and tell the user:
- **YouTube** — since **March 2024**, creators must disclose **"altered or synthetic" realistic content** via a Creator-Studio field; the label shows in "How this content was made" (and prominently on the player for sensitive topics). The trigger is **realism that could mislead** — notably **AI voice clones of a real person**. Pure AI *SFX* or a clearly-synthetic narrator generally **does not** trigger it; a cloned real voice **does.** [23][24]
- **TikTok** — requires labeling realistic AI images/audio/video; **integrated C2PA Content Credentials in Jan 2025** and now **auto-labels** content whose embedded credentials indicate AI, even absent self-disclosure. Unlabeled realistic deepfakes of real people are prohibited. [25][26]
- **Meta (FB/IG)** — analogous "AI info" labels driven by C2PA/IPTC metadata.

Design consequence: if foley uses a **cloned/real voice** or produces **photoreal-adjacent realistic** synthetic audio of a real person/event, it should **strongly recommend disclosure** and, where it writes C2PA, make that the machine-readable disclosure carrier.

---

## 7. Safety — voice/likeness and trademarked-sound pitfalls

### 7.1 Voice & likeness (the highest-risk area)
Generating a **recognizable real person's voice** is a distinct legal exposure from copyright — it implicates **right of publicity** and new voice-clone statutes:
- **Tennessee ELVIS Act (2024)** — first US law to **expressly extend right-of-publicity to AI voice clones**; criminalizes unauthorized digital voice replication + civil remedies. [27]
- **NO FAKES Act (federal, reintroduced Apr 2025, H.R.2794 / Senate companion)** — would create a **nationwide right against unauthorized AI replicas of voice/likeness**; advanced in committee but **not yet law** as of mid-2026; several states have parallel laws. [28][29]
- **Right of publicity** (state common law/statute) already reaches soundalikes in many states.

**foley rule:** the retrieval/generation core should **never** clone or synthesize an identifiable real person's voice without explicit user-supplied consent/authorization; flag any voice-bearing sound with `contains_recognizable_voice` and gate it. (foley is SFX-first, so this is mostly an **exclusion**: filter out speech/voice content from SFX results, and refuse voice-clone generation prompts.)

### 7.2 Trademarked / branded sounds
Distinctive brand audio is protected as **sound trademarks**, independent of copyright: **NBC's three chimes** (first US registered sound mark, 1978), **MGM's lion roar**, **20th Century Fox fanfare**, **THX "Deep Note,"** **Intel's five-note bong**, **Netflix "Ta-dum"** (registered 2017), even **Homer Simpson's "D'oh!"** [30][31] A CC0/CC-BY upload that *is* one of these is **still trademark-encumbered** (§3.1) — the audio license cannot clear the mark. Likewise, **generating** a sound that reproduces a recognizable trademarked audio logo risks infringement/dilution.

**foley rule:** carry a `potential_trademark` flag; **do not** knowingly retrieve-and-serve or generate recognizable branded audio logos for commercial use; when a generation prompt names a brand sound ("the THX sound," "Netflix intro chime"), refuse or warn.

### 7.3 Copyrighted-recording pitfalls
Beyond marks: a "free" upload may be an **unauthorized rip** of a copyrighted recording (e.g., a game/film SFX re-uploaded as CC0). Provenance + content-hash dedup and (where available) **source reputation** help, but foley cannot fully verify chain-of-title. Mitigation: **prefer high-trust sources** (Freesound CC0 with a real uploader history, FSD50K, first-party generation), record provenance so takedowns are traceable, and **fail closed** on unknown/unverifiable rights for commercial renders.

---

## 8. Recommendations for foley

### 8.1 The `LicenseRecord` — exact fields every sound must carry
Extend report 01's minimal record into a full rights+provenance object, stored as a JSON sidecar keyed to the audio blob in a `dol` store. Fields group into **identity**, **rights**, **provenance**, **generation**, and **safety**:

```python
LicenseRecord = {
    # ── identity / origin ─────────────────────────────────────────
    "source": "freesound",  # adapter that produced it
    "source_id": "12345",
    "source_url": "https://freesound.org/s/12345/",
    "acquisition_method": "api",  # api | bulk | scrape_pointer | generated
    "retrieved_at": "2026-07-22T14:30:45Z",
    "adapter_version": "freesound@0.3.1",
    "content_sha256": "9f2b…",  # hash of canonical bytes (dedup + provenance key)
    # ── rights (the license, normalized) ──────────────────────────
    "license_id": "CC-BY-4.0",  # SPDX where possible; else RemArc,
    #   Sonniss-GDC, ElevenLabs-SFX,
    #   Stability-Community, Proprietary-<vendor>
    "license_name": "Creative Commons Attribution 4.0",
    "license_version": "4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "rights_holder": "user 'foo'",
    "creator_name": "foo",
    "creator_url": "https://freesound.org/people/foo/",
    # derived boolean flags (cheap query-time filtering — the SSOT for §8.2)
    "commercial_ok": True,
    "embed_in_derivative_ok": True,  # ~always True; the normal case
    "redistribute_standalone_ok": True,  # raw-file re-exposure / sample pack
    "modification_ok": True,
    "ai_training_ok": True,  # feed a training/dataset pipeline
    "revenue_cap_usd": None,  # e.g. 1_000_000 for Stability Community
    # attribution
    "requires_attribution": True,
    "attribution_text": '"door creak" by foo — https://freesound.org/s/12345/ — licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)',
    "notice_text_required": None,  # e.g. Stability NOTICE when redistributing weights
    # ── provenance / transformation ───────────────────────────────
    "transformations": [  # ordered; non-empty ⇒ credit "(modified)"
        {"op": "trim", "params": {"start": 0.2, "end": 3.1}},
        {"op": "normalize_lufs", "params": {"target": -23.0}},
    ],
    # ── generation (present iff AI-generated) ─────────────────────
    "is_ai_generated": False,
    "generator_model": None,  # e.g. "elevenlabs:eleven_text_to_sound_v2"
    "generator_version": None,
    "generation_prompt": None,
    "generation_seed": None,
    "watermark": None,  # {"present": True, "method": "audioseal", "version": "..."}
    "c2pa_manifest_ref": None,  # pointer to written Content Credential
    # ── safety / disclosure ───────────────────────────────────────
    "contains_recognizable_voice": False,
    "potential_trademark": False,
    "disclosure_recommended": False,  # synthetic-media platform label hint
    "rights_verified": True,  # False ⇒ treated as unknown (fail-closed)
    "verified_at": "2026-07-22T14:30:45Z",
}
```

Two design rules make this maintainable:
1. **A `license_id → flag-set` table is the SSOT.** Adding a source means "declare its default `license_id`(s)"; the boolean flags are looked up, never re-hand-coded. Per-item overrides (Freesound's per-sound license) win over the source default.
2. **Never discard provenance.** Even for CC0 (no attribution required), store origin + hash + creator — it is cheap and is the only defense against takedowns, trademark disputes, and "where did this come from" audits.

**Seed `license_id → flags` table** (extend as sources are added):

| `license_id` | commercial | standalone_redist | modification | ai_training | requires_attr | revenue_cap |
|---|---|---|---|---|---|---|
| `CC0-1.0` | ✅ | ✅ | ✅ | ✅ | ❌ | — |
| `CC-BY-4.0` | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `CC-BY-NC-4.0` | ❌ | ✅(nc) | ✅ | ⚠️(nc) | ✅ | — |
| `CC-Sampling+-1.0` | ⚠️ sample-only | ❌ | ✅ | ⚠️ | ✅ | — |
| `RemArc` | ❌ | ❌ | ✅ | ❌ | ✅ | — |
| `Sonniss-GDC` | ✅ | ❌ | ✅ | ❌ | ❌ | — |
| `Pixabay-Content` | ✅ | ❌ | ✅ | ❌ | ❌ | — |
| `ElevenLabs-SFX` (paid) | ✅ | ❌ | ✅ | n/a | ❌ | — |
| `Stability-Community` | ✅ | ❌ (of weights) | ✅ | ❌ (foundation) | ⚠️ model-only | 1_000_000 |
| `MIT` | ✅ | ✅ | ✅ | ✅ | ✅ (notice) | — |
| `Proprietary-*` / unknown | ❌* | ❌ | ❌ | ❌ | — | — |

\* fail-closed default until verified.

### 8.2 License-compatibility filter policy (the agent's keep/reject rule)
The caller declares an **`IntendedUse`**; the agent filters candidates by comparing it to each record's flags. **Fail closed** — unknown/unverified rights are rejected for anything published commercially.

```python
IntendedUse = {
    "commercial": True,  # will the render be monetized?
    "publish": True,  # embed-in-derivative (≈ always True for foley)
    "redistribute_standalone": False,  # ship raw files / sample pack? (rare)
    "will_train": False,  # feed sounds into model training?
    "can_attribute": True,  # can the pipeline emit credits in this channel?
    "revenue_usd": 0,  # caller's annual revenue (for capped licenses)
    "allow_voice_or_trademark": False,
}


def keep(rec: LicenseRecord, use: IntendedUse) -> bool:
    if not rec["rights_verified"]:
        return False  # fail-closed
    if use["commercial"] and not rec["commercial_ok"]:
        return False
    if use["publish"] and not rec["embed_in_derivative_ok"]:
        return False
    if use["redistribute_standalone"] and not rec["redistribute_standalone_ok"]:
        return False
    if use["will_train"] and not rec["ai_training_ok"]:
        return False
    cap = rec["revenue_cap_usd"]
    if cap is not None and use["revenue_usd"] >= cap:
        return False  # e.g. Stability >$1M
    if rec["requires_attribution"] and not use["can_attribute"]:
        return False  # can't credit ⇒ drop
    if not use["allow_voice_or_trademark"] and (
        rec["contains_recognizable_voice"] or rec["potential_trademark"]
    ):
        return False
    return True
```

Policy notes:
- **Attribution is a *filter*, not just a footnote.** If the delivery channel can't carry credits (`can_attribute=False`), CC-BY/Sampling+ candidates are **dropped** in favor of CC0 — foley should *prefer* CC0 whenever a valid credit surface isn't guaranteed.
- **Push the filter into the query where possible.** Translate `IntendedUse` into each source's native constraint (Freesound `license:"Creative Commons 0"`; FSD50K `license in {CC0, CC-BY}`; exclude BBC/Sonniss for commercial; exclude NC-weight generators for commercial) so rejected candidates are never fetched — mirrors report 01's per-source query composition.
- **Sampling+ and NC default to *excluded* for commercial** unless the user explicitly opts in and accepts the sample-only / non-commercial constraint.
- **Generation obligations:** on any *generated* commercial clip, foley should (a) verify the backend's `commercial_ok` (Stable Audio Open <$1M, ElevenLabs/Stability paid, Make-An-Audio-1 — **not** the CC-BY-NC family), (b) **AudioSeal-watermark** the output, (c) optionally write a **C2PA** manifest, and (d) set `disclosure_recommended` if a real voice/likeness is involved.
- **Emit credits automatically** at render time from the union of `attribution_text` over sounds actually used, appending `(modified)` where the transformation log is non-empty, and writing both an inline short form and a `CREDITS.md` + JSON manifest.

### 8.3 Where this plugs into the architecture
- The `SOURCE_CONFIG` `license` block (design.md) declares each source's **default `license_id`(s)** and whether license is **per-item**; the adapter resolves the per-item license into a `LicenseRecord`.
- The `LicenseRecord` is a first-class part of the canonical `SoundRecord` (report 04) — same store, same key as the audio blob.
- The **agent's `decide()` step** (report 05) runs `keep()` as a hard gate *before* verification/ranking, so no license-incompatible clip ever reaches a render.
- **Weave** (report 06) appends to the transformation log and, at export, invokes the credit generator + optional AudioSeal/C2PA writers.

---

## REFERENCES

1. [What is "royalty-free"? — general RF vs RM overview (Pixabay Content License summary)](https://pixabay.com/service/license-summary/)
2. [Freesound — Frequently Asked Questions (licenses used, CC0 no-credit, required attribution template, YouTube claims)](https://freesound.org/help/faq/)
3. [Creative Commons — CC0 1.0 Universal Public Domain Dedication (deed)](https://creativecommons.org/publicdomain/zero/1.0/)
4. [Creative Commons — About CC Licenses (BY, BY-NC characteristics)](https://creativecommons.org/share-your-work/cclicenses/)
5. [Creative Commons — Recommended practices for attribution (TASL; indicate changes; reasonable to medium)](https://wiki.creativecommons.org/wiki/Best_practices_for_attribution)
6. [Creative Commons — Sampling Plus 1.0 (deed: sample commercially; whole-work only non-commercial; no advertising)](https://creativecommons.org/licenses/sampling+/1.0/)
7. [Creative Commons — "Celebrating Freesound 2.0, retiring Sampling licenses" (2011-09-12 retirement)](https://creativecommons.org/2011/09/12/celebrating-freesound-2-0-retiring-sampling-licenses/)
8. [ElevenLabs — Sound Effects Terms (last updated 2026-02-12; standalone-file prohibition; default sublicensing + "Disable" opt-out)](https://elevenlabs.io/sound-effects-terms)
9. [ElevenLabs — Terms of Use (non-EEA)](https://elevenlabs.io/terms-of-use)
10. [Terms.Law — ElevenLabs Commercial Rights & Output Ownership (paid own+commercial+perpetual; free = non-commercial + attribution)](https://terms.law/ai-output-rights/elevenlabs/)
11. [Stability AI — License page (Community vs Enterprise; indemnification)](https://stability.ai/license)
12. [Stability AI — Stable Audio (hosted) trained on licensed data / enterprise indemnification](https://stability.ai/news-updates/stability-ai-introduces-stable-audio-25-the-first-audio-model-built-for-enterprise-sound-production-at-scale)
13. [Stable Audio Open 1.0 — LICENSE.md (Stability AI Community License, 2024-07-05; own outputs; $1M cap; NOTICE + "Powered by Stability AI" on model redistribution)](https://huggingface.co/stabilityai/stable-audio-open-1.0/blob/main/LICENSE.md)
14. [Hugging Face — stabilityai/stable-audio-open-1.0 model card (Community License, training-data attribution page)](https://huggingface.co/stabilityai/stable-audio-open-1.0)
15. [Hugging Face — facebook/audiogen-medium model card (CC-BY-NC-4.0 weights)](https://huggingface.co/facebook/audiogen-medium)
16. [GitHub — facebookresearch/audioseal (localized AI-audio watermarking; MIT license for code + model)](https://github.com/facebookresearch/audioseal)
17. [AudioSeal — "Proactive Detection of Voice Cloning with Localized Watermarking" (arXiv:2401.17264)](https://arxiv.org/abs/2401.17264)
18. [Hugging Face — facebook/audioseal (checkpoints)](https://huggingface.co/facebook/audioseal)
19. [C2PA — Content Credentials Technical Specification 2.x (audio as first-class asset; assertions incl. AI use; durable Content Credentials)](https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html)
20. [Sonniss — #GameAudioGDC Bundle License (royalty-free; no raw resale; AI-training prohibited)](https://sonniss.com/gdc-bundle-license/)
21. [Pixabay — Content License / summary (royalty-free; no standalone redistribution)](https://pixabay.com/service/license-summary/)
22. [BBC Sound Effects — Licensing (RemArc: personal/education/research only, non-commercial)](https://sound-effects.bbcrewind.co.uk/licensing)
23. [YouTube Blog — "How we're helping creators disclose altered or synthetic content" (Mar 2024; realistic-media trigger)](https://blog.youtube/news-and-events/disclosing-ai-generated-content/)
24. [YouTube Help — Disclosing altered or synthetic content (Creator Studio field; "How this content was made")](https://support.google.com/youtube/answer/14328491)
25. [TikTok Newsroom — New labels for disclosing AI-generated content](https://newsroom.tiktok.com/en-us/new-labels-for-disclosing-ai-generated-content)
26. [TikTok — Content Credentials / C2PA integration (Jan 2025 auto-labeling of AI media)](https://newsroom.tiktok.com/en-us/partnering-with-our-industry-to-advance-ai-transparency-and-literacy)
27. [Holland & Knight — Tennessee ELVIS Act: first US law covering AI voice clones (2024)](https://www.hklaw.com/en/insights/publications/2024/04/first-of-its-kind-ai-law-addresses-deep-fakes-and-voice-clones)
28. [Congress.gov — NO FAKES Act of 2025 (H.R.2794, 119th Congress) full text](https://www.congress.gov/bill/119th-congress/house-bill/2794/text)
29. [Holland & Knight — Senate Judiciary advances NO FAKES / NIL-and-voice protection (2026)](https://www.hklaw.com/en/insights/publications/2026/06/senate-judiciary-committee-advances-legislation-to-protect-name)
30. [Global Law Experts — How brands like Intel, NBC & MGM trademarked sounds (NBC chimes 1978 first US sound mark)](https://globallawexperts.com/want-to-trademark-a-sound-heres-how-brands-like-intel-nbc-and-mgm-did-it/)
31. [Trademarkia — Why Netflix trademarked "Tudum" (registered 2017; THX, MGM, D'oh! examples)](https://www.trademarkia.com/news/entertainment/netflix-tudum-sound-trademark)
32. [Creative Commons — BY-SA 4.0 legal code (Section 1(a): a sound recording synched with a moving image is always Adapted Material; Section 3(b): ShareAlike)](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en)
</content>
</invoke>
