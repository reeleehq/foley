# foley.eval.toolkit_driver

The script [`foley.eval.external_toolkit.ExternalToolkit`](foley.eval.external_toolkit.html.md#foley.eval.external_toolkit.ExternalToolkit) runs inside a toolkit’s interpreter.

It is not imported by foley: foley runs it as `python -I toolkit_driver.py SPEC_JSON`
with the interpreter of a virtualenv that has the toolkit (`fadtk`, `kadtk` or
`audiobox_aesthetics`, `msclap`) installed (none can share foley’s environment). It imports
only the standard library and the toolkit, and only inside the functions, so foley’s
test collection and linters can load this file without them. `spec["task"]` picks
what it computes ([`TASKS`](#foley.eval.toolkit_driver.TASKS)): `fidelity` (the default), `aesthetics` or
`pam`.

`fidelity` builds ONE embedding model from `spec["loader"]` (a class name in
`<toolkit>.model_loader`) and `spec["args"]`. The toolkits’ own command lines
(`python -m fadtk`, `python -m kadtk`) instantiate every model they know first,
and the CLAP constructors download their checkpoints (about 2.5 GB); building one
model avoids that. Then it runs the toolkit’s own pipeline (`cache_embedding_files`
on each directory, then the toolkit’s scorer, see [`TOOLKITS`](#foley.eval.toolkit_driver.TOOLKITS)) and writes the
score, the toolkit’s version, the model name, the embedding-frame counts, the
embedding dimension and the scorer’s parameters (kadtk: the bandwidth it used and its
scale) as JSON to `spec["out"]`.

`aesthetics` scores each WAV of `spec["clips"]` (in that order) with Meta’s
Audiobox Aesthetics predictor (`initialize_predictor`, from `spec["checkpoint"]`
or, when that is `None`, the Hugging Face `facebook/audiobox-aesthetics` weights),
`spec["batch_size"]` clips a forward pass. The WAVs are read with the standard
library’s `wave` (foley writes them as 16-bit PCM) rather than `torchaudio.load`,
which needs `torchcodec` from torchaudio 2.9 on. It writes one `{CE, CU, PC, PQ}`
row per clip, the package version and the model as JSON to `spec["out"]`.

`pam` scores each WAV of `spec["clips"]` with PAM (Deshmukh et al., Interspeech
2024): the softmax, over `spec["prompts"]`, of MS-CLAP 2023’s audio-text
similarities, the probability of the first prompt. It reproduces the reference
(github.com/soham97/PAM, `PAM/PAM.py` and `dataset.py`) on the `msclap` package,
whose 2023 model and config are the ones PAM vendors: each clip is resampled with
torchaudio’s `Resample` to the model’s rate, tiled to one window if shorter, else cut
into whole windows plus the last window; each window is scored and a clip’s score is
their mean. One deviation, which does not change the numbers: msclap builds its GPT-2
text encoder with `AutoModel.from_pretrained('gpt2')` (548 MB of weights) and then
overwrites every one of them from the CLAP checkpoint (`caption_encoder.base.*`);
here GPT-2 is built from its config, and the load is checked to leave no parameter
unset. It writes one `{score, segments}` row per clip, the msclap version, the model
and the prompts as JSON to `spec["out"]`.

### Module Attributes

| [`TOOLKITS`](#foley.eval.toolkit_driver.TOOLKITS)   | Toolkit name → a function of the spec returning (embedding cacher, scorer).   |
|-------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`TASKS`](#foley.eval.toolkit_driver.TASKS)      | `spec["task"]` → the function of the spec computing the answer.               |

### Functions

| [`main`](#foley.eval.toolkit_driver.main)(spec_json)   | Compute `spec['task']` (default `fidelity`) and write its JSON to `spec['out']`.   |
|--------------------------------------------------------------------|------------------------------------------------------------------------------------|

### foley.eval.toolkit_driver.TASKS *= {'aesthetics': <function \_aesthetics>, 'fidelity': <function \_fidelity>, 'pam': <function \_pam>}*

`spec["task"]` → the function of the spec computing the answer.

### foley.eval.toolkit_driver.TOOLKITS *= {'fadtk': <function \_fadtk>, 'kadtk': <function \_kadtk>}*

Toolkit name → a function of the spec returning (embedding cacher, scorer).

### foley.eval.toolkit_driver.main(spec_json)

Compute `spec['task']` (default `fidelity`) and write its JSON to `spec['out']`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
