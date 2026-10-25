# 17 — SFX generation models: verification and update (2026-10-25)

*Delta on foley report 13 (2026-10-03) [1]. Scope: text-to-audio (T2A) and video-to-audio (V2A) models that turn a description into environmental / foley sound effects (footsteps on wood, page turn, clock ticking, a sigh, metal clicks, a sabre sheathed). fal schemas were downloaded from fal's per-endpoint OpenAPI on 2026-10-25; fal catalogue metadata from the unauthenticated `GET https://api.fal.ai/v1/models` [14]; prices come from each model page [3][5][7][9][12][52][53][54]. "unverified" = single secondary source, vendor claim, or inference.*

## 1. What changed since 2026-10-03

1. **Mirelo SFX 2.0 launched 2026-10-14** (fal `mirelo-ai/sfx2.0/text-to-audio`, `/video-to-audio`, `/video-to-video`) [8][9][10][14]. Text-to-SFX up to **600 s**, 1–4 samples, `negative_prompt` (new), returns per-sample `seeds`. Intro price **$0.010/s per sample until 2026-12-13, then $0.015/s** [9]. V2A keeps speech (`preserve_speech`, default true), can return the separated speech, and drops music the video model added (vendor claims) [10][23].
2. **Mirelo SFX 2.0 renamed and removed fields**: `text_prompt` → `prompt`; **`ambience` (seamless loop tile) and `double_output` are gone** from the T2A schema; `upload_audio_bitrate_kbps` added [6][8]. A secondary review says extend/inpaint ops were also dropped (unverified) [24]. foley's `loop` canonical now has one fewer provider on the newest Mirelo model.
3. **Mirelo SFX 1.6 (and 1.5) are being retired**: the fal page says "This endpoint will be deprecated on December 15, 2026. Migrate to SFX 2.0" [7]; 1.6 no longer appears in fal's catalogue search and its metadata record is empty [14]. Price unchanged at $0.01/s [7].
4. **Mirelo terms updated 2026-10-19**: Free users must now "clearly and visibly attribute Mirelo as the sound provider"; the paid training-opt-out toggle does **not** cover organisation API keys (email legal@mirelo.ai); §14 says use via third-party services/API gateways "is not covered by these Terms" [21]. Mirelo pricing page now lists SFX 2.0 minutes per plan (Free 5,000 credits ≈ 8 min, Creator €20 ≈ 40 min, Studio €99 ≈ 200 min, Scale €299, Business €999) [22].
5. **Mirelo's own blind test (vendor claim, unverified)**: 81% preference vs Sony Woosh, 63% vs Kling Foley, 46% vs Sonilo (25 raters, 30 videos), relayed by secondary sites [23][24].
6. **ElevenLabs Sound Effects API, 2026-10-19 changelog**: `output_format` adds `wav_8000`…`wav_48000`; new `enable_logging=false` (Zero Retention, enterprise) [18][17]. 44.1 kHz PCM/WAV needs Pro tier or higher [16]. This supersedes report 13's "fix: map wav to pcm_48000" (now: map to `wav_48000`, mind the tier).
7. **ElevenLabs `model_id` enum now lists `eleven_text_to_sound_v3`** alongside v2 (default still v2) in the live OpenAPI and API reference [16][17]. No announcement, changelog entry or pricing for it found: **unverified / unannounced**. Price still $0.12/min [20].
8. **fal's ElevenLabs wrapper is narrower than the direct API**: `duration_seconds` is **0.5–22** (direct API: 0.5–30), no `model_id` (so v2 only), no `wav_*` formats, but `pcm_*` incl. 44100/48000 are present [4]. Report 13 said 30 s; that is wrong for the fal route.
9. **Sonilo on fal no longer returns a `watermark` field**: output is now `{audio, audios}` (T2A) and `{audio, audios, segments}` (V2A, with per-segment `skipped`/`tags`) [11][13]. Report 13's "only target that reports its own watermark" no longer holds. Price unchanged, and the page now says "**per second of output and per sample**" [12].
10. **Sonilo licensing clarified**: "Audio generated through the API can be used commercially … billed pay-as-you-go … no Pro or Premium plan is required"; paid plans need no attribution; Free/Creator remain non-commercial; whether fal-routed calls count as "API" is still not addressed (unverified) [25].
11. **Stable Audio 3 shipped an official CPU path (TFLite/LiteRT), 2026-10-10**, in the **ungated** HF repo `stabilityai/stable-audio-3-optimized` (anonymous downloads work, rate-limited) [27][28]. Small-SFX int8 DiT `dit_w8a8.tflite` 539 MB, SAME-S decoder w8a8 89 MB, T5Gemma encoder fp16 564 MB (≈1.2 GB total) with "flat ~0.8 GB RAM" for the small DiT [27][28]. This is the first credible route to run a good open SFX model without a GPU and without an HF token. The README is internally inconsistent on whether small DiTs default to `w8a8` or `fp32` [27].
12. **SA3 licensing nuance missed earlier**: the SA3 checkpoints bundle the T5Gemma text encoder "redistributed under the Gemma Terms of Use", including its §3.2 use restrictions [29]. Weights otherwise Stability Community License (free under US $1M revenue; outputs yours; no building competing foundation models) [31]. HF lists SA3 Small-SFX at 0.6B params, GitHub at 433M, fal at 459M (inconsistent counting; unverified which includes the conditioner).
13. **First published SFX evaluation that covers SA3** (SA3 technical report, BBC SFX, 5 s clips, 14-listener MOS): SA3 Medium FAD 0.369 / CLAP 0.369 / OVL 3.65 / REL 3.95; SA3 Small-SFX 0.395 / 0.351 / 3.35 / 3.25; Woosh Flow 0.580 / 0.277 / 3.45 / 3.80; SAO-small 0.500 / 0.277 / 3.10 / 3.55; SAO 0.501 / 0.263 / 2.95 / 3.30; TangoFlux 0.760 / 0.179 / 2.35 / 3.25 [30]. Vendor-run; no ElevenLabs, Mirelo, MOSS or MMAudio in it.
14. **Sony Woosh (missed by report 13; paper 2026-04, release v1.0.0 2026-03-16, v1.0.1 2026-09-10)**: SFX foundation model with T2A (Flow, distilled DFlow) and V2A (VFlow, DVFlow); code MIT/Apache-2.0, **weights CC-BY-NC**; weights on GitHub Releases (no HF token needed), ≈3.4 GB of zips for the T2A path [32][33][34]. A private commercial version trained on Pro Sound Effects and BOOM libraries is not public [34].
15. **ControlFoley weights are CC BY-NC 4.0** (xiaomi-research) [46], yet fal labels `fal-ai/controlfoley` `commercial` [14]: a second MMAudio-style label conflict. Its fal OpenAPI still returns nothing [14].
16. **PrismAudio** (ThinkSound successor, ICLR 2026) lives on a branch of the ThinkSound repo since 2026-03-24; same "research and educational purposes only, commercial use NOT permitted" notice [44]. The ThinkSound HF Space is now PAUSED [50].
17. **fal Terms of Service: correction to report 13.** The ToS (last updated 2026-09-08) does **not** say the customer owns Output Content. It says the customer owns *Customer Input*, that fal does not claim IP in Output Content and gives no originality/non-infringement warranty, that outputs may be similar across users, and (§14) that third-party models "may be subject to additional terms" and their outputs may not be used to train competing models [15].
18. **Replicate HunyuanVideo-Foley now ~$0.058/run** (L40S, up to ~60 s), not ~$0.011 as report 13 had (unverified either way; Replicate's estimate varies with input) [49]. No Stable Audio 3 on Replicate (search, unverified absence).
19. **No new open T2A SFX model of note in Sep/Oct 2026** on HF (search by `text-to-audio` creation date and "sound effect"/"foley" queries): only mirrors/quantisations (MOSS GGUF/MLX, a TinyPine mirror of EzAudio-XL, SA3 Core AI fine-tunes) [35][57]. LTX-2.3 Foley LoRA card updated 2026-10-22 (content of change unverified) [47]. AudioX-Turbo (arXiv 2606.12555) exists as a paper; weights/licence not checked (unverified) [58].
20. **Unchanged** (re-checked): fal SA3 Small-SFX $0.0206/audio, SA3 Medium $0.0376/audio, MMAudio T2A $0.001/s, CassetteAI $0.01/generation, ElevenLabs on fal $0.002/s [3][5][52][53][54]; Stability Community License $1M threshold [31]; MMAudio weights CC-BY-NC (HF updated 2026-02-19) [42]; HunyuanVideo-Foley no 2026 release, XXL 20 GB / XL 16 GB VRAM (8–12 GB with offload) [43].

## 2. Comparison table

Reference host for the "runs on a CPU host?" column: no GPU, 4 vCPU without VNNI/AMX (int8 matmuls are not hardware-accelerated), a couple of GB of free RAM, a few GB of free disk, no Hugging Face token. Cost column is per ~3 s clip, one sample.

| Model | Kind | SFX quality evidence | Code licence | Weights licence | Output terms | Local HW / disk | Runs on a small CPU host? | Hosted routes (cost / 3 s) | Last update |
|---|---|---|---|---|---|---|---|---|---|
| **Stable Audio 3 Small-SFX** | T2A (+a2a, inpaint, outpaint) | SA3 report: FAD 0.395, CLAP 0.351, OVL 3.35, REL 3.25 on BBC SFX [30] | MIT [26] | SA Community + Gemma ToU for T5Gemma [29][31] | Commercial OK under $1M revenue; outputs yours; no competing foundation models [31] | PyTorch: 2.27 GB DiT + 1.18 GB T5Gemma, gated [29]; TFLite: ≈1.2 GB, ~0.8 GB RAM for DiT + encoder, ungated [27][28] | **Borderline**: only the TFLite w8a8 path; peak RAM likely ~1.4–1.6 GB (DiT + T5Gemma) vs ~2 GB free; untested, unverified | fal `fal-ai/stable-audio-3/small/sfx/text-to-audio` **$0.0206/clip** [3]; HF Space `stabilityai/stable-audio-3` (ZeroGPU, running) [50]; no Replicate, no HF Inference Provider | HF 2026-10-06; optimized 2026-10-10; repo 2026-10-11 |
| Stable Audio 3 Medium | T2A | FAD 0.369, CLAP 0.369, OVL 3.65, REL 3.95 (best open in [30]) | MIT | SA Community + Gemma ToU | as above | CUDA + FA2, 5–6.5 GB VRAM; TFLite w8a8 DiT 1.6 GB, 2–4 GB RAM [27] | No (RAM) | fal `fal-ai/stable-audio-3/medium/text-to-audio` $0.0376/clip [54]; HF Inference Provider: fal-ai (needs HF token) [29] | 2026-10-06 |
| Stable Audio 3 Large | T2A | FAD 0.358, CLAP 0.370, OVL 3.60 [30] | — | API only | Stability API terms [1] | — | No | Stability API, 26 credits ≈ $0.26/clip (from [1], not re-checked) | 2026-05 |
| Stable Audio Open 1.0 | T2A | FAD 0.501, OVL 2.95 [30] | MIT (stable-audio-tools) | SA Community | as SA3 | 1.2B params, GPU recommended; gated | No (gated, RAM) | fal `fal-ai/stable-audio` $0.00125/compute-s [1]; Replicate `stackadoc/stable-audio-open-1.0`; many HF Spaces | 2025-06-19 |
| Stable Audio Open Small | T2A | FAD 0.500, OVL 3.10 [30] | MIT | SA Community | as SA3 | 497M, 1.68 GB, CPU/phone-capable; gated [51] | No (gated; no HF token) | HF Spaces only | 2025-05-27 |
| AudioLDM 2 | T2A | not in 2026 evals; superseded | — | CC-BY-NC-SA-4.0 [39] | Non-commercial | ~347M core (+ encoders), diffusers | Possibly slow on CPU, but NC (unverified) | many HF Spaces | 2024-04-16 |
| Tango 2 | T2A | no 2026 evaluation found | — | CC-BY-NC-SA-4.0 [40] | Non-commercial | GPU | No | HF Space `declare-lab/tango2` | 2026-01-17 |
| TangoFlux | T2A | FAD 0.760, CLAP 0.179, OVL 2.35 (worst in [30]) | — | non-commercial (report 13) [1] | Non-commercial | 8–12 GB | No | Replicate `declare-lab/tangoflux`; HF Space (ZeroGPU) | 2025-05-07 |
| AudioGen (Meta) | T2A | no 2026 evaluation found | MIT | CC-BY-NC-4.0 [41] | Non-commercial | ≥16 GB, 16 kHz | No | Replicate `sepal/audiogen` [1] | 2024-03-12 |
| Make-An-Audio 2 | T2A | no evaluation found | MIT | MIT [1] | Commercial OK (model licence) | ~8–12 GB | No | none found | 2024 (stale) |
| EzAudio (L/XL) | T2A | no independent evaluation found | MIT | MIT [37] | Commercial OK by licence; AudioCaps/WavCaps academic data caveat (unverified) [1] | L 2.4 GB / XL 3.5 GB + FLAN-T5-XL, GPU | No | HF Space `OpenSound/EzAudio` (ZeroGPU) | 2026-09-21 |
| MOSS-SoundEffect v2.0 | T2A, 48 kHz, ≤30 s | no evaluation published on card [35] | Apache-2.0 | Apache-2.0 [35] | Commercial OK; training data unstated | ≈11 GB (DiT 5.7 GB + Qwen3 enc 4.1 GB + VAE 1.5 GB), CUDA + torch.compile | No | HF Space `OpenMOSS-Team/MOSS-SoundEffect-v2.0` (ZeroGPU); not on fal | 2026-05-26 |
| Dasheng-AudioGen | T2A (scene: speech+music+SFX), 16 kHz | paper reports metrics (not checked) | Apache-2.0 | Apache-2.0 [36] | Commercial OK | 8.7 GB, CUDA | No | HF Space `mispeech/Dasheng-AudioGen` (cpu-basic hardware listed) [50] | 2026-06-16 |
| AudioX / AudioX-MAF | any-to-audio | no SFX evaluation found | — | CC-BY-NC-4.0 [45] | Non-commercial | GPU | No | HF Spaces | 2026-06-17 |
| **Sony Woosh** (Flow / DFlow) | T2A + V2A | SA3 report: Woosh Flow OVL 3.45, REL 3.80 but FAD 0.580 (band-limited); DFlow 0.06 s latency [30]; Woosh paper claims ≥ SAO/TangoFlux [32] | MIT / Apache-2.0 [33] | **CC-BY-NC** [33] | Non-commercial | ≈3.4 GB zipped (DFlow 1.28 + TextConditioner 1.3 + AE 0.82); `uv sync --extra cpu` exists [33] | No (RAM/disk after unzip; NC anyway) | none found | release v1.0.1 2026-09-10 |
| MMAudio (v2) | V2A + T2A | strong V2A sync (2025 literature) | MIT | **CC-BY-NC-4.0** [42] | Non-commercial (fal label "commercial" conflicts) | ~6 GB fp16 GPU | No | fal `fal-ai/mmaudio-v2/text-to-audio` $0.003 [52], `fal-ai/mmaudio-v2` (V2A) $0.001/s; Replicate `zsxkib/mmaudio` ~$0.0067/run [48]; HF Space (ZeroGPU) | 2026-02-19 |
| ThinkSound / PrismAudio | V2A | no SFX evaluation checked | Apache-2.0 tag | research-only notice [44] | **No commercial use** | GPU | No | fal `fal-ai/thinksound` $0.001/s [1]; Replicate `zsxkib/thinksound`; HF Space PAUSED | PrismAudio 2026-03-24 |
| HunyuanVideo-Foley | V2A (+T2A) | best sync per secondary sources [1] | Tencent | Tencent Hunyuan Community: **not valid in EU, UK, KR** [1] | No outputs to improve other models | XXL 20 GB / XL 16 GB VRAM (8–12 GB offload) [43] | No | fal `fal-ai/hunyuan-video-foley` $0.10 / 10 s [1]; Replicate ~$0.058/run [49]; HF Space (ZeroGPU) | 2025-09-29 |
| ControlFoley | V2A | ACM MM 2026 paper (not checked) | Apache-2.0 | **CC BY-NC 4.0** [46] | Non-commercial (fal label conflicts) | CUDA | No | fal `fal-ai/controlfoley` $0.002/s (schema unpublished) [1][14] | 2026-07/08 |
| LTX-2.3 Foley LoRA | V2A (LoRA on 22B video model) | no evaluation found | — | LTX Community (free < $10M ARR) [1] | Commercial under threshold | 22B base, large GPU | No | fal `fal-ai/ltx-2.3-quality/text-to-audio` (T2A) [1]; HF Space `hugging-apps/ltx-foley-v2a` | 2026-10-22 |
| **ElevenLabs Sound Effects v2** (v3 id unannounced) | T2A, ≤30 s (fal ≤22 s), loop | vendor + many anecdotal reviews; no independent benchmark found | SDK MIT | proprietary | Paid plans commercial; free non-commercial + attribution; no standalone redistribution of raw SFX [1] | — | n/a (hosted) | direct $0.12/min = **$0.006** [20]; fal `fal-ai/elevenlabs/sound-effects/v2` $0.002/s = **$0.006** [5] | API 2026-10-19 |
| **Mirelo SFX 2.0** | T2A ≤600 s + V2A | vendor blind test (V2A only) [23] | SDK MIT | proprietary | Paid commercial; free NC + attribution + watermark; Mirelo may train on your I/O (paid opt-out, not for org API keys) [21] | — | n/a | fal $0.010/s/sample → **$0.03** (1 sample; default 2 = $0.06), $0.045 after 2026-12-13 [9]; Mirelo direct (credits) [22] | 2026-10-14 (fal 10-23) |
| Mirelo SFX 1.6 | T2A + V2A, ambience loops | none independent | SDK MIT | proprietary | as above | — | n/a | fal $0.01/s = $0.03, **deprecated 2026-12-15** [7] | 2026-05 |
| **Sonilo v1.1** | T2A ≤180 s + V2A with `segments` | vendor comparison blog only [55] | — | proprietary; trained on licensed data (vendor) [25] | API output commercial; Free/Creator NC [25]; fal route unverified | — | n/a | fal `sonilo/v1.1/text-to-sound-effects` $0.0018/s/sample = **$0.0054** [12]; V2A $0.009/s [1] | fal 2026-10-18 |
| CassetteAI SFX | T2A ≤30 s | no evaluation found | — | proprietary | vendor terms unverified | — | n/a | fal `cassetteai/sound-effects-generator` $0.01/generation [53] | 2026-04-26 |
| Kling video-to-audio | V2A (3–20 s video) | no evaluation found | — | proprietary | unverified | — | n/a | fal `fal-ai/kling-video/video-to-audio` $0.035/video (from [1], not re-checked) | fal 2026-10-20 |
| Procedural (pyfxr, jsfxr, ZzFX, rFXGen) | synthesis | n/a; not realistic foley | BSD-3 / Unlicense / MIT / zlib | none | unencumbered [1] | KB, ms on CPU | **Yes** | n/a (free) | see [1] |

**Bottom line for a small CPU-only host**: no realistic-foley open model runs comfortably. The only candidate is the **SA3 Small-SFX TFLite w8a8 build** (ungated, ≈1.2 GB disk, DiT ~0.8 GB RAM plus a 0.56 GB encoder), which is borderline on a host with ~2 GB of free RAM, and runs int8 without VNNI acceleration (speed unverified). Everything else either needs a GPU, needs more RAM/disk, is gated behind an HF token, or is non-commercial. HF Inference Providers need an HF token and only SA3 Medium is routed (via fal). HF ZeroGPU Spaces can be called anonymously through `gradio_client`, but anonymous quota is small (exact quota unverified) and they are demos, not a production route.

## 3. fal endpoint schema details (downloaded 2026-10-25)

All four are queue endpoints on `https://queue.fal.run/<endpoint_id>` (submit `POST`, then `GET …/requests/{request_id}/status` and `GET …/requests/{request_id}`), auth header `Authorization: Key $FAL_KEY` [2][4][6][11]. fal labels all four `license_type: commercial` [14], which is a platform label, not a licence grant (see §1 item 17).

### fal-ai/stable-audio-3/small/sfx/text-to-audio [2][3]
- Input (`StableAudio3SmallSfxTextToAudioInput`, required `prompt`): `prompt` (str), `negative_prompt` (str, default ""), `duration` (number 1–120, default 30), `num_inference_steps` (int 1–100, default 8; "distilled checkpoints look good with the default 8"), `guidance_scale` (number 0–25, default 1; "Only effective on base (non-distilled) checkpoints"), `seed` (int or null = random), `output_format` (`mp3` default, `wav`, `flac`, `ogg`, `opus`, `m4a`, `aac`), `bitrate` (str, default `192k`, ignored for wav/flac), `enable_prompt_expansion` (bool, default false; LLM rewrites prompt), `enable_safety_checker` (bool, default true), `sync_mode` (bool, default false; returns a data URI and skips request history).
- Output (`…Output`, required `audio`, `seed`, `prompt`): `{"audio": {"url", "content_type", "file_name", "file_size"}, "seed": int, "prompt": str}`. Audio URL at **`audio.url`**. `prompt` echoes the prompt used (matters when expansion is on).
- Price: "**$0.0206 per audio**" (flat per clip, any duration up to 120 s) [3]. Sibling `/base/` variant is the non-distilled checkpoint where `guidance_scale` matters.
- Note: guidance on distilled SA3 is native `1`; foley's `prompt_influence` mapping must not push it up (report 13 §3).

### fal-ai/elevenlabs/sound-effects/v2 [4][5]
- Input (`ElevenlabsSoundEffectsV2Input`, required `text`): `text` (str), `duration_seconds` (number **0.5–22** or null = auto), `prompt_influence` (number 0–1, default 0.3), `loop` (bool, default false), `output_format` (enum, default `mp3_44100_128`: `mp3_22050_32`, `mp3_44100_{32,64,96,128,192}`, `pcm_{8000,16000,22050,24000,44100,48000}`, `ulaw_8000`, `alaw_8000`, `opus_48000_{32,64,96,128,192}`). No `model_id`, no `wav_*`, no `pcm_32000`, no `mp3_24000_48`.
- Output (required `audio`): `{"audio": {"url", "content_type", "file_name", "file_size"}}`. Audio URL at **`audio.url`** (schema text says "in MP3 format"; container for `pcm_*` on fal unverified). No seed returned (non-reproducible).
- Price: "**$0.002 per second**" [5] (= $0.12/min, same as direct [20]).
- Direct API differences: `duration_seconds` to 30, `model_id` ∈ {`eleven_text_to_sound_v2`, `eleven_text_to_sound_v3`}, `wav_*` formats (2026-10-19), `enable_logging` [16][17][18].

### mirelo-ai/sfx1.6/text-to-audio (deprecated 2026-12-15) [6][7]
- Input (`Sfx16TextToAudioInput`, required `text_prompt`): `text_prompt` (str), `duration` (number 0.1–60, default 10; ≥1 when `ambience`), `num_samples` (int 1–4, default 2), `seed` (int −1…2^64 or null; −1/null = random), `ambience` (bool, default false; "seamlessly loopable ambience tile"), `double_output` (bool, default false; only with `ambience`), `upload_audio_format` (`wav` default, `mp3`, `aac`, `flac`).
- Output (required `model`, `audio`): `{"model": str, "audio": [{"url", …}, …]}` — **a list**; URLs at **`audio[i].url`**. No seeds returned.
- Price: "$0.01 per second" [7]; whether `num_samples` multiplies it is not stated on 1.6 (unverified).
- **Successor `mirelo-ai/sfx2.0/text-to-audio`** [8][9]: required `prompt`; `duration` 0.1–600 (default 30); `num_samples` 1–4 (default 2, "Billed per sample"); `seed`; `negative_prompt` (≤1000 chars); `upload_audio_format` (`wav` default/mp3/aac/flac); `upload_audio_bitrate_kbps` (32–320, mp3/aac). Output `{"model": str, "audio": [File…], "seeds": [int…]}`; URLs at `audio[i].url`. **No `ambience` / `double_output`.** Price "$0.010 per second through December 13, 2026 … then $0.015 per second", "per second of generated audio, per sample" [9].

### sonilo/v1.1/text-to-sound-effects [11][12]
- Input (`V11TextToSoundEffectsInput`, required `prompt`): `prompt` (str), `duration` (number 0.5–180, default 8), `audio_format` (`aac` default, `mp3`, `wav`, `flac`). No seed, no negative prompt, no sample-count knob.
- Output (required `audio`, `audios`): `{"audio": {"url", …}, "audios": [{"url", …}, …]}`. Primary URL at **`audio.url`**; all samples at `audios[i].url`. **No `watermark` field any more.**
- Price: "**$0.0018 per second of output and per sample**" [12].

### fal output ownership (all four)
- fal ToS (2026-09-08): customer owns Customer Input; fal "does not represent, warrant, or covenant that any Output Content will be original, will not infringe … or otherwise entitle Company to any intellectual property rights in any Output Content"; outputs may be the same or similar for other users; Output Content is the customer's Confidential Information; third-party (partner) models "may be subject to additional terms"; outputs of third-party models may not be used to train competing models or to replicate training assets [15].
- So ownership/commercial rights on fal come from the **model owner's terms**, not fal: SA3 → Stability Community License (<$1M) [31]; ElevenLabs → ElevenLabs SFX terms (paid-plan rules; how they map to a fal-billed call is unverified) [1]; Mirelo → its §14 says gateway use "is not covered by these Terms" (so fal-routed rights rest on fal's partner agreement, unpublished; unverified) [21]; Sonilo → "API" output is commercial, fal not mentioned (unverified) [25].

