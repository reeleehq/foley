# Generation fidelity and the audio-LM judge

Two Tier-2 evaluation backends that need more than foley's own environment: reference FAD from Microsoft's [fadtk](https://github.com/microsoft/fadtk), run as a separate program, and the Qwen2-Audio "does this clip contain {event}?" judge. Both are for nightly or pre-release comparisons, never a per-PR gate.

| Backend | What it scores | How it runs | Install | Download |
|---|---|---|---|---|
| `foley.eval.generation_fidelity` (default) | FAD or KAD between two embedding sets, pure numpy | in process | nothing | whatever your embedder needs |
| `foley.eval.FadtkFidelity` | FAD with fadtk's own models, loading and statistics, comparable with published fadtk numbers | `python -I fadtk_driver.py` in a fadtk virtualenv | its own venv (below) | about 90 MB for the default `encodec-emb` |
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

fad = FadtkFidelity(python="~/venvs/fadtk/bin/python")
result = fad(reference_wavs, generated_wavs, sr=48000)
result.value   # the FAD
result.stamp   # FidelityStamp(embedding='encodec-emb', toolkit='fadtk', version='1.1.0', n_ref=..., n_gen=...)
```

Each call writes the two sets as WAVs to a temporary directory, runs fadtk's embedding and scoring on them in that interpreter, and reads back its score. `model=` picks the embedding (`encodec-emb`, `encodec-emb-48k`, `vggish`, `clap-laion-audio`, `clap-laion-music`, `clap-2023`; add any other fadtk loader with `models={"name": ("LoaderClass", args)}`). The default is `encodec-emb` because its weights are the smallest; for SFX, `clap-laion-audio` is the domain-matched choice and downloads about 1.9 GB. Weights go to torch's cache, so pass `env={**os.environ, "TORCH_HOME": ...}` to choose where. `workers=` sets fadtk's embedding processes, `timeout=` bounds a run.

foley does not call `python -m fadtk`: that command builds every model fadtk knows before choosing one, and the two CLAP constructors download their checkpoints (about 2.5 GB) even when you asked for EnCodec. The driver builds only the model you name.

fadtk's FAD is over embedding frames (every frame of every clip), so it is not the number `generation_fidelity` gives with one vector per clip. Fed the same frames, foley's numpy `frechet_distance` agrees with fadtk to about 1e-5 relative; the remainder is fadtk taking each clip's mean in float16. Numbers are only comparable within one embedding, toolkit and version, which is why the stamp carries all three.

## The Qwen2-Audio judge

```python
from foley.agent import AudioLMJudge
from foley.eval import run_fit_eval

report = run_fit_eval(fit_judge=AudioLMJudge(), level="listen")
```

The first judgement loads `Qwen/Qwen2-Audio-7B-Instruct` with `dtype="auto"` and `device_map="auto"` (change with `load_kwargs=`, or another checkpoint with `model=`). Each clip is resampled to the model's 16 kHz, put through the chat template with the question "Does this audio contain {event}? Answer strictly yes or no.", and P(yes) is read from one forward pass as the softmax of the next-token logits over "Yes" and "No". A match is P(yes) at or above `tau` (default 0.5). It is never picked by default: pass it as `fit_judge=`. For tests, or another audio-LM, pass `pipeline=` a function `(prompt, wav, sr) -> {"p_yes": float}`.
