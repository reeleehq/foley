# foley.index.onnx_clap

CLAP on a small host: the same checkpoint through ONNX Runtime, no torch, no transformers.

A production server with no GPU, about 2 GB of free RAM and no `transformers` cannot
load [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder) (a ~1.7 GB model plus torch), so every
generated clip there used to be `unchecked` by [`foley.prompt_match.prompt_match()`](foley.prompt_match.html.md#foley.prompt_match.prompt_match)
(#116). [`OnnxClapEmbedder`](#foley.index.onnx_clap.OnnxClapEmbedder) runs `laion/larger_clap_general` from the community
ONNX export `Xenova/larger_clap_general` (ungated), int8-quantised: about 205 MB on
disk, a few hundred MB of RAM, and the same 512-d text-audio space, so it can stand in for
the full model wherever only the similarity of a text and a clip matters.

It needs `onnxruntime`, `tokenizers` and `huggingface_hub` (the `foley[clap-onnx]`
extra) and `numpy`; the log-mel front end is a small numpy port of
`transformers`’ `ClapFeatureExtractor` (checked against it in the tests), so nothing
else is imported. The quantised model gives slightly different vectors from the full one:
its prompt-match threshold is calibrated separately ([`foley.eval.prompt_match`](foley.eval.prompt_match.html.md#module-foley.eval.prompt_match)) under
its own id, [`ONNX_CLAP_MODEL_ID`](#foley.index.onnx_clap.ONNX_CLAP_MODEL_ID), and it is not a drop-in for an index built with the
full embedder (use it to compare a text with a clip, not to search an index).

Same protocol as [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder): `embed_text` ->
`(n, 512)`, `embed_audio` -> `(512,)`, L2-normalised, `prompt_match_threshold`.
Clips over 10 s are cut to the middle 10 s (`transformers` takes a random crop), so the
vector is deterministic.

### Module Attributes

| [`ONNX_CLAP_REPO`](#foley.index.onnx_clap.ONNX_CLAP_REPO)     | The ONNX export repo (an ungated mirror of the LAION checkpoint's graphs).              |
|---------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`ONNX_CLAP_MODEL_ID`](#foley.index.onnx_clap.ONNX_CLAP_MODEL_ID) | The id the thresholds file keys the quantised model under (the checkpoint + its build). |

### Functions

| [`log_mel`](#foley.index.onnx_clap.log_mel)(wav)   | The `(1001, 64)` dB log-mel features of a mono 48 kHz clip, as `ClapFeatureExtractor`'s.   |
|-----------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`mel_filters`](#foley.index.onnx_clap.mel_filters)()  | The `(513, 64)` triangular Slaney-scale, Slaney-normalised mel filter bank.                |

### Classes

| [`OnnxClapEmbedder`](#foley.index.onnx_clap.OnnxClapEmbedder)(\*[, threads, ...])   | The int8 ONNX CLAP embedder (see the module docstring).   |
|-----------------------------------------------------------------------------------------|-----------------------------------------------------------|

### foley.index.onnx_clap.ONNX_CLAP_MODEL_ID *= 'Xenova/larger_clap_general:int8'*

The id the thresholds file keys the quantised model under (the checkpoint + its build).

### foley.index.onnx_clap.ONNX_CLAP_REPO *= 'Xenova/larger_clap_general'*

The ONNX export repo (an ungated mirror of the LAION checkpoint’s graphs).

### *class* foley.index.onnx_clap.OnnxClapEmbedder(, threads=None, prompt_match_threshold=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The int8 ONNX CLAP embedder (see the module docstring).

#### model_id

[`ONNX_CLAP_MODEL_ID`](#foley.index.onnx_clap.ONNX_CLAP_MODEL_ID), the key of its calibrated threshold.

#### dim

#### open_source

True (the LAION checkpoint is).

#### embed_audio(wav, sr)

Embed one clip -> `(512,)` L2-normalised (down-mixed and resampled to 48 kHz).

* **Return type:**
  `ndarray`

#### embed_text(text)

Embed one or more query strings -> `(n_texts, 512)` L2-normalised.

Each text is run alone, unpadded: the exported text graph takes no attention mask.

* **Return type:**
  `ndarray`

#### *property* prompt_match_threshold *: [float](https://docs.python.org/3/builtins/functions.html#float)*

The calibrated threshold of the quantised model (provisional until calibrated).

### foley.index.onnx_clap.log_mel(wav)

The `(1001, 64)` dB log-mel features of a mono 48 kHz clip, as `ClapFeatureExtractor`’s.

The clip is cut to its middle 10 s or, if shorter, repeated to fill 10 s and
zero-padded (`repeatpad`); then a centred, reflect-padded, periodic-Hann STFT
(1024 / hop 480), power spectrum, mel projection, `10 * log10(max(x, 1e-10))`.

* **Return type:**
  `ndarray`

### foley.index.onnx_clap.mel_filters()

The `(513, 64)` triangular Slaney-scale, Slaney-normalised mel filter bank.

What `ClapFeatureExtractor` uses outside its “fusion” mode (`librosa.filters.mel`’s
defaults, 50 Hz to 14 kHz).

* **Return type:**
  `ndarray`
