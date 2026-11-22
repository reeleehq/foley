# foley.index.taggers

Taggers — auto-fill a sound’s semantic labels on ingest (report 03).

Two default taggers behind the [`Tagger`](foley.index.protocols.html.md#foley.index.protocols.Tagger) protocol:

> * [`ClapZeroShotTagger`](#foley.index.taggers.ClapZeroShotTagger) — foley’s default. Scores a clip against a
>   custom/UCS label set by CLAP cosine (report 03 Part 2), \*\*reusing the same
>   embedder the Index already loads\*\* — so ingest never loads CLAP twice and
>   it needs no dependency beyond `foley[clap]`.
> * [`PannsTagger`](#foley.index.taggers.PannsTagger) — PANNs CNN14 supervised tagging over the 527 AudioSet
>   classes (report 03 Part 1); `foley[tag]`. The checkpoint auto-downloads
>   (~327 MB) on first use.

Captioners (EnCLAP / Qwen2-Audio, `foley[caption]`) plug in behind the
[`Captioner`](foley.index.protocols.html.md#foley.index.protocols.Captioner) protocol as adapters; none ships as a
default yet (no clean, permissively-licensed, pip-installable checkpoint), so the
ingest caption stage is off unless a captioner is injected.

Heavy deps (`torch`/`transformers`/`panns_inference`) are lazy-imported, so
importing this module costs only the stdlib.

### Module Attributes

| [`ZEROSHOT_PROMPT`](#foley.index.taggers.ZEROSHOT_PROMPT)            | Prompt template for zero-shot CLAP tagging (report 03 Part 2).                  |
|-----------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`PANNS_SAMPLE_RATE`](#foley.index.taggers.PANNS_SAMPLE_RATE)          | PANNs CNN14 expects 32 kHz mono audio.                                          |
| [`PANNS_DATA_DIR`](#foley.index.taggers.PANNS_DATA_DIR)             | Where panns-inference keeps (and, when missing, `wget`-downloads) its files.    |
| [`PANNS_CHECKPOINT_MIN_BYTES`](#foley.index.taggers.PANNS_CHECKPOINT_MIN_BYTES) | panns-inference treats a smaller checkpoint as incomplete and fetches it again. |

### Functions

| [`default_tagger`](#foley.index.taggers.default_tagger)()                    | The default supervised tagger (PANNs CNN14; `foley[tag]`).               |
|--------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`default_zeroshot_tagger`](#foley.index.taggers.default_zeroshot_tagger)([embedder]) | The default zero-shot tagger (CLAP vs UCS subcategories; `foley[clap]`). |

### Classes

| [`ClapZeroShotTagger`](#foley.index.taggers.ClapZeroShotTagger)(\*[, embedder, labels, ...])   | Zero-shot tagger: score a clip against a label set via CLAP cosine.         |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`PannsTagger`](#foley.index.taggers.PannsTagger)(\*[, device, threshold])              | PANNs CNN14 supervised tagger over the 527 AudioSet classes (`foley[tag]`). |

### *class* foley.index.taggers.ClapZeroShotTagger(, embedder=None, labels=None, prompt='this is a sound of {label}', threshold=0.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Zero-shot tagger: score a clip against a label set via CLAP cosine.

Reuses a [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder) (the same model the
Index uses), so the audio is embedded in the same joint space as the label
prompts and no extra weights load. The default label set is the UCS
subcategory names (foley’s own vocabulary), so tags land in-taxonomy.

#### *property* embedder

The CLAP embedder (injected or the process-wide default).

#### *property* labels *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

natural UCS `category subcategory` phrases).

Natural multi-word phrases (`"weather rain"`, `"glass break"`) are far
better CLAP prompts — and better BM25 tags / taxonomy-resolver input — than
bare abstract subcategory words (`"Break"`, `"Buzz"`); a generic
subcategory (`GENERAL`, `MISC`) gives the bare category, and the
`ARCHIVED` bookkeeping rows give none, which are a known
zero-shot artifact (anomalously close to everything). Absolute tag-quality
calibration (thresholds, label curation) is an eval-harness concern (#10).

* **Type:**
  The label vocabulary ([*default*](foley.html.md#foley.Affordance.default)

#### tag(wav, sr, , taxonomy='custom', top_k=10)

Return the top-`k` `(label, cosine)` tags for the clip, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### tag_vector(audio_vec, , top_k=10)

Score a **precomputed** (L2-normalized) audio vector against the labels.

The efficiency seam (report 03 Part 2): the Index already embeds every
sound with this model, so on ingest the retrieval vector is reused here —
no second CLAP forward pass.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### foley.index.taggers.PANNS_CHECKPOINT_MIN_BYTES *= 300000000*

panns-inference treats a smaller checkpoint as incomplete and fetches it again.

### foley.index.taggers.PANNS_DATA_DIR *= '~/panns_data'*

Where panns-inference keeps (and, when missing, `wget`-downloads) its files.

### foley.index.taggers.PANNS_SAMPLE_RATE *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 32000*

PANNs CNN14 expects 32 kHz mono audio.

### *class* foley.index.taggers.PannsTagger(, device='cpu', threshold=0.1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

PANNs CNN14 supervised tagger over the 527 AudioSet classes (`foley[tag]`).

The checkpoint auto-downloads to `~/panns_data` (~327 MB) on the first
[`tag()`](#foley.index.taggers.PannsTagger.tag). PANNs expects 32 kHz mono; the clip is resampled via
[`foley.audio.to_working()`](foley.audio.html.md#foley.audio.to_working).

#### tag(wav, sr, , taxonomy='audioset', top_k=10)

Return the top-`k` `(AudioSet label, score)` tags, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### foley.index.taggers.ZEROSHOT_PROMPT *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'this is a sound of {label}'*

Prompt template for zero-shot CLAP tagging (report 03 Part 2).

### foley.index.taggers.default_tagger()

The default supervised tagger (PANNs CNN14; `foley[tag]`).

* **Return type:**
  [`PannsTagger`](#foley.index.taggers.PannsTagger)

### foley.index.taggers.default_zeroshot_tagger(embedder=None)

The default zero-shot tagger (CLAP vs UCS subcategories; `foley[clap]`).

Cached **per embedder** so the tagger is bound to the SAME embedder that
produced the audio vector it scores — otherwise (report seam) the cosine would
cross two unrelated embedding spaces. `embedder=None` uses the process-wide
default embedder.

* **Return type:**
  [`ClapZeroShotTagger`](#foley.index.taggers.ClapZeroShotTagger)
