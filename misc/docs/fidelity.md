# Generation fidelity and the audio-LM judge

Tier-2 evaluation backends that need more than foley's own environment: reference FAD from Microsoft's [fadtk](https://github.com/microsoft/fadtk) and reference KAD from [kadtk](https://github.com/YoonjinXD/kadtk), each run as a separate program, and the Qwen2-Audio "does this clip contain {event}?" judge. All are for nightly or pre-release comparisons, never a per-PR gate.

| Backend | What it scores | How it runs | Install | Download |
|---|---|---|---|---|
| `foley.eval.generation_fidelity` (default) | FAD or KAD between two embedding sets, pure numpy | in process | nothing | whatever your embedder needs |
| `foley.eval.FadtkFidelity` | FAD with fadtk's own models, loading and statistics, comparable with published fadtk numbers | `python -I toolkit_driver.py` in a fadtk virtualenv | its own venv (below) | about 90 MB for the default `encodec-emb` |
| `foley.eval.KadtkFidelity` | KAD with kadtk's own models, loading and kernel, comparable with published kadtk numbers | the same driver in a kadtk virtualenv | its own venv (below) | about 90 MB for the default `encodec-emb` |
| `foley.agent.AudioLMJudge` | P(yes) that a clip contains the wanted event (AQAScore) | in process | `pip install 'foley[fit]'` | about 15 GB (Qwen2-Audio-7B-Instruct, bf16) on first use |

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

Both toolkits run through one mechanism, `foley.eval.external_fidelity.ExternalFidelity`: writing the sets, the clip-layout and interpreter guards, the driver (`foley/eval/toolkit_driver.py`, which builds the one model named, whichever toolkit) and the stamped result. A toolkit adapter only names its package, metric, models, interpreter variable and install line, and how many frames a set needs.

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

## The Qwen2-Audio judge

```python
from foley.agent import AudioLMJudge
from foley.eval import run_fit_eval

report = run_fit_eval(fit_judge=AudioLMJudge(), level="listen")
```

The first judgement loads `Qwen/Qwen2-Audio-7B-Instruct` with `dtype="auto"` and `device_map="auto"` (change with `load_kwargs=`, or another checkpoint with `model=`). Each clip is resampled to the model's 16 kHz, put through the chat template with the question "Does this audio contain {event}? Answer strictly yes or no.", and P(yes) is read from one forward pass: the softmax mass of the next token on "Yes" and "yes", over "Yes", "yes", "No" and "no" (each must be a single token for the tokenizer, or it raises; change the spellings with `qwen2_audio_pipeline(..., answers=)`). `load_kwargs` other than the model-only ones (`dtype`, `device_map`, ...) also go to the processor, so a `revision=` pins both. Whisper's feature extractor hears only the first 30 s of a clip, so a longer clip warns. A match is P(yes) at or above `tau` (default 0.5). It is never picked by default: pass it as `fit_judge=`. For tests, or another audio-LM, pass `pipeline=` a function `(prompt, wav, sr) -> {"p_yes": float}`.
