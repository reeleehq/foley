# foley.obs.redact

Redaction of sensitive narration / prompt / query text in telemetry (#11).

A published product’s narration is frequently confidential or pre-release, yet foley
exfiltrates prompt/query text to LLM, generation, and search backends (report 12
§privacy). So every value foley writes into a span attribute or a run-manifest is
passed through this module’s SSOT redactor, which — by **default** — replaces a
sensitive string with a salted content **hash** + length (never the raw text), so a
manifest still *joins* a prompt to its provenance without exposing it.

Stdlib-only. Applied at TWO boundaries (belt-and-suspenders, mirroring
`qc._json_safe`’s construction-time clamp + serialization sweep):

* **record-time** (primary): the recorder routes every sensitive value through
  [`Redactor.redact_value()`](#foley.obs.redact.Redactor.redact_value) before it enters the in-memory `SpanRecord` /
  > `RunManifest` — so raw text never reaches the OTel mirror either;
* **emit-time** (net): [`Redactor.redact_manifest()`](#foley.obs.redact.Redactor.redact_manifest) deep-walks the serialized
  manifest before the store write, catching anything stuffed past record-time.

### Module Attributes

| [`REDACT_FIELDS`](#foley.obs.redact.REDACT_FIELDS)   | The attribute / field keys whose string values are sensitive and redacted.   |
|------------------------------------------------------------------|------------------------------------------------------------------------------|

### Functions

| [`redact_text`](#foley.obs.redact.redact_text)(text, \*[, mode, salt, preview_chars])   | Redact one string per `mode`.   |
|-------------------------------------------------------------------------------------------------------|---------------------------------|

### Classes

| [`RedactionMode`](#foley.obs.redact.RedactionMode)(\*values)                       | How a sensitive string is rendered in telemetry (`str`-Enum → serializes cleanly).   |
|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`Redactor`](#foley.obs.redact.Redactor)([mode, salt, preview_chars, fields]) | The SSOT applier: redacts sensitive keys in values, attribute dicts, and manifests.  |

### foley.obs.redact.REDACT_FIELDS *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= frozenset({'context_text', 'gen_ai.completion', 'gen_ai.prompt', 'generation_prompt', 'generation_prompt_used', 'narration', 'negative_prompt', 'onset', 'prompt', 'prompt_used', 'query'})*

The attribute / field keys whose string values are sensitive and redacted. The
narration/prompt/query surfaces report 12 §11 names; `context_text` / `narration`
/ `gen_ai.*` producers arrive with the #7 agent, but the seam + keys exist now.

### *class* foley.obs.redact.RedactionMode(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a sensitive string is rendered in telemetry (`str`-Enum → serializes cleanly).

### *class* foley.obs.redact.Redactor(mode=RedactionMode.hash, salt='foley-obs-v1', preview_chars=0, fields=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The SSOT applier: redacts sensitive keys in values, attribute dicts, and manifests.

#### redact_attrs(attrs)

Redact every sensitive key in a (shallow) attribute/inputs dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### redact_error(exc)

Redact an exception for storage/export.

An exception message can echo the raw prompt/query/narration (hosted
backends commonly do), so by default only the exception **type name** is
recorded (safe + still useful); the full `repr` is kept only in
`full` mode (opt-in local debug).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### redact_manifest(payload)

Deep-walk `payload` (dict/list), redacting any sensitive key at any depth.

The emit-time net: catches `inputs.query` / `seeds[*].prompt` / any nested
sensitive value a caller stuffed past the record-time layer.

#### redact_value(key, value)

Redact `value` iff `key` is a sensitive field and `value` is a string.

### foley.obs.redact.redact_text(text, , mode=RedactionMode.hash, salt='foley-obs-v1', preview_chars=0)

Redact one string per `mode`.

* **Parameters:**
  * **text** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The (possibly sensitive) string, or `None`.
  * **mode** ([`RedactionMode`](#foley.obs.redact.RedactionMode)) – `off` → `None`; `full` → `text` verbatim; `hash` (default) →
    `{"sha256": <salted hex>, "len": <n>}` (+ `"preview"` only if
    `preview_chars > 0`).
  * **salt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Salt mixed into the hash (injectable; default fixed for diffability).
  * **preview_chars** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – If > 0 (hash mode), include a leading `text[:preview_chars]`
    preview. Default 0 → **zero content leak**.
* **Returns:**
  `None`, the raw string, or a hash dict — depending on `mode`.
