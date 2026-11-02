# Generation fidelity and the audio-LM judge

Tier-2 evaluation backends that need more than foley's own environment: reference FAD from Microsoft's [fadtk](https://github.com/microsoft/fadtk) and reference KAD from [kadtk](https://github.com/YoonjinXD/kadtk), each run as a separate program, Meta's per-clip [Audiobox Aesthetics](https://github.com/facebookresearch/audiobox-aesthetics) scores, run the same way, and the Qwen2-Audio "does this clip contain {event}?" judge. All are for nightly or pre-release comparisons, never a per-PR gate; Audiobox Aesthetics can also be recorded on each generated clip when asked.

| Backend | What it scores | How it runs | Install | Download |
|---|---|---|---|---|
| `foley.eval.generation_fidelity` (default) | FAD or KAD between two embedding sets, pure numpy | in process | nothing | whatever your embedder needs |
| `foley.eval.FadtkFidelity` | FAD with fadtk's own models, loading and statistics, comparable with published fadtk numbers | `python -I toolkit_driver.py` in a fadtk virtualenv | its own venv (below) | about 90 MB for the default `encodec-emb` |
| `foley.eval.KadtkFidelity` | KAD with kadtk's own models, loading and kernel, comparable with published kadtk numbers | the same driver in a kadtk virtualenv | its own venv (below) | about 90 MB for the default `encodec-emb` |
| `foley.eval.AudioboxAesthetics` | per clip: content enjoyment (CE), content usefulness (CU), production complexity (PC), production quality (PQ), about 1 to 10 | the same driver in an `audiobox_aesthetics` virtualenv | its own venv (below) | about 415 MB (`facebook/audiobox-aesthetics`) |
| `foley.agent.AudioLMJudge` | P(yes) that a clip contains the wanted event (AQAScore) | in process | `pip install 'foley[fit]'` | about 15 GB (Qwen2-Audio-7B-Instruct, bf16) on first use |
| `foley.eval.Pam` | per clip, no reference: PAM, the probability that a clip is "clear and clean" rather than "noisy and with artifacts" (0 to 1) | `python -I pam_driver.py` in an `msclap` virtualenv | its own venv (below) | 690 MB (`microsoft/msclap` `CLAP_weights_2023.pth`) plus 3 MB of GPT-2 tokenizer files |

## Reference FAD with fadtk

fadtk 1.1 pins `numpy<2` and pulls torch, torchvision, laion-clap and msclap, so it gets its own virtualenv and foley runs it there, as it runs aeneas:

```bash
uv venv ~/venvs/fadtk --python 3.11
uv pip install --python ~/venvs/fadtk/bin/python fadtk torchcodec
```

`torchcodec` is needed because torchaudio 2.9 and later load audio through it (it uses your system ffmpeg). Then:

```python
from foley.eval import FadtkFidelity

fad = FadtkFidelity(python="~/venvs/fadtk/bin/python")  # or set FOLEY_FADTK_PYTHON
result = fad(reference_wavs, generated_wavs, sr=48000)
result.value  # the FAD
result.stamp  # FidelityStamp(embedding='encodec-emb', toolkit='fadtk', version='1.1.0', n_ref=600, n_gen=600)
```

With neither `python=` nor `$FOLEY_FADTK_PYTHON` it raises with the install line above (foley's own interpreter cannot hold fadtk). Clips are `(frames,)` or `(frames, channels)` arrays, mixed to mono; a channel-first `(2, N)` array is refused rather than read as two-sample clips. `n_ref` / `n_gen` in the stamp are the embedding frames FAD was computed over, not the clip counts. Each set needs more frames than the embedding has dimensions (128 for `encodec-emb`, which makes 75 frames per second), or the covariance is singular and the number meaningless, so a set that short raises `ValueError`.

Each call writes the two sets as WAVs to a temporary directory, runs fadtk's embedding and scoring on them in that interpreter, and reads back its score. `model=` picks the embedding (`encodec-emb`, `encodec-emb-48k`, `vggish`, `clap-laion-audio`, `clap-laion-music`, `clap-2023`; add any other fadtk loader with `models={"name": ("LoaderClass", args)}`). The default is `encodec-emb` because its weights are the smallest; for SFX, `clap-laion-audio` is the domain-matched choice and downloads about 1.9 GB. Weights go to torch's cache, so pass `env={"TORCH_HOME": ...}` (added to this process's environment) to choose where. `workers=` sets fadtk's embedding processes, `timeout=` bounds a run.

foley does not call `python -m fadtk`: that command builds every model fadtk knows before choosing one, and the two CLAP constructors download their checkpoints (about 2.5 GB) even when you asked for EnCodec. The driver builds only the model you name.

fadtk's FAD is over embedding frames (every frame of every clip), so it is not the number `generation_fidelity` gives with one vector per clip. Fed the same frames, foley's numpy `frechet_distance` agrees with fadtk to about 1e-5 relative; the remainder is fadtk taking each clip's mean in float16. Numbers are only comparable within one embedding, toolkit and version, which is why the stamp carries all three.

Both toolkits run through one mechanism, `foley.eval.external_fidelity.ExternalFidelity`: writing the sets, the clip-layout guards, the driver (`foley/eval/toolkit_driver.py`, which builds the one model named, whichever toolkit) and the stamped result. A toolkit adapter only names its package, metric, models, interpreter variable and install line, and how many frames a set needs. Its base, `foley.eval.external_toolkit.ExternalToolkit` (the interpreter and its install hint, the failure hints, running the driver on a JSON spec), is shared with the per-clip Audiobox Aesthetics scorer below; the driver's `spec["task"]` says which computation it runs (`fidelity` or `aesthetics`).

## Reference KAD with kadtk

kadtk 1.1 (a fork of fadtk by the KAD paper's authors) needs Python below 3.12, `numpy<2`, `torch<2.6` and `transformers<4.47`, and pulls tensorflow; its venv is about 2.2 GB:

```bash
uv venv ~/venvs/kadtk --python 3.11 --managed-python
uv pip install --python ~/venvs/kadtk/bin/python kadtk torchaudio==2.5.1
```

`--managed-python` because kadtk imports `turtle`, so the interpreter needs Tk, which uv's Python builds have and Homebrew's often lack. `torchaudio==2.5.1` because kadtk resolves torch 2.5.1 but would leave the newest torchaudio, whose native library does not load against it. Then:

```python
from foley.eval import KadtkFidelity

kad = KadtkFidelity(python="~/venvs/kadtk/bin/python")  # or set FOLEY_KADTK_PYTHON
result = kad(reference_wavs, generated_wavs, sr=48000)
result.value  # kadtk's KAD
result.stamp  # FidelityStamp(embedding='encodec-emb', toolkit='kadtk', version='1.1.0', n_ref=120, n_gen=120)
result.params  # {'bandwidth': 2.4, 'scale': 100}
```

Arguments, guards and errors are fadtk's (`model=`, `models=`, `workers=`, `env=`, `timeout=`, a missing interpreter, channel-first clips), plus `bandwidth=` (the RBF bandwidth) and `device=` (where kadtk sums the kernels, default `"cpu"`). `model=` also offers the PANNs models (`panns-cnn14-32k`, `panns-cnn14-16k`, `panns-wavegram-logmel`). KAD has no covariance, so a set needs only two embedding frames, not more frames than dimensions; below 100 frames a set (`warn_frames=`, default `KADTK_WARN_FRAMES`) it warns, because the value is then mostly noise. kadtk's EnCodec embedding is pooled to one frame per second of audio (a trailing partial second is dropped), and kadtk crashes on a clip shorter than a second, so such a clip is refused with `ValueError` before anything runs; for `encodec-emb-48k`, which kadtk embeds in whole 1 s segments, a clip must also be a whole number of seconds. These rules are `KADTK_CLIP_RULES` (override with `clip_rule=`); if kadtk crashes anyway, the error says why.

KAD is the unbiased MMD² times 100, so for two sets from one distribution it is centred on 0 and negative about half the time. Values near 0 mean "indistinguishable at this sample size", not "identical", and with few frames they are noise: two sets of the same noise gave -1.49 at 8 frames a set and -0.37 at 50, against about 100 for tones vs noise.

kadtk's number is not the one `kernel_audio_distance` gives by default, for two reasons. kadtk reports the MMD² times 100. Its default bandwidth is torch's median (the lower of the two middle values) of the pairwise distances between the generated set's frames, where foley's default pools both sets. The bandwidth used and the scale are in `result.params`. Because the default bandwidth comes from the generated set, two generators scored against one reference are on different kernels; pass the first run's `params["bandwidth"]` as `bandwidth=` to the second to compare them. Fed kadtk's own frames with that bandwidth, `100 * kernel_audio_distance(ref, gen, bandwidth=...)` agrees with kadtk to about 5e-5 relative; the remainder is kadtk's float32 arithmetic.

## Per-clip quality with Audiobox Aesthetics

[Audiobox Aesthetics](https://github.com/facebookresearch/audiobox-aesthetics) (Tjandra et al. 2025, [arXiv:2502.05139](https://arxiv.org/abs/2502.05139)) is a WavLM encoder with four regression heads that rates one clip of speech, music or sound, with no reference set and no prompt, on four axes of about 1 to 10: content enjoyment (CE), content usefulness (CU), production complexity (PC) and production quality (PQ). The package brings its own torch and torchaudio, so it gets a virtualenv (about 700 MB, plus 415 MB of weights):

```bash
uv venv ~/venvs/aes --python 3.11
uv pip install --python ~/venvs/aes/bin/python audiobox_aesthetics requests
```

`requests` because the package imports it without declaring it, and `huggingface_hub` 1.0 and later no longer bring it in. Then:

```python
from foley.eval import AudioboxAesthetics

aes = AudioboxAesthetics(python="~/venvs/aes/bin/python")  # or set FOLEY_AES_PYTHON
tone, noise, silence = aes([tone_wav, noise_wav, silence_wav], sr=48000)
tone.axes      # {'CE': 2.47, 'CU': 5.78, 'PC': 1.74, 'PQ': 6.02}
tone.to_dict() # the axes plus model='facebook/audiobox-aesthetics', toolkit, version='0.0.4'
```

Those are real scores (version 0.0.4, 3 s clips at 48 kHz): a 440 Hz sine at 0.5 scored CE 2.47, CU 5.78, PC 1.74, PQ 6.02; white noise at 0.3 RMS CE 2.14, CU 4.42, PC 1.97, PQ 4.83; digital silence CE 3.44, CU 6.62, PC 1.70, PQ 7.00; the sine as a stereo pair the same as mono. Silence scoring the highest PQ is the point to remember: the model rates how a clip sounds, it does not detect faults, so Tier-0 QC (`foley.qc`) stays the gate for silent, clipped or broken audio.

The first call downloads the weights from Hugging Face into the toolkit's `HF_HOME` (pass `env={"HF_HOME": ...}` to choose where), or `checkpoint=` names a local `checkpoint.pt`. Loading the model takes a few seconds, once per call, so score many clips in one call; `batch_size=` (default 10) sets the clips a forward pass. Clips are `(frames,)` or `(frames, channels)` arrays, mixed to mono; channel-first arrays are refused, as for fadtk. A clip shorter than 25 ms (one WavLM encoder frame, its 400-sample receptive field at the model's 16 kHz; `min_seconds=`) or with a NaN or infinite sample raises `ValueError` before anything runs: the toolkit pads every clip to a 10 s window, so a shorter clip would still get numbers, but they would describe the padding. With neither `python=` nor `$FOLEY_AES_PYTHON` it raises with the install line. A run is abandoned after `timeout=` seconds (default `AES_TIMEOUT_S`, 300, room for the first run's download; `None` waits forever).

### On generated clips

`foley.generate(prompt, ..., aesthetics=True)` scores each stored clip and records the verdict in `sound.qc['aesthetics']` and the notes, next to `qc['prompt_match']`. It is a record, not a gate: the default `None` skips it (each scored clip starts the model in its own process, so `foley.variations` loads it once per take), and when it runs, nothing is quarantined. The clip's content credential is written before it is scored, so a slow or failed score never leaves a stored clip without one. `aesthetics=True` (or an `AudioboxAesthetics` instance) without a reachable interpreter raises before anything is paid for, as `watermark=True` does. A generation that duplicates a stored clip scores that clip if it has no score yet (no verdict, or `unchecked`), and otherwise notes that its recorded verdict stands. `True` uses `AudioboxAesthetics()` with its interpreter from `$FOLEY_AES_PYTHON`; pass a configured instance to set the interpreter, checkpoint or floors:

```python
aes = AudioboxAesthetics(python="~/venvs/aes/bin/python", floors={"PQ": 5.0})
cand = foley.generate("a wooden door creak", aesthetics=aes)
cand.sound.qc["aesthetics"]
# {'status': 'ok', 'CE': ..., 'CU': ..., 'PC': ..., 'PQ': ..., 'model': ..., 'toolkit': ..., 'version': ..., 'floors': {'PQ': 5.0}}
```

The status is `scored` without floors, `ok` at or above every floor, `low` (with the axes `below` them, flagged in the notes as "listen before using it") under one, or `unchecked` with the reason when the scorer cannot run (a clip too short, a timeout, a crash, a scorer answering anything but one score with all four axes): never a silent pass, and never an exception out of `generate`. The record is published with the clip, so the reason is short: the exception type, the first and last line of its message, local paths replaced by `<path>` (`foley.obs.redact.redact_paths`: the home, temp, interpreter and venv directories whole, spaces and all, then any other POSIX, drive, UNC or `file:` path), never the command or the program's full output. A non-finite axis is stored as `null` (strict JSON) and counts as below any floor on it. No floor is calibrated for SFX yet, so none is set by default. Any callable `(wavs, *, sr) -> [AestheticsScore]` with an optional `floors` attribute can stand in for the scorer (the tests pass one).

It is wired on `generate` rather than on ingest because it is a generation-quality signal: a retrieved library sound was already chosen by a person, while a generated clip is what a model happened to produce, the same reason `prompt_match` runs there.

Licences: the code is CC-BY-4.0, with parts from microsoft/unilm under MIT. Meta's README states no separate licence for the weights; the Hugging Face repository that holds them (`facebook/audiobox-aesthetics`) is tagged `cc-by-4.0`. The scores are metadata about a clip, not part of it, so they do not change the clip's own licence.

## The Qwen2-Audio judge

```python
from foley.agent import AudioLMJudge
from foley.eval import run_fit_eval

report = run_fit_eval(fit_judge=AudioLMJudge(), level="listen")
```

The first judgement loads `Qwen/Qwen2-Audio-7B-Instruct` with `dtype="auto"` and `device_map="auto"` (change with `load_kwargs=`, or another checkpoint with `model=`). Each clip is resampled to the model's 16 kHz, put through the chat template with the question "Does this audio contain {event}? Answer strictly yes or no.", and P(yes) is read from one forward pass: the softmax mass of the next token on "Yes" and "yes", over "Yes", "yes", "No" and "no" (each must be a single token for the tokenizer, or it raises; change the spellings with `qwen2_audio_pipeline(..., answers=)`). `load_kwargs` other than the model-only ones (`dtype`, `device_map`, ...) also go to the processor, so a `revision=` pins both. Whisper's feature extractor hears only the first 30 s of a clip, so a longer clip warns. A match is P(yes) at or above `tau` (default 0.5). It is never picked by default: pass it as `fit_judge=`. For tests, or another audio-LM, pass `pipeline=` a function `(prompt, wav, sr) -> {"p_yes": float}`.

## Per-clip quality with PAM

[PAM](https://github.com/soham97/PAM) (Deshmukh et al., "PAM: Prompting Audio-Language Models for Audio Quality Assessment", Interspeech 2024, [arXiv:2402.00282](https://arxiv.org/abs/2402.00282)) scores one clip with no reference set and no task-specific model. It asks Microsoft's CLAP 2023 audio-language model which of two antonym prompts fits the clip better, and the score is the softmax probability of the first: "the sound is clear and clean." against "the sound is noisy and with artifacts." (`PAM_PROMPTS`). It runs from 0 to 1, higher is cleaner.

PAM itself is a research repository (pinned 2023 requirements, no package). Its model and config are the ones the [`msclap`](https://pypi.org/project/msclap/) package ships, so foley installs `msclap` in its own virtualenv (it pins `numpy<2` and brings its own torch, about 1 GB installed) and runs PAM's scoring there, in `foley/eval/pam_driver.py`:

```bash
uv venv ~/venvs/pam --python 3.11
uv pip install --python ~/venvs/pam/bin/python msclap
```

```python
from foley.eval import Pam

pam = Pam(python="~/venvs/pam/bin/python")  # or set FOLEY_PAM_PYTHON
tone, noise, silence = pam([tone_wav, noise_wav, silence_wav], sr=48000)
tone.score      # 0.68
tone.segments   # (0.68,): one score per 7 s window
tone.to_dict()  # {'pam': 0.68, 'segments': [...], 'model': 'microsoft/msclap:CLAP_weights_2023.pth', 'toolkit': 'msclap', 'version': '1.3.4'}
```

Real scores (msclap 1.3.4, CPU, clips at 48 kHz): a 3 s 440 Hz sine at 0.5 scored 0.680, and the same sine as a stereo pair the same; a 10 s sine 0.733 (two windows, 0.733 and 0.733); the 3 s sine plus white noise at 0.03 RMS 0.416; white noise at 0.3 RMS 0.043; clicks four times a second 0.071; digital silence 0.354. Like Audiobox Aesthetics, PAM rates how a clip sounds and is not a fault detector (silence lands in the middle), so Tier-0 QC (`foley.qc`) stays the gate for silent or broken audio.

How it scores, as the reference does: each clip is mixed to mono, resampled to 44.1 kHz with the same torchaudio resampler, and cut into the model's 7 s windows. A clip shorter than 7 s is tiled to one window; a longer one keeps its whole windows plus the last 7 s when a part is left over. Each window is scored, and the clip's score is the mean (`segments` keeps them). On the three 3 s clips above, the driver and the reference `PAM.evaluate` agreed to 1e-6. An empty clip, a NaN or infinite sample, or a channel-first array raises `ValueError` before anything runs; a very short clip is scored, but its number describes the tiling. Loading the model takes about 20 s, once per call, so score many clips in one call; `batch_size=` (default 10) is windows a forward pass, `device=` where the model runs.

One deviation from msclap that does not change the numbers: msclap builds its GPT-2 text encoder with `AutoModel.from_pretrained("gpt2")`, a 548 MB download, then overwrites every one of those weights from the CLAP checkpoint, which carries all of them (`caption_encoder.base.*`, 137M parameters). The driver builds GPT-2 from its config instead and refuses to run if the checkpoint leaves any parameter unset. The first call downloads the checkpoint (690 MB) and GPT-2's tokenizer files (3 MB) into the interpreter's `HF_HOME` (pass `env={"HF_HOME": ...}` to choose where), or `checkpoint=` names a local `CLAP_weights_2023.pth`. `prompts=` takes another pair (the clean one first), which gives a PAM-style score, not PAM's.

`Pam` is an eval-side scorer for any set of clips; it is not wired into `foley.generate`. Recording it on generated clips, the way `generate(aesthetics=)` records Audiobox Aesthetics, is a follow-up once that hook lands, and `Pam` can then share the `ExternalToolkit` base it mirrors (same attribute names and interpreter guards).

Licences: PAM's code and msclap's are MIT. The CLAP weights are tagged MS-PL (Microsoft Public License) on their Hugging Face repository, `microsoft/msclap`; the GPT-2 tokenizer files are MIT. The scores are metadata about a clip, not part of it, so they do not change the clip's own licence.
