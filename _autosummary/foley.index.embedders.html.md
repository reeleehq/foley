# foley.index.embedders

Embedders — the joint text<->audio space that powers retrieval.

The default is **LAION-CLAP** `laion/larger_clap_general` (512-d, Apache-2.0):
one space serves both text->audio search and audio<->audio similarity, it is
trained on general/environmental sound (not just music/speech), and its license
is clean for a widely-installed façade (report 04 §1.2, §6.3). It lives behind
the [`Embedder`](foley.index.protocols.html.md#foley.index.protocols.Embedder) protocol so MS-CLAP, PANNs, or GLAP
can be dropped in by keyword injection; every record stores the
`embedding_model`/`embedding_dim` it was indexed under so mixed-model
libraries stay coherent.

`torch`/`transformers` are lazy-imported (the `foley[clap]` extra), so
importing this module — and constructing a [`ClapEmbedder`](#foley.index.embedders.ClapEmbedder) — costs only the
stdlib; the ~1.7 GB checkpoint loads on the first `embed_*` call.

### Module Attributes

| [`DEFAULT_CLAP_MODEL_ID`](#foley.index.embedders.DEFAULT_CLAP_MODEL_ID)              | The default CLAP checkpoint (LAION, Apache-2.0, general/environmental sound).   |
|-------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`CLAP_SAMPLE_RATE`](#foley.index.embedders.CLAP_SAMPLE_RATE)                   | Sample rate CLAP expects at its audio input (report 04 §1.2).                   |
| [`DEFAULT_CLAP_DIM`](#foley.index.embedders.DEFAULT_CLAP_DIM)                   | `projection_dim=512`).                                                          |
| [`PROVISIONAL_PROMPT_MATCH_THRESHOLD`](#foley.index.embedders.PROVISIONAL_PROMPT_MATCH_THRESHOLD) | The prompt-match threshold of a checkpoint with no calibration on record.       |

### Functions

| [`default_embedder`](#foley.index.embedders.default_embedder)()   | Return a process-wide default [`ClapEmbedder`](#foley.index.embedders.ClapEmbedder) (loaded once, reused).   |
|-----------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|

### Classes

| [`ClapEmbedder`](#foley.index.embedders.ClapEmbedder)([model_id, device, ...])   | LAION-CLAP text<->audio embedder (the default retrieval engine).   |
|------------------------------------------------------------------------------------------|--------------------------------------------------------------------|

### foley.index.embedders.CLAP_SAMPLE_RATE *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 48000*

Sample rate CLAP expects at its audio input (report 04 §1.2).

### *class* foley.index.embedders.ClapEmbedder(model_id='laion/larger_clap_general', , device=None, prompt_match_threshold=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LAION-CLAP text<->audio embedder (the default retrieval engine).

Returns **L2-normalized** `float32` embeddings so a plain inner product is
cosine similarity. `embed_text` always returns a 2-D `(n, dim)` array;
`embed_audio` returns a 1-D `(dim,)` array for one clip.

#### model_id

The HF checkpoint id.

#### dim

The embedding dimensionality.

#### open_source

Whether the checkpoint is an open-source model (the LAION
releases are). Read by the ingest AI-use gate for sounds whose rights
holder allows only open-source models (#69).

#### *property* device *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The resolved torch device string (`'cuda'`/`'cpu'`).

#### *property* dim *: [int](https://docs.python.org/3/builtins/functions.html#int)*

The embedding dimensionality (512 for the default; resolved for others).

For a non-default checkpoint this fetches only the model’s `config.json`
(via `AutoConfig`) — never the ~1.7 GB weights — so building an index
for it does not force a model download. Falls back to the loaded model’s
config if the standalone config lacks `projection_dim`.

#### embed_audio(wav, sr)

Embed one audio clip -> `(dim,)` L2-normalized.

The clip is down-mixed to mono and resampled to 48 kHz (what CLAP expects)
via [`foley.audio`](foley.audio.html.md#module-foley.audio) before embedding.

* **Parameters:**
  * **wav** (`ndarray`) – A working-array clip (`float32`; mono or multichannel).
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The clip’s sample rate in Hz.
* **Return type:**
  `ndarray`

#### embed_text(text)

Embed one or more query strings -> `(n_texts, dim)` L2-normalized.

* **Return type:**
  `ndarray`

#### *property* prompt_match_threshold *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Cosine similarity under which a generated clip is flagged as not matching its prompt.

Calibrated per checkpoint on a labelled set ([`foley.eval.prompt_match`](foley.eval.prompt_match.html.md#module-foley.eval.prompt_match),
`foley/data/prompt_match/thresholds.json`); a checkpoint nobody has calibrated
gets [`PROVISIONAL_PROMPT_MATCH_THRESHOLD`](#foley.index.embedders.PROVISIONAL_PROMPT_MATCH_THRESHOLD).

### foley.index.embedders.DEFAULT_CLAP_DIM *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 512*

`projection_dim=512`).

* **Type:**
  Embedding width for the default checkpoint (verified

### foley.index.embedders.DEFAULT_CLAP_MODEL_ID *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'laion/larger_clap_general'*

The default CLAP checkpoint (LAION, Apache-2.0, general/environmental sound).

### foley.index.embedders.PROVISIONAL_PROMPT_MATCH_THRESHOLD *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.2*

The prompt-match threshold of a checkpoint with no calibration on record. LAION-CLAP
puts matching text-audio pairs around 0.3-0.5 and unrelated ones near 0-0.15; this is
a guess between them, not a measurement.

### foley.index.embedders.default_embedder()

Return a process-wide default [`ClapEmbedder`](#foley.index.embedders.ClapEmbedder) (loaded once, reused).

Cached so repeated `foley.search()` calls share a single loaded model.

* **Return type:**
  [`ClapEmbedder`](#foley.index.embedders.ClapEmbedder)
