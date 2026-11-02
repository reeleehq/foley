# foley.eval.toolkit_driver

The script [`foley.eval.external_fidelity.ExternalFidelity`](foley.eval.external_fidelity.html.md#foley.eval.external_fidelity.ExternalFidelity) runs inside a toolkit’s interpreter.

It is not imported by foley: foley runs it as `python -I toolkit_driver.py SPEC_JSON`
with the interpreter of a virtualenv that has the toolkit (`fadtk` or `kadtk`)
installed (both pin `numpy<2` and an old torch, so neither can share foley’s
environment). It imports only the standard library and the toolkit, and only inside
the functions, so foley’s test collection and linters can load this file without them.

It builds ONE embedding model from `spec["loader"]` (a class name in
`<toolkit>.model_loader`) and `spec["args"]`. The toolkits’ own command lines
(`python -m fadtk`, `python -m kadtk`) instantiate every model they know first,
and the CLAP constructors download their checkpoints (about 2.5 GB); building one
model avoids that. Then it runs the toolkit’s own pipeline (`cache_embedding_files`
on each directory, then the toolkit’s scorer, see [`TOOLKITS`](#foley.eval.toolkit_driver.TOOLKITS)) and writes the
score, the toolkit’s version, the model name, the embedding-frame counts, the
embedding dimension and the scorer’s parameters (kadtk: the bandwidth it used and its
scale) as JSON to `spec["out"]`.

### Module Attributes

| [`TOOLKITS`](#foley.eval.toolkit_driver.TOOLKITS)   | Toolkit name → a function of the spec returning (embedding cacher, scorer).   |
|-------------------------------------------------------------|-------------------------------------------------------------------------------|

### Functions

| [`main`](#foley.eval.toolkit_driver.main)(spec_json)   | Score `spec['ref']` against `spec['gen']` with `spec['toolkit']`; write JSON to `spec['out']`.   |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|

### foley.eval.toolkit_driver.TOOLKITS *= {'fadtk': <function \_fadtk>, 'kadtk': <function \_kadtk>}*

Toolkit name → a function of the spec returning (embedding cacher, scorer).

### foley.eval.toolkit_driver.main(spec_json)

Score `spec['ref']` against `spec['gen']` with `spec['toolkit']`; write JSON to `spec['out']`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