## 4. Recommended hosted route for these foley sounds

- **Default: fal `fal-ai/stable-audio-3/small/sfx/text-to-audio`** at $0.0206 per clip, 44.1 kHz stereo, `seed` echoed (reproducible), `negative_prompt` (e.g. "music, speech, reverb"), best measured open SFX model short of SA3 Medium [30], licence clear for a user under $1M revenue [31]. Ask for `duration` 3–5 s and `output_format: wav`; keep `guidance_scale` 1 and steps 8. Escalate to `/medium/text-to-audio` ($0.0376) for the hard ones.
- **Second opinion / human non-speech (the sigh): ElevenLabs v2 via fal** ($0.006 per 3 s; ≤22 s on fal) — cheapest high-quality proprietary option, no seed. Then **Sonilo** ($0.0054 per 3 s per sample, licensed training data, commercial API output) as a third candidate. Generate 2–3 candidates per sound across backends and pick by ear or by CLAP score.
- **Avoid for this job**: Mirelo 1.6 (retiring 2026-12-15); Mirelo 2.0 T2A is 5–10x the cost per 3 s and lost the loop flag (use it for V2A against picture instead); MMAudio, ThinkSound, ControlFoley, Woosh, TangoFlux, AudioGen (non-commercial weights); HunyuanVideo-Foley (licence void in EU/UK/KR).
- **Offline fallback on a CPU-only host**: SA3 Small-SFX TFLite w8a8 (try once with nothing else running; RAM is the risk), else procedural sfxr-family for clicks/ticks only.

