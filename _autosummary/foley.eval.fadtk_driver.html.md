# foley.eval.fadtk_driver

The script [`foley.eval.fadtk.FadtkFidelity`](foley.eval.fadtk.html.md#foley.eval.fadtk.FadtkFidelity) runs inside fadtk’s own interpreter.

It is not imported by foley: foley runs it as `python -I fadtk_driver.py SPEC_JSON`
with the interpreter of a virtualenv that has `fadtk` installed (fadtk pins
`numpy<2` and pulls torch, so it cannot share foley’s environment). It imports only
the standard library and fadtk, and only inside [`main()`](#foley.eval.fadtk_driver.main), so foley’s test
collection and linters can load this file without fadtk.

It builds ONE fadtk embedding model from `spec["loader"]` (a class name in
`fadtk.model_loader`) and `spec["args"]`. fadtk’s own command line
(`python -m fadtk`) instantiates every model it knows first, and two of those
download CLAP checkpoints (about 2.5 GB) in their constructors; building one model
avoids that. Then it runs fadtk’s own pipeline (`cache_embedding_files` on each
directory, `FrechetAudioDistance.score`) and writes the score, fadtk’s version, the
model name, the embedding-frame counts and the embedding dimension as JSON to `spec["out"]`.

### Functions

| [`main`](#foley.eval.fadtk_driver.main)(spec_json)   | Score `spec['ref']` against `spec['gen']` with fadtk; write JSON to `spec['out']`.   |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------------|

### foley.eval.fadtk_driver.main(spec_json)

Score `spec['ref']` against `spec['gen']` with fadtk; write JSON to `spec['out']`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
