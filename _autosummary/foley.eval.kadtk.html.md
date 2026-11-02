# foley.eval.kadtk

Reference KAD from `kadtk`, run in its own interpreter (#262).

[`foley.eval.fidelity.kernel_audio_distance()`](foley.eval.fidelity.html.md#foley.eval.fidelity.kernel_audio_distance) is the KAD math (unbiased RBF MMD²)
in pure numpy. [kadtk](https://github.com/YoonjinXD/kadtk) is the reference toolkit
of the KAD paper, a fork of fadtk with the same embedding models; version 1.1 needs
Python < 3.12, `numpy<2`, `torch<2.6` and `transformers<4.47`, so it cannot share
foley’s environment. [`KadtkFidelity`](#foley.eval.kadtk.KadtkFidelity) runs it through
[`ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity) exactly as
[`FadtkFidelity`](foley.eval.fadtk.html.md#foley.eval.fadtk.FadtkFidelity) runs fadtk, and stamps `toolkit='kadtk'`.

```default
kad = KadtkFidelity(python="~/venvs/kadtk/bin/python")
result = kad(reference_wavs, generated_wavs, sr=48000)
result.value   # kadtk's KAD: the unbiased MMD² times 100, so it can be negative
result.params  # {'bandwidth': ..., 'scale': 100}
```

Two conventions differ from [`kernel_audio_distance()`](foley.eval.fidelity.html.md#foley.eval.fidelity.kernel_audio_distance), so
the numbers agree only after accounting for them: kadtk reports the MMD² \*\*times
100\*\*, and its default bandwidth is torch’s (lower) median of the pairwise distances
between the **generated** set’s frames (foley’s numpy default pools both sets). The
bandwidth used is returned in `result.params`; pass it as `bandwidth=` to score a
second generator against the same reference on the same kernel. kadtk’s EnCodec
embeddings are pooled to one frame per second of audio, and kadtk crashes on a clip
shorter than that, so such clips are refused here ([`KADTK_CLIP_RULES`](#foley.eval.kadtk.KADTK_CLIP_RULES)).
Install: `misc/docs/fidelity.md`.

### Module Attributes

| [`KADTK_MODELS`](#foley.eval.kadtk.KADTK_MODELS)     | kadtk embedding models by kadtk's name → (loader class in `kadtk.model_loader`, its constructor args): fadtk's, plus the PANNs models.   |
|-------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| [`KADTK_CLIP_RULES`](#foley.eval.kadtk.KADTK_CLIP_RULES) | kadtk model → [`ClipRule`](#foley.eval.kadtk.ClipRule); a model not listed accepts any clip.                            |

### Classes

| [`ClipRule`](#foley.eval.kadtk.ClipRule)([min_seconds, whole_seconds])      | What a clip must be for kadtk to embed it with a given model.   |
|----------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`KadtkFidelity`](#foley.eval.kadtk.KadtkFidelity)(\*[, bandwidth, device, ...]) | Set-level KAD computed by `kadtk` in a separate interpreter.    |

### *class* foley.eval.kadtk.ClipRule(min_seconds=0.0, whole_seconds=False)

Bases: [`NamedTuple`](https://docs.python.org/3/library/typing.html#typing.NamedTuple)

What a clip must be for kadtk to embed it with a given model.

`min_seconds`: the shortest clip. `whole_seconds`: the length must be a whole
number of pooling windows (kadtk embeds EnCodec 48 kHz per 1 s segment and pools
each, so a partial last segment crashes it like a short clip).

#### min_seconds *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Alias for field number 0

#### whole_seconds *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Alias for field number 1

### foley.eval.kadtk.KADTK_CLIP_RULES *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [ClipRule](#foley.eval.kadtk.ClipRule)]* *= {'encodec-emb': (1.0, False), 'encodec-emb-48k': (1.0, True)}*

kadtk model → [`ClipRule`](#foley.eval.kadtk.ClipRule); a model not listed accepts any clip.

### foley.eval.kadtk.KADTK_MODELS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)]]* *= {'clap-2023': ('CLAPModel', ('2023',)), 'clap-laion-audio': ('CLAPLaionModel', ('audio',)), 'clap-laion-music': ('CLAPLaionModel', ('music',)), 'encodec-emb': ('EncodecEmbModel', ('24k',)), 'encodec-emb-48k': ('EncodecEmbModel', ('48k',)), 'panns-cnn14-16k': ('PANNsModel', ('cnn14-16k',)), 'panns-cnn14-32k': ('PANNsModel', ('cnn14-32k',)), 'panns-wavegram-logmel': ('PANNsModel', ('wavegram-logmel',)), 'vggish': ('VGGishModel', ())}*

kadtk embedding models by kadtk’s name → (loader class in `kadtk.model_loader`,
its constructor args): fadtk’s, plus the PANNs models. Extend with
`KadtkFidelity(models={...})`. The default, `encodec-emb`, downloads the
smallest weights (EnCodec 24 kHz, about 90 MB).

### *class* foley.eval.kadtk.KadtkFidelity(, bandwidth=None, device='cpu', warn_frames=100, clip_rule=None, \*\*kwargs)

Bases: [`ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity)

Set-level KAD computed by `kadtk` in a separate interpreter.

:param those of [`ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity):
:param plus:
:type bandwidth: [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
:param bandwidth: The RBF bandwidth (default: kadtk’s, the median pairwise distance

> of the generated set’s embedding frames; the one used is in `params`).
* **Parameters:**
  * **device** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Where kadtk computes the kernel sums (`'cpu'`, `'cuda'`, `'mps'`).
  * **warn_frames** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Warn below this many frames a set (default
    `KADTK_WARN_FRAMES`; `None` never warns).
  * **clip_rule** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ClipRule`](#foley.eval.kadtk.ClipRule)]) – What each clip must be (default: the model’s in
    [`KADTK_CLIP_RULES`](#foley.eval.kadtk.KADTK_CLIP_RULES), else any clip).

`model` is a key of [`KADTK_MODELS`](#foley.eval.kadtk.KADTK_MODELS) (default `DEFAULT_KADTK_MODEL`).

#### check_clip(clip, , sr, name)

Refuse a clip `clip_rule` says kadtk would crash on, before it runs.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### failure_hints *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {"No module named '_tkinter'": "kadtk imports turtle, which needs Tk; build the venv on a Python that has it. Install: uv venv ~/venvs/kadtk --python 3.11 --managed-python && uv pip install --python ~/venvs/kadtk/bin/python kadtk torchaudio==2.5.1; then KadtkFidelity(python='~/venvs/kadtk/bin/python') or set FOLEY_KADTK_PYTHON", '_aoti_torch_abi_version': "torchaudio does not match torch; pin torchaudio to torch's version. Install: uv venv ~/venvs/kadtk --python 3.11 --managed-python && uv pip install --python ~/venvs/kadtk/bin/python kadtk torchaudio==2.5.1; then KadtkFidelity(python='~/venvs/kadtk/bin/python') or set FOLEY_KADTK_PYTHON", 'maximum size for tensor at dimension': "kadtk pools this model's embedding per 1 s and crashes on a clip (or, for encodec-emb-48k, a last segment) shorter than that; use longer clips, or give the model a clip_rule"}*

A substring of a failed run’s output → what to do about it.

#### frames_needed(dim)

Two frames: the unbiased MMD² averages over pairs of distinct frames.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### options()

kadtk’s bandwidth and device.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