## 5. Hands-on: the fal backends foley gained from this report (2026-10-25)

foley now reaches six fal endpoints as generate sources (`foley/sources/fal/`, executed through `falaw`): `fal_stable_audio_3`, `fal_stable_audio_3_medium`, `fal_mirelo` (SFX 2.0), `fal_elevenlabs`, `fal_sonilo`, `fal_mmaudio`. Seven film-foley prompts (footsteps on wood, pacing, a page turn, a musket put into a hand, a sabre handed over, a clock ticking, a sleepy sigh), 1.5 to 8 s each, were generated on three of them (Stable Audio 3 Small-SFX, ElevenLabs v2, Sonilo): 21 clips for $0.235 in total, every one decodable and admitted by foley's QC (one Stable Audio 3 clip needed foley's automatic 20 ms fade and peak attenuation). Measured facts worth keeping:

- Stable Audio 3 Small-SFX on fal echoes the seed it used (so a take is reproducible) and returns 44.1 kHz stereo WAV when asked; its output is quiet (peaks around -20 dBFS on a clock tick), so level it in the mix rather than judging it raw.
- ElevenLabs on fal returns `pcm_44100` as a **stereo WAV with a RIFF header** (`content_type: audio/L16; rate=44100; channels=2`). That answers, for the fal route, the channel-layout question foley#95 asks of the direct API.
- Sonilo returns `audio` plus `audios`; Mirelo SFX 2.0 returns `audio` as a list and `seeds` as a list, and bills per sample (foley sends `num_samples=1`).
- Durations came back as asked (within 0.05 s) on all three.

