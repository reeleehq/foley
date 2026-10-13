# Generative-AI SFX Generation: Local Models and Hosted APIs

**Research brief for `foley`** — a unified façade for sourcing, indexing, searching, and *generating* sound effects (SFX) to weave into AI-generated narrations. This report covers the **generation** leg (the sibling of `arioso`'s music generation): text-to-audio / text-to-sound-effect systems, both **local/open-weight** models and **hosted APIs**. For each option it records the interface, cost, latency, max duration, hardware needs, and — critically for a product that ships generated sound — the **licensing of the generated output**.

*Compiled 2026-07 from primary sources (model cards, official API docs, papers). Model sizes, licenses, and download stats verified against the Hugging Face Hub. Where a spec is version- or date-sensitive it is flagged inline.*

---

## Abstract

Text-to-SFX generation splits cleanly into two deployment modes. **Hosted APIs** (ElevenLabs Sound Effects [1], Stability's Stable Audio API [4], plus resellers fal.ai [7,8] and Replicate [10,11]) trade a per-call fee for zero local hardware, clean REST/SDK ergonomics, and — for the commercial ones — legally clean, often indemnified output. **Local/open models** (AudioGen [12], Stable Audio Open 1.0 / Small [14,16], AudioLDM(2) [19,21], Tango(2)/TangoFlux [24,27], Make-An-Audio [28], Auffusion [30], GenAU [31], and the video-conditioned MMAudio [33]) trade GPU VRAM and setup for zero marginal cost, offline operation, and full control — but most ship under **non-commercial** research licenses (CC-BY-NC-*), a decisive constraint for a product.

The single most important licensing fact for `foley`: nearly all high-quality *open* SFX models are **CC-BY-NC** (non-commercial weights) — the notable exceptions being the **Stable Audio Open** family (Stability AI Community License, free commercial use under **US $1M annual revenue** [36,38]) and the original **Make-An-Audio (MIT)** [28]. Among *hosted* options, **ElevenLabs** and **Stability's Stable Audio** grant commercial rights to output on paid tiers, with Stability additionally offering fully-licensed-training-data indemnification [4,5].

**Bottom line for foley:** default **LOCAL** adapter → **Stable Audio Open 1.0** (best open SFX quality, 47 s stereo, commercially usable under the $1M threshold), with **Stable Audio Open Small** as the fast/low-VRAM tier. Default **HOSTED** adapter → **ElevenLabs Sound Effects** (purpose-built for SFX, the cleanest parameter surface — `text` / `duration_seconds` / `prompt_influence` / `loop` — and unambiguous commercial licensing). Details and adapter mapping in the final section.

---

## Comparison Table

| Model / API | Access | Max duration | Quality (SFX) | VRAM / hardware | License (weights → output) | How to invoke |
|---|---|---|---|---|---|---|
| **ElevenLabs Sound Effects** [1,2] | Hosted API | 30 s (0.5–30) | High, SFX-tuned | none (cloud) | Proprietary → commercial on paid plans | `POST /v1/sound-generation`; `elevenlabs` SDK |
| **Stability Stable Audio 2.5 / 3.0** [4,6] | Hosted API | ~3 min (2.5) / 6 min (3.0) | High, music+SFX | none (cloud) | Proprietary → commercial, indemnified (enterprise) | `platform.stability.ai` REST; also on fal/Replicate |
| **fal.ai** (Stable Audio Open, SA 2.5, MMAudio) [7,8,9] | Hosted API | 30 s (open) / longer (2.5) | Model-dependent | none (cloud) | Follows underlying model | `@fal-ai/client` / `fal_client` (Python) |
| **Replicate** (stable-audio-open, audiogen) [10,11] | Hosted API | 47 s / ~10 s | Model-dependent | none (cloud) | Follows underlying model | `replicate` SDK; HTTP predictions |
| **AudioGen medium** [12,13] | Local (audiocraft) | ~10 s (default), extendable | Good pure-SFX | ≥16 GB GPU | **CC-BY-NC-4.0** → non-commercial | `AudioGen.get_pretrained('facebook/audiogen-medium')` |
| **Stable Audio Open 1.0** [14,15] | Local (stable-audio-tools / diffusers) | **47 s** | **High**, stereo 44.1 kHz | ~8–12 GB GPU | **Stability Community License** → commercial < $1M rev | `StableAudioPipeline` (diffusers), gated |
| **Stable Audio Open Small** [16,17,18] | Local | ~11 s | High, fast | Runs on ARM CPU / small GPU | **Stability Community License** → commercial < $1M rev | `stable-audio-tools`; 75 ms on H100 |
| **AudioLDM** [21,22] | Local (diffusers) | ~10 s (variable) | Moderate | ~4–8 GB GPU | **CC-BY-NC-SA-4.0** → non-commercial | `AudioLDMPipeline` (diffusers) |
| **AudioLDM2** [19,20,23] | Local (diffusers) | variable (audio+music) | Good | ~8–14 GB GPU | **CC-BY-NC-SA-4.0** → non-commercial | `AudioLDM2Pipeline` (diffusers) |
| **Tango / Tango 2** [24,25,26] | Local (transformers) | ~10 s | Good, DPO-aligned (T2) | ~10–16 GB GPU | **CC-BY-NC-SA-4.0** → non-commercial | `tango` repo / `AutoModel` |
| **TangoFlux** [27] | Local | up to **30 s** | High, fast (rectified flow) | ~8–12 GB GPU | Non-commercial (research) — verify repo | `tangoflux` package |
| **Make-An-Audio (1)** [28] | Local | ~10 s | Moderate | ~8 GB GPU | **MIT** → permissive/commercial | `Make-An-Audio` repo |
| **Make-An-Audio 2** [29] | Local | ~10 s | Better temporal control | ~8–12 GB GPU | Repo license (verify) | `Make-An-Audio-2` repo |
| **Auffusion** [30] | Local (diffusers-based) | ~10 s | Good (SD-derived) | ~8 GB GPU | **CC-BY-NC-SA-4.0** → non-commercial | `auffusion` repo |
| **GenAU** [31,32] | Local | ~10 s | High (scaled DiT, 1.25B) | ≥16 GB GPU (large) | Research (Snap) — verify repo | `snap-research/GenAU` repo |
| **MMAudio** (video→audio + text) [33,34,35] | Local | **8 s** (default) | High, A/V-synced | **~6 GB GPU** (fp16) | **CC-BY-NC-4.0** → non-commercial | `pip install -e .`; `demo.py` |

---

## Part 1 — Hosted Text-to-SFX APIs

### 1.1 ElevenLabs Sound Effects  *(recommended default hosted adapter)*

The only major hosted API **purpose-built for sound effects** (not music). Its parameter surface is exactly the vocabulary `foley` wants to standardize on. [1,2,3]

- **Endpoint:** `POST https://api.elevenlabs.io/v1/sound-generation`
- **Parameters** [1]:
  - `text` (string, required) — the sound description.
  - `model_id` (default `eleven_text_to_sound_v2`).
  - `duration_seconds` (number | null, default **null** = model auto-picks; range **0.5–30 s**). Auto-duration costs a flat fee; fixed duration is billed per second.
  - `prompt_influence` (number | null, default **0.3**, range **0–1**) — higher = closer prompt adherence, **less** variety. This is the "guidance"/prompt-strength knob.
  - `loop` (bool, default false; v2 only) — generate a seamless loopable clip (great for ambience beds under narration).
  - `output_format` (default `mp3_44100_128`) — MP3 (22.05–44.1 kHz, 32–192 kbps), PCM (8–48 kHz), Opus (48 kHz), and telephony µ-law/A-law 8 kHz.
- **Max duration:** 30 s. **Latency:** typically a few seconds.
- **Cost** [2]: **$0.12 per minute** of audio via API; in credit terms, **200 credits** per auto-duration generation or **40 credits/second** for fixed duration.
- **Output licensing:** commercial use of generated SFX is granted on paid plans (ElevenLabs terms); free tier is attribution/non-commercial.

```python
# pip install elevenlabs
from elevenlabs import ElevenLabs

client = ElevenLabs(api_key="...")  # or ELEVENLABS_API_KEY env var
audio = client.text_to_sound_effects.convert(
    text="heavy wooden door creaking open in a stone dungeon",
    duration_seconds=4.0,  # None => model decides
    prompt_influence=0.5,  # 0..1  (guidance)
    loop=False,
    output_format="mp3_44100_128",
)
# `audio` is an iterator of bytes; write to file
with open("creak.mp3", "wb") as f:
    for chunk in audio:
        f.write(chunk)
```

### 1.2 Stability AI — Stable Audio (2.5 / 3.0) API

Stability's *hosted* model targets **music and SFX** and is the pick when **legally clean, indemnified output** matters (trained on fully licensed data). [4,5,6]

- **Access:** `platform.stability.ai` REST API; also resold on **fal**, **Replicate**, and **ComfyUI**. [4]
- **Pricing:** credit-based, **1 credit = $0.01**; text-to-audio ≈ **20 credits (~$0.20)** per generation on the developer platform [6]. Enterprise volume discounts available.
- **Max duration:** Stable Audio 2.5 up to **~3 minutes**; Stable Audio 3.0 (2026) up to **6 minutes**, with open weights for the smaller variants. [4]
- **Latency:** a few seconds (2.5 is enterprise-tuned for fast inference).
- **Output licensing:** commercially safe; **legal indemnification** under the Enterprise license; training data fully licensed. [4,5]

```python
import requests

resp = requests.post(
    "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio",
    headers={"authorization": "Bearer sk-...", "accept": "audio/*"},
    files={"none": ""},
    data={
        "prompt": "distant thunder rolling over a quiet field",
        "duration": 10,
        "output_format": "mp3",
    },
)
open("thunder.mp3", "wb").write(resp.content)
```

### 1.3 fal.ai — reseller for open + Stability models

fal hosts several text-to-audio models behind one client, pay-as-you-go (no subscription). Useful as a *managed* path to open models without provisioning GPUs. [7,8,9]

- **Endpoints:** `fal-ai/stable-audio` (Stable Audio Open, text-to-audio) [8]; `fal-ai/stable-audio-25/text-to-audio` [7]; `fal-ai/mmaudio-v2/text-to-audio` [9]; plus community SFX generators.
- **Params (Stable Audio Open)** [8]: `prompt` (required), `seconds_total` (default 30), `seconds_start`, `steps` (default 100). Response: `{ audio: { url, content_type, file_name, file_size } }`.
- **Cost:** per-compute-second; MMAudio v2 ≈ **$0.001/sec**; Stable Audio Open is inexpensive (near-free tier reported). [9]
- **Max duration:** 30 s (open); longer for SA 2.5.
- **Output licensing:** inherits the underlying model's license (Stable Audio Open → Community License; MMAudio → CC-BY-NC).

```python
# pip install fal-client   (needs FAL_KEY)
import fal_client

result = fal_client.subscribe(
    "fal-ai/stable-audio",
    arguments={
        "prompt": "glass shattering on tile floor",
        "seconds_total": 5,
        "steps": 100,
    },
)
print(result["audio"]["url"])
```

### 1.4 Replicate — reseller for open models

Container-hosted community/official models, billed by run time. [10,11]

- **Models:** `stackadoc/stable-audio-open-1.0` (Stable Audio Open 1.0, up to **47 s**, runs on **L40S**, ≈ **$0.14/run**, ~ up to ~145 s predict time) [10]; `sepal/audiogen` (Meta AudioGen) [11].
- **Output licensing:** inherits the underlying model license (AudioGen → CC-BY-NC-4.0; Stable Audio Open → Community License).

```python
# pip install replicate  (needs REPLICATE_API_TOKEN)
import replicate

out = replicate.run(
    "stackadoc/stable-audio-open-1.0:<version>",
    input={"prompt": "rain on a tin roof", "seconds_total": 12, "steps": 100},
)
print(out)  # URL to generated audio
```

---

## Part 2 — Local / Open Models

### 2.1 Meta AudioGen (`facebook/audiogen-medium`) [12,13]

- **What:** 1.5B autoregressive LM over discrete EnCodec tokens; the canonical **pure-SFX** open model (music is MusicGen's job). Mono 16 kHz.
- **Size / HW:** 1.5B params, **≥16 GB GPU** for the medium model. Downloads 250K+ (HF).
- **Duration:** default ~**10 s**; `set_generation_params(duration=…)` extends via continuation.
- **License:** **CC-BY-NC-4.0** — weights and output **non-commercial** only.

```python
# pip install audiocraft
import torchaudio
from audiocraft.models import AudioGen
from audiocraft.data.audio import audio_write

model = AudioGen.get_pretrained("facebook/audiogen-medium")
model.set_generation_params(
    duration=5
)  # seconds; also top_k, top_p, temperature, cfg_coef
wav = model.generate(["dog barking", "footsteps in a corridor"])
for i, one in enumerate(wav):
    audio_write(f"sfx_{i}", one.cpu(), model.sample_rate, strategy="loudness")
```

### 2.2 Stable Audio Open 1.0 [14,15]  *(recommended default local adapter)*

- **What:** 1.21B latent-diffusion DiT; **stereo 44.1 kHz**, the highest-quality *open* SFX/short-sample model. Trained largely on Creative-Commons Freesound/FMA data. Gated on HF (accept terms).
- **Size / HW:** 1213.4M params; runs comfortably in **~8–12 GB VRAM**.
- **Duration:** up to **47 s** — long enough for ambience beds and layered foley.
- **License:** **Stability AI Community License** — free for research and for **commercial use up to US $1M annual revenue**; above that requires an Enterprise license. Users own their outputs. [36,38]

```python
# pip install "diffusers>=0.27" transformers torch soundfile
import torch, soundfile as sf
from diffusers import StableAudioPipeline

pipe = StableAudioPipeline.from_pretrained(
    "stabilityai/stable-audio-open-1.0", torch_dtype=torch.float16
).to("cuda")
audio = pipe(
    prompt="a creaking ship's hull with waves lapping",
    negative_prompt="music, speech",
    num_inference_steps=100,
    audio_end_in_s=10.0,  # duration control
).audios[0]
sf.write("ship.wav", audio.T.float().cpu().numpy(), pipe.vae.sampling_rate)
```

### 2.3 Stable Audio Open Small [16,17,18]  *(fast / low-VRAM tier)*

- **What:** distilled-free, **ARC (Adversarial Relativistic-Contrastive) post-trained** small sibling. Generates **11 s** of 44.1 kHz stereo; **75 ms on an H100**, or **<8 s on a smartphone ARM CPU** (via Arm KleidiAI). Ideal for real-time/edge or bulk generation.
- **Size:** ~**341M** generator (HF card lists 497M incl. text encoder). Downloads 43K+ (HF).
- **License:** Stability AI Community License (same $1M commercial threshold).
- **Invoke:** via `stable-audio-tools` (config + ckpt); diffusers support tracks the family.

### 2.4 AudioLDM & AudioLDM2 [19,20,21,22,23]

- **AudioLDM** (`cvssp/audioldm-s-full-v2`, 185M): CLAP-conditioned latent diffusion; ~10 s; light (~4–8 GB). Moderate quality; first-class `diffusers` support.
- **AudioLDM2** (`cvssp/audioldm2`, 347M): unified **audio + music + speech**; better fidelity; `AudioLDM2Pipeline`. Exposes `negative_prompt`, `num_inference_steps`, `audio_length_in_s`, `num_waveforms_per_prompt`.
- **License (both):** **CC-BY-NC-SA-4.0** — non-commercial, share-alike.

```python
# pip install diffusers transformers torch scipy
import torch, scipy.io.wavfile as wav
from diffusers import AudioLDM2Pipeline

pipe = AudioLDM2Pipeline.from_pretrained(
    "cvssp/audioldm2", torch_dtype=torch.float16
).to("cuda")
audio = pipe(
    "a hammer hitting a nail, echoing in a workshop",
    negative_prompt="low quality",
    num_inference_steps=200,
    audio_length_in_s=5.0,
).audios[0]
wav.write("hammer.wav", 16000, audio)
```

### 2.5 Tango / Tango 2 / TangoFlux [24,25,26,27]

- **Tango** (FLAN-T5-conditioned latent diffusion) and **Tango 2** (`declare-lab/tango2-full`): Tango 2 adds **DPO alignment** on the `audio-alpaca` preference set, improving prompt faithfulness / event presence. ~10 s, `cc-by-nc-sa-4.0`.
- **TangoFlux** (`declare-lab/TangoFlux`): rectified-flow transformer, **up to 30 s**, notably fast; strong CLAP/FAD. Research use — verify commercial terms in repo.
- **License:** Tango/Tango 2 **CC-BY-NC-SA-4.0**; TangoFlux research (non-commercial) — confirm before shipping.

### 2.6 Make-An-Audio (1 / 2) [28,29]

- **Make-An-Audio (ICML'23):** prompt-enhanced diffusion; **MIT license** — the rare permissively-licensed open SFX model (commercial OK), though quality trails Stable Audio Open.
- **Make-An-Audio 2:** improved **temporal/event ordering** and structured captions; check the repo's license before commercial use.

### 2.7 Auffusion [30]

- **What:** adapts a Stable-Diffusion text-to-image backbone to spectrograms (`auffusion/auffusion`), inheriting strong text-conditioning and cross-attention control. Good quality, ~10 s.
- **License:** **CC-BY-NC-SA-4.0** — non-commercial.

### 2.8 GenAU [31,32]

- **What:** Snap Research's scaled transformer T2A (up to **1.25B** params) trained on **AutoReCap-XL** (47M+ clips) with the AutoCap captioner; strong ambient-sound quality and state-of-the-art FAD/CLAP at release. Code, checkpoints, and dataset public.
- **HW:** ≥16 GB GPU for the large model. **License:** Snap research terms — verify commercial eligibility in the repo before shipping.

### 2.9 MMAudio (video-conditioned + text) [33,34,35]

- **What:** multimodal flow-matching model for **high-quality, temporally-synced video-to-audio** — and it also does **text-to-audio** if you omit `--video`. The right tool when foley must line up with picture.
- **Variants:** `small_16k`, `small_44k`, `medium_44k`, `large_44k_v2` (default). Output **44.1 kHz**, `.flac`.
- **Duration:** **8 s** default. **HW:** only **~6 GB GPU** in fp16 — the lightest strong model here.
- **License:** **CC-BY-NC-4.0** — non-commercial.

```bash
pip install torch torchvision torchaudio
git clone https://github.com/hkchengrex/MMAudio && cd MMAudio && pip install -e .
# text-to-audio (omit --video):
python demo.py --duration=8 --prompt "sword clash and metal ringing"
```

---

## Part 3 — SFX vs Music, and Conditioning Controls

**Text-to-SFX vs text-to-music.** They are trained on different corpora and optimized for different structure:
- **SFX / "sound"** models (AudioGen, AudioLDM, Tango, Make-An-Audio, Stable Audio Open, GenAU, MMAudio) target **non-musical events** — impacts, ambiences, foley, whooshes — where **temporal onset accuracy** and **event realism** matter more than harmony or beat. Corpora: AudioSet, AudioCaps, WavCaps, Freesound.
- **Music** models (MusicGen, Stable Audio's music mode, Stable Audio 2.5/3.0) optimize **rhythm, tonality, and long-range structure** (bars, BPM, key). Corpora: licensed music catalogs.
- Several backbones straddle both (**AudioLDM2**, **Stable Audio Open**, **Stable Audio 2.5**). For `foley`'s narration-SFX use case, **prefer SFX-tuned models and steer away from music** via negative prompts ("music, melody, singing").

**Conditioning controls foley should expose (unified vocabulary):**
- **Duration** — `duration_seconds` (ElevenLabs), `audio_end_in_s`/`audio_length_in_s` (diffusers), `seconds_total` (Stable Audio / fal), `set_generation_params(duration=…)` (AudioGen), `--duration` (MMAudio).
- **Prompt influence / guidance** — `prompt_influence` 0–1 (ElevenLabs) ≈ `guidance_scale`/`cfg_coef` in diffusion/AR models: higher = closer adherence, lower diversity.
- **Negative prompts** — supported by diffusion models (Stable Audio Open, AudioLDM2, Tango, Auffusion) to *exclude* content (e.g. suppress music/speech); **not** offered by ElevenLabs or AudioGen.
- **Steps** (`num_inference_steps` / `steps`) — quality↔latency trade for diffusion/flow models.
- **Seed** — reproducibility (all local diffusion models; some hosted).
- **Loop** — seamless looping (ElevenLabs `loop`; others need manual crossfade).

---

## Recommendations for foley

`foley` should mirror `arioso`'s façade: **one `generate()` call**, **config-driven plugin adapters**, a **unified parameter vocabulary translated per backend**, and **zero required core deps** with **lazy per-backend optional-deps**.

### Default LOCAL model → **Stable Audio Open 1.0**
The best-quality *open* SFX model that is **actually commercially usable** (Community License, free under $1M revenue), 47 s stereo 44.1 kHz, first-class `diffusers` (`StableAudioPipeline`) support with `negative_prompt` + duration + guidance controls. Pair it with **Stable Audio Open Small** as a `stable-audio-open:small` fast/low-VRAM/edge tier (same license). If a foley user needs *picture-synced* SFX, offer **MMAudio** as an opt-in adapter (note its CC-BY-NC / non-commercial output). Keep **AudioGen** available for pure-SFX experimentation but flag it **non-commercial**.

### Default HOSTED API → **ElevenLabs Sound Effects**
Purpose-built for SFX, the cleanest parameter surface (`text`, `duration_seconds`, `prompt_influence`, `loop`, `output_format`), predictable **$0.12/min** cost, ≤30 s, and unambiguous commercial output rights on paid plans. Offer **Stability Stable Audio (2.5)** as the alternate hosted adapter when a user needs **longer** clips or **indemnified, fully-licensed** output, and **fal.ai / Replicate** as managed paths to the open models for users who want open-model behavior without a GPU.

### Adapter shape (arioso-style)
Define one `SfxGenerationBackend` protocol and per-backend adapters selected by config string:

```python
# foley/generation — sketch
from typing import Protocol, Optional


class SfxGenerationBackend(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        duration: Optional[float] = None,  # seconds; None => backend default/auto
        prompt_influence: Optional[float] = None,  # 0..1 unified "guidance"; None => native default (foley#70)
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        steps: Optional[int] = None,
        output_format: str = "wav",
    ) -> "AudioClip": ...
```

Each adapter **translates the unified vocabulary** to its backend:

| foley param | ElevenLabs | Stable Audio Open (diffusers) | AudioGen | Stability API / fal |
|---|---|---|---|---|
| `duration` | `duration_seconds` | `audio_end_in_s` | `set_generation_params(duration=)` | `duration` / `seconds_total` |
| `prompt_influence` | `prompt_influence` | `guidance_scale` | `cfg_coef` | (fixed / n/a) |
| `negative_prompt` | — (drop) | `negative_prompt` | — (drop) | `negative_prompt` (2.5) |
| `steps` | — | `num_inference_steps` | (n/a) | `steps` |
| `seed` | — | `generator=torch.Generator(seed)` | seed arg | `seed` |

**Lazy optional-deps** (per `arioso`): `elevenlabs`; `stable-audio-tools` **or** `diffusers`+`torch`+`soundfile`; `audiocraft`; `fal-client`; `replicate` — imported only inside the adapter that needs them, so the core `foley` install stays dependency-free. Config drives selection, e.g. `foley.generate(prompt, backend="stable-audio-open-1.0")` or `backend="elevenlabs"`.

**Licensing guardrail (product-critical):** `foley` should carry a per-backend `commercial_ok` flag in its adapter registry and surface it, since the majority of open SFX models are **CC-BY-NC**. Commercial-safe defaults are **Stable Audio Open** (local, <$1M), **Make-An-Audio 1 / MIT** (local), and **ElevenLabs / Stability** (hosted). Non-commercial-only: **AudioGen, AudioLDM(2), Tango(2), Auffusion, MMAudio** (and, pending repo confirmation, **TangoFlux / GenAU**).

---

## REFERENCES

1. [ElevenLabs — Create Sound Effect (API reference)](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)
2. [ElevenLabs — How much does it cost to generate sound effects?](https://help.elevenlabs.io/hc/en-us/articles/25735337678481-How-much-does-it-cost-to-generate-sound-effects)
3. [ElevenLabs — Sound effects (capabilities / product guide)](https://elevenlabs.io/docs/overview/capabilities/sound-effects)
4. [Stability AI — Introducing Stable Audio 2.5 (enterprise sound production)](https://stability.ai/news-updates/stability-ai-introduces-stable-audio-25-the-first-audio-model-built-for-enterprise-sound-production-at-scale)
5. [Stability AI — License](https://stability.ai/license)
6. [Stability AI — Developer Platform pricing](https://platform.stability.ai/pricing)
7. [fal.ai — Stable Audio 2.5 (Text to Audio)](https://fal.ai/models/fal-ai/stable-audio-25/text-to-audio)
8. [fal.ai — Stable Audio Open (Text to Audio) API docs](https://fal.ai/models/fal-ai/stable-audio/api)
9. [fal.ai — MMAudio V2 (Text to Audio)](https://fal.ai/models/fal-ai/mmaudio-v2/text-to-audio)
10. [Replicate — stackadoc/stable-audio-open-1.0](https://replicate.com/stackadoc/stable-audio-open-1.0)
11. [Replicate — sepal/audiogen](https://replicate.com/sepal/audiogen)
12. [Hugging Face — facebook/audiogen-medium (model card)](https://huggingface.co/facebook/audiogen-medium)
13. [AudioGen: Textually Guided Audio Generation (arXiv:2209.15352)](https://arxiv.org/abs/2209.15352)
14. [Hugging Face — stabilityai/stable-audio-open-1.0 (model card)](https://huggingface.co/stabilityai/stable-audio-open-1.0)
15. [Stable Audio Open (arXiv:2407.14358)](https://arxiv.org/abs/2407.14358)
16. [Hugging Face — stabilityai/stable-audio-open-small (model card)](https://huggingface.co/stabilityai/stable-audio-open-small)
17. [Fast Text-to-Audio Generation with Adversarial Post-Training (arXiv:2505.08175)](https://arxiv.org/abs/2505.08175)
18. [MarkTechPost — Stability AI introduces ARC post-training and Stable Audio Open Small](https://www.marktechpost.com/2025/05/15/stability-ai-introduces-adversarial-relativistic-contrastive-arc-post-training-and-stable-audio-open-small-a-distillation-free-breakthrough-for-fast-diverse-and-efficient-text-to-audio-generation/)
19. [Hugging Face — cvssp/audioldm2 (model card)](https://huggingface.co/cvssp/audioldm2)
20. [AudioLDM 2 (arXiv:2308.05734)](https://arxiv.org/abs/2308.05734)
21. [Hugging Face — cvssp/audioldm-s-full-v2 (model card)](https://huggingface.co/cvssp/audioldm-s-full-v2)
22. [AudioLDM (arXiv:2301.12503)](https://arxiv.org/abs/2301.12503)
23. [Hugging Face Diffusers — AudioLDM2 pipeline docs](https://huggingface.co/docs/diffusers/main/en/api/pipelines/audioldm2)
24. [Hugging Face — declare-lab/tango2-full (model card)](https://huggingface.co/declare-lab/tango2-full)
25. [Tango 2: Aligning Diffusion-based T2A with DPO (arXiv:2404.09956)](https://arxiv.org/abs/2404.09956)
26. [Hugging Face — declare-lab/tango (model card)](https://huggingface.co/declare-lab/tango)
27. [Hugging Face — declare-lab/TangoFlux (model card) / arXiv:2412.21037](https://huggingface.co/declare-lab/TangoFlux)
28. [GitHub — Text-to-Audio/Make-An-Audio (ICML'23, MIT)](https://github.com/Text-to-Audio/Make-An-Audio)
29. [GitHub — Text-to-Audio/Make-An-Audio-2](https://github.com/Text-to-Audio/Make-An-Audio-2)
30. [Hugging Face — auffusion/auffusion (model card) / arXiv:2401.01044](https://huggingface.co/auffusion/auffusion)
31. [GitHub — snap-research/GenAU](https://github.com/snap-research/GenAU)
32. [Taming Data and Transformers for Audio Generation (GenAU, arXiv:2406.19388)](https://arxiv.org/abs/2406.19388)
33. [Hugging Face — hkchengrex/MMAudio (model card)](https://huggingface.co/hkchengrex/MMAudio)
34. [GitHub — hkchengrex/MMAudio](https://github.com/hkchengrex/MMAudio)
35. [MMAudio: Taming Multimodal Joint Training for High-Quality Video-to-Audio (arXiv:2412.15322)](https://arxiv.org/abs/2412.15322)
36. [Hugging Face — Stable Audio Open 1.0 LICENSE.md (Stability AI Community License)](https://huggingface.co/stabilityai/stable-audio-open-1.0/blob/main/LICENSE.md)
37. [GitHub — facebookresearch/audiocraft (AudioGen docs)](https://github.com/facebookresearch/audiocraft/blob/main/docs/AUDIOGEN.md)
38. [The Decoder — Stability AI launches Stable Audio 3.0 (open weights, commercial threshold)](https://the-decoder.com/stability-ai-launches-stable-audio-3-0-with-up-to-six-minute-tracks-and-open-weights/)
