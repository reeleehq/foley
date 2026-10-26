# foley.eval.prompt_match

Calibrate the prompt-match threshold of a text-audio embedder on a labelled set (#111).

[`foley.prompt_match.prompt_match()`](foley.prompt_match.html.md#foley.prompt_match.prompt_match) flags a generated clip whose CLAP similarity to
its own prompt is under a threshold. That threshold depends on the checkpoint, so it is
measured, not guessed: given prompts and the clips generated for them, every prompt is
scored against every clip. A clip generated for its prompt is a *match*; the same clip
scored against another prompt is a *mismatch* (the failure the check exists for: a clean
clip of the wrong thing). [`calibrate_threshold()`](#foley.eval.prompt_match.calibrate_threshold) picks the cut that best separates
the two and reports precision and recall of the **mismatch** call; [`save_threshold()`](#foley.eval.prompt_match.save_threshold)
records it per checkpoint in `foley/data/prompt_match/thresholds.json`, which
[`foley.prompt_match.threshold_for()`](foley.prompt_match.html.md#foley.prompt_match.threshold_for) (and so [`foley.index.embedders.ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder)) reads.

The labels are only as good as the clips: a “match” is a clip generated for the prompt,
not one a person listened to, so a generation that missed its prompt counts as a match
and pulls the threshold down. Put by-ear labels in the manifest (`"match": false` on a
clip) to correct that. Pure numpy/stdlib apart from the embedder passed in.

### Functions

| [`calibrate_threshold`](#foley.eval.prompt_match.calibrate_threshold)(scores)                       | The threshold under which a clip is called a mismatch, maximising balanced accuracy.   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| [`load_labelled_dir`](#foley.eval.prompt_match.load_labelled_dir)(directory)                      | The `score_pairs` items of a directory holding `manifest.json` and its clips.          |
| [`save_threshold`](#foley.eval.prompt_match.save_threshold)(model_id, calibration, \*, source) | Record `calibration` for `model_id` (`source`: what set it was measured on).           |
| [`score_pairs`](#foley.eval.prompt_match.score_pairs)(embedder, items)                      | Every prompt against every clip: `[(cosine, is_match), ...]`.                          |

### Classes

| [`Calibration`](#foley.eval.prompt_match.Calibration)(threshold, precision, recall, ...)   | A measured threshold and what it achieves on the labelled set.   |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------|

### *class* foley.eval.prompt_match.Calibration(threshold, precision, recall, f1, match_kept, auc, n_match, n_mismatch, match_mean, mismatch_mean)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A measured threshold and what it achieves on the labelled set.

### foley.eval.prompt_match.calibrate_threshold(scores)

The threshold under which a clip is called a mismatch, maximising balanced accuracy.

Balanced accuracy (the mean of the share of mismatches caught and the share of matches
kept) because the set has far more mismatch pairs (n² - n) than matches (n): plain F1
would be won by a threshold that flags most good clips. A false alarm costs a listen,
a miss costs a wrong sound in the film; this weighs them equally, and [`Calibration`](#foley.eval.prompt_match.Calibration)
reports precision and recall so the trade can be re-struck.

* **Parameters:**
  **scores** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]) – `[(similarity, is_match), ...]` from [`score_pairs()`](#foley.eval.prompt_match.score_pairs).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If either class is empty.
* **Return type:**
  [`Calibration`](#foley.eval.prompt_match.Calibration)

### foley.eval.prompt_match.load_labelled_dir(directory)

The `score_pairs` items of a directory holding `manifest.json` and its clips.

The manifest is a list of `{"prompt": ..., "file": ..., "match": true}` (`match`
defaults to true; set it false for a clip a listener rejected for its prompt).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]

### foley.eval.prompt_match.save_threshold(model_id, calibration, , source, path=PosixPath('/home/runner/work/foley/foley/foley/data/prompt_match/thresholds.json'))

Record `calibration` for `model_id` (`source`: what set it was measured on).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.eval.prompt_match.score_pairs(embedder, items)

Every prompt against every clip: `[(cosine, is_match), ...]`.

`items` is `[(prompt, clip_bytes, clip_matches_prompt), ...]`. Pair `(i, i)` is a
match when its flag is true (a clip a listener rejected counts as a mismatch); pair `(i, j)` with `i != j` is a mismatch (clip `j`
was made for another prompt). Embeddings are computed once per prompt and per clip.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]