## REFERENCES

1. foley report 13 — *SFX generation targets: the delta since July 2026* (2026-10-03), `foley/misc/docs/research/13-generation-targets-2026-10.md`
2. [fal — OpenAPI, fal-ai/stable-audio-3/small/sfx/text-to-audio](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/stable-audio-3/small/sfx/text-to-audio)
3. [fal — Stable Audio 3 Small SFX text-to-audio (model page, price)](https://fal.ai/models/fal-ai/stable-audio-3/small/sfx/text-to-audio)
4. [fal — OpenAPI, fal-ai/elevenlabs/sound-effects/v2](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/elevenlabs/sound-effects/v2)
5. [fal — ElevenLabs Sound Effects V2 (model page, price)](https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2)
6. [fal — OpenAPI, mirelo-ai/sfx1.6/text-to-audio](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx1.6/text-to-audio)
7. [fal — Mirelo SFX 1.6 text-to-audio (deprecation notice, price)](https://fal.ai/models/mirelo-ai/sfx1.6/text-to-audio)
8. [fal — OpenAPI, mirelo-ai/sfx2.0/text-to-audio](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx2.0/text-to-audio)
9. [fal — Mirelo SFX 2.0 text-to-audio (model page, intro pricing)](https://fal.ai/models/mirelo-ai/sfx2.0/text-to-audio)
10. [fal — OpenAPI, mirelo-ai/sfx2.0/video-to-audio](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx2.0/video-to-audio)
11. [fal — OpenAPI, sonilo/v1.1/text-to-sound-effects](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=sonilo/v1.1/text-to-sound-effects)
12. [fal — Sonilo v1.1 text-to-sound-effects (model page, price)](https://fal.ai/models/sonilo/v1.1/text-to-sound-effects)
13. [fal — OpenAPI, sonilo/v1.1/video-to-sound-effects](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=sonilo/v1.1/video-to-sound-effects)
14. [fal Platform API — model catalogue `GET /v1/models` (category and endpoint queries, 2026-10-25)](https://api.fal.ai/v1/models?category=text-to-audio)
15. [fal — Terms of Service (last updated 8 Sep 2026; §4, §6, §7, §14)](https://fal.ai/legal/terms-of-service)
16. [ElevenLabs — Create sound effect (API reference)](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)
17. [ElevenLabs — OpenAPI spec (`/v1/sound-generation`, `SFXModelId`)](https://api.elevenlabs.io/openapi.json)
18. [ElevenLabs — Changelog (19 Oct 2026: WAV output, enable_logging for Sound Effects)](https://elevenlabs.io/docs/changelog)
19. [ElevenLabs — Sound effects capability overview](https://elevenlabs.io/docs/overview/capabilities/sound-effects)
20. [ElevenLabs — API pricing](https://elevenlabs.io/pricing/api)
21. [Mirelo — Terms of service (last updated 2026-10-19)](https://mirelo.ai/terms)
22. [Mirelo — Pricing](https://mirelo.ai/pricing)
23. [Morphic — Mirelo SFX 2 model page (secondary; relays Mirelo launch claims)](https://morphic.com/resources/models/mirelo-sfx-2)
24. [aiidelist — Mirelo SFX 2.0 review (secondary)](https://aiidelist.com/blog/mirelo-sfx-2-0-review)
25. [Sonilo — Licensing](https://sonilo.com/licensing)
26. [GitHub — Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3)
27. [GitHub — Stable Audio 3 TFLite/LiteRT CPU README (optimized/tflite)](https://github.com/Stability-AI/stable-audio-3/blob/main/optimized/tflite/README.md)
28. [Hugging Face — stabilityai/stable-audio-3-optimized (ungated; TFLite/ONNX/MLX/TensorRT files)](https://huggingface.co/stabilityai/stable-audio-3-optimized)
29. [Hugging Face — stabilityai/stable-audio-3-small-sfx (gated; Gemma terms note)](https://huggingface.co/stabilityai/stable-audio-3-small-sfx)
30. [Stable Audio 3 technical report, arXiv:2605.17991 (§5.3 SFX, Table 5; Tables 13–14 memory/CPU)](https://arxiv.org/html/2605.17991)
31. [Stability AI — License tiers / Community License](https://stability.ai/license)
32. [Woosh: A Sound Effects Foundation Model, arXiv:2604.01929](https://arxiv.org/abs/2604.01929)
33. [GitHub — SonyResearch/Woosh (code MIT/Apache-2.0, weights CC-BY-NC, releases)](https://github.com/SonyResearch/Woosh)
34. [Mix — Sony AI announces SFX generation model Woosh (19 May 2026)](https://www.mixonline.com/post-and-broadcast/sony-ai-announces-sfx-generation-model-woosh)
35. [Hugging Face — OpenMOSS-Team/MOSS-SoundEffect-v2.0](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0)
36. [Hugging Face — mispeech/Dasheng-AudioGen](https://huggingface.co/mispeech/Dasheng-AudioGen)
37. [Hugging Face — OpenSound/EzAudio](https://huggingface.co/OpenSound/EzAudio)
38. [Hugging Face — declare-lab/TangoFlux](https://huggingface.co/declare-lab/TangoFlux)
39. [Hugging Face — cvssp/audioldm2 (CC-BY-NC-SA-4.0)](https://huggingface.co/cvssp/audioldm2)
40. [Hugging Face — declare-lab/tango2 (CC-BY-NC-SA-4.0)](https://huggingface.co/declare-lab/tango2)
41. [Hugging Face — facebook/audiogen-medium (CC-BY-NC-4.0)](https://huggingface.co/facebook/audiogen-medium)
42. [Hugging Face — hkchengrex/MMAudio (CC-BY-NC-4.0)](https://huggingface.co/hkchengrex/MMAudio)
43. [GitHub — Tencent-Hunyuan/HunyuanVideo-Foley (variants, VRAM)](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley)
44. [GitHub — FunAudioLLM/ThinkSound (PrismAudio branch; research-only notice)](https://github.com/FunAudioLLM/ThinkSound)
45. [Hugging Face — HKUSTAudio/AudioX (CC-BY-NC-4.0)](https://huggingface.co/HKUSTAudio/AudioX)
46. [GitHub — xiaomi-research/controlfoley (code Apache-2.0, weights CC BY-NC 4.0)](https://github.com/xiaomi-research/controlfoley)
47. [Hugging Face — Lightricks/LTX-2.3-22b-LoRA-Foley-V2A](https://huggingface.co/Lightricks/LTX-2.3-22b-LoRA-Foley-V2A)
48. [Replicate — zsxkib/mmaudio](https://replicate.com/zsxkib/mmaudio)
49. [Replicate — tencent/hunyuanvideo-foley](https://replicate.com/tencent/hunyuanvideo-foley)
50. [Hugging Face — Spaces runtime API (e.g. stabilityai/stable-audio-3), queried 2026-10-25](https://huggingface.co/api/spaces/stabilityai/stable-audio-3/runtime)
51. [Hugging Face — stabilityai/stable-audio-open-small](https://huggingface.co/stabilityai/stable-audio-open-small)
52. [fal — MMAudio V2 text-to-audio (price)](https://fal.ai/models/fal-ai/mmaudio-v2/text-to-audio)
53. [fal — CassetteAI sound effects generator (price)](https://fal.ai/models/cassetteai/sound-effects-generator)
54. [fal — Stable Audio 3 Medium text-to-audio (price)](https://fal.ai/models/fal-ai/stable-audio-3/medium/text-to-audio)
55. [Sonilo — Sonilo vs ElevenLabs vs Mirelo SFX (vendor comparison; context only)](https://sonilo.com/blog/comparisons/sonilo-vs-elevenlabs-vs-mirelo-sfx)
56. [GitHub — bytedance/Make-An-Audio-2](https://github.com/bytedance/Make-An-Audio-2)
57. [Hugging Face — pinecoresystems/TinyPine-Sound-Effects (EzAudio-XL mirror, MIT)](https://huggingface.co/pinecoresystems/TinyPine-Sound-Effects)
58. [AudioX-Turbo, arXiv:2606.12555](https://arxiv.org/abs/2606.12555)
