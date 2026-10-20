# foley.obs

Observability & the reproducible run-artifact for foley (#11).

The cross-cutting layer that makes foley debuggable, auditable, and re-renderable —
the “snapshots/stories for the SFX layer”. Every instrumented operation
(`generate` / `add_from` / `ingest` / `search` / `similar` — and, later, a
#7 `find()` / #8 `weave()` scope) can emit one [`RunManifest`](#foley.obs.RunManifest):
simultaneously the debug **trace** (span tree), the reproducible **plan/seed** record,
and the **provenance** record — report 10 §1.3.

**Manifest-first**: the run-artifact is pure stdlib and exists on a bare
`pip install foley`; OpenTelemetry is an *optional mirror* behind the
`foley[obs]` extra (vendor-neutral GenAI spans for Langfuse/Datadog/…). \*\*Off by
default\*\*: `import foley` stays dol-only and a plain façade call is a byte-for-byte
no-op until `foley.obs.enable()` / `$FOLEY_OBS=1` / `with foley.obs.run(...)`.
Sensitive prompt/query/narration text is **redacted** (salted content hash) by default.

All four submodules are stdlib-only at import; `opentelemetry` loads lazily inside
[`OTelTracer`](foley.obs.trace.html.md#foley.obs.trace.OTelTracer) only, so importing this package is dol-only.

### Functions

| [`emit_run_manifest`](#foley.obs.emit_run_manifest)(store, manifest, \*[, redactor])   | Serialize `manifest` (redacting the payload) and write it to `store`.                                                                  |
|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| [`ingest_digest`](#foley.obs.ingest_digest)(report)                                | A leak-free digest of an [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) for a manifest. |
| [`load_run`](#foley.obs.load_run)(store, run_id)                              | Load and typed-rehydrate a [`RunManifest`](#foley.obs.RunManifest) from `store` (the read helper).                |
| [`run`](#foley.obs.run)([op, inputs, params])                            | Open an explicit run scope that aggregates nested façade calls into ONE manifest.                                                      |
| [`facade_run`](#foley.obs.facade_run)(op, \*[, inputs, params])                 | The get-or-create seam every façade wraps its body in.                                                                                 |
| [`current_run`](#foley.obs.current_run)()                                        | The active [`RunRecorder`](#foley.obs.RunRecorder), or `_NULL_RUN` (for the shared child span).                   |
| [`enable`](#foley.obs.enable)(\*\*overrides)                                | Turn observability on process-wide (and apply any [`ObsConfig`](#foley.obs.ObsConfig) overrides).               |
| [`disable`](#foley.obs.disable)()                                            | Turn observability off process-wide (façades revert to a byte-for-byte no-op).                                                         |
| [`configure`](#foley.obs.configure)(\*\*overrides)                             | Apply [`ObsConfig`](#foley.obs.ObsConfig) overrides WITHOUT flipping `enabled` (the test-injection seam).       |
| [`reset`](#foley.obs.reset)()                                              | Restore the default config (test teardown; clears injected store/tracer/clock).                                                        |
| [`is_enabled`](#foley.obs.is_enabled)()                                         | Whether observability is on (via [`enable()`](#foley.obs.enable) or `$FOLEY_OBS` in {1,true,yes}).           |
| [`get_tracer`](#foley.obs.get_tracer)(\*[, prefer_otel])                        | Return the effective [`Tracer`](#foley.obs.Tracer) (OTel-backed when available, else no-op).                 |
| [`redact_text`](#foley.obs.redact_text)(text, \*[, mode, salt, preview_chars])   | Redact one string per `mode`.                                                                                                          |

### Classes

| [`RunManifest`](#foley.obs.RunManifest)(run_id, op[, created_at, ...])        | The reproducible run-artifact for one foley operation (trace ⊕ plan ⊕ provenance).                                                                                          |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`SpanRecord`](#foley.obs.SpanRecord)(name, span_id[, parent_id, kind, ...]) | One node of the run's span tree (the trace half of the artifact).                                                                                                           |
| [`Step`](#foley.obs.Step)(kind[, seq, event_index, span_id, ...])      | One SELECT-stage step of a `find()` run (the plan half of the artifact, #7).                                                                                                |
| [`ObsConfig`](#foley.obs.ObsConfig)([enabled, force_disabled, ...])         | Process-wide observability configuration (flipped by [`enable()`](#foley.obs.enable)/[`disable()`](#foley.obs.disable)). |
| [`RunRecorder`](#foley.obs.RunRecorder)(manifest, \*, tracer, redactor, ...)  | Builds one [`RunManifest`](#foley.obs.RunManifest) (span tree + composed shapes), tracer-independent.                                                  |
| [`Tracer`](#foley.obs.Tracer)(\*args, \*\*kwargs)                        | Starts mirror spans; the DI seam (default no-op, OTel-backed when present).                                                                                                 |
| [`NoOpTracer`](#foley.obs.NoOpTracer)()                                      | The default [`Tracer`](#foley.obs.Tracer) — yields the shared `_NOOP_SPAN`, zero deps.                                                            |
| [`Redactor`](#foley.obs.Redactor)([mode, salt, preview_chars, fields])     | The SSOT applier: redacts sensitive keys in values, attribute dicts, and manifests.                                                                                         |
| [`RedactionMode`](#foley.obs.RedactionMode)(\*values)                           | How a sensitive string is rendered in telemetry (`str`-Enum → serializes cleanly).                                                                                          |

### *class* foley.obs.NoOpTracer

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default [`Tracer`](#foley.obs.Tracer) — yields the shared `_NOOP_SPAN`, zero deps.

#### start_as_current_span(name, , kind=None, attributes=None)

Yield the no-op span (context-manager protocol; nothing is recorded).

### *class* foley.obs.ObsConfig(enabled=False, force_disabled=False, redaction_mode=RedactionMode.hash, salt='foley-obs-v1', prefer_otel=True, run_store=None, tracer=None, clock=<built-in function time>, id_factory=<function ObsConfig.<lambda>>, now=<function \_iso_now>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Process-wide observability configuration (flipped by [`enable()`](#foley.obs.enable)/[`disable()`](#foley.obs.disable)).

#### clock()

time() -> floating-point number

Return the current time in seconds since the Epoch.
Fractions of a second may be present if the system clock provides them.

#### now()

ISO-8601 UTC timestamp (real wall-clock; overridden to `None` in tests).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.obs.RedactionMode(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a sensitive string is rendered in telemetry (`str`-Enum → serializes cleanly).

### *class* foley.obs.Redactor(mode=RedactionMode.hash, salt='foley-obs-v1', preview_chars=0, fields=<factory>)

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

### *class* foley.obs.RunManifest(run_id, op, created_at=None, foley_version=None, inputs=dict(), params=dict(), spans=list(), steps=list(), ingest_report=None, result_ids=list(), candidate_scores=list(), credits_ref=None, disclosure_refs=dict(), seeds=dict(), plan_ref=None, trace_ref=None, status='ok', error=None, schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The reproducible run-artifact for one foley operation (trace ⊕ plan ⊕ provenance).

Persisted by [`emit_run_manifest()`](#foley.obs.emit_run_manifest) into a run store keyed by `run_id`.
Sensitive prompt/query text lives redacted (see [`foley.obs.redact`](foley.obs.redact.html.md#module-foley.obs.redact)); chosen
clips are held by reference (`SoundRecord` id) so the manifest stays light and a
trace can be replayed against a fresh index.

### *class* foley.obs.RunRecorder(manifest, , tracer, redactor, run_store, clock, id_factory)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Builds one [`RunManifest`](#foley.obs.RunManifest) (span tree + composed shapes), tracer-independent.

#### add_step(step)

Append a SELECT-stage [`Step`](#foley.obs.Step) (#7), deep-redacting `detail` at record time.

The record-time net (belt over the emit-time sweep): event text carried in
`detail` (under the `query` key) is hashed here so a manifest read straight
off `self.manifest.steps` — before any emit — never holds raw narration.
`seq` is assigned here (append position) when the caller left it `None`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### emit()

Persist the manifest to the run store — swallowing any write failure.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_plan_ref(plan_ref)

Fill the reserved #8 `plan_ref` slot (a light join dict — no text).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### span(name, , kind=None, \*\*attributes)

Open a span: append a [`SpanRecord`](#foley.obs.SpanRecord) (from our own clock/ids) + mirror it.

### *class* foley.obs.SpanRecord(name, span_id, parent_id=None, kind=None, start_ms=None, duration_ms=None, status='ok', attributes=dict(), events=list(), error=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One node of the run’s span tree (the trace half of the artifact).

Built by the recorder from its own clock + id-factory, independent of any tracer,
so the tree is complete even when the OTel mirror is a total no-op.

### *class* foley.obs.Step(kind, seq=None, event_index=None, span_id=None, status='ok', detail=dict())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One SELECT-stage step of a `find()` run (the plan half of the artifact, #7).

The typed entry type of `RunManifest.steps`: a compact, redacted record of
each `decompose`/`refine`/`search`/`license_gate`/`verify`/`decide`/
`generate`/`place` stage, in `seq` order, with `span_id` joining the step
back to the [`SpanRecord`](#foley.obs.SpanRecord) that timed it. `detail` is a small,
already-redacted dict (event text lives under the `query` key so the redactor
catches it). Rehydrated element-wise by `RunManifest.from_dict()` exactly like
`spans` (see the module docstring).

### *class* foley.obs.Tracer(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Starts mirror spans; the DI seam (default no-op, OTel-backed when present).

### foley.obs.configure(\*\*overrides)

Apply [`ObsConfig`](#foley.obs.ObsConfig) overrides WITHOUT flipping `enabled` (the test-injection seam).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.current_run()

The active [`RunRecorder`](#foley.obs.RunRecorder), or `_NULL_RUN` (for the shared child span).

### foley.obs.disable()

Turn observability off process-wide (façades revert to a byte-for-byte no-op).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.emit_run_manifest(store, manifest, , redactor=None)

Serialize `manifest` (redacting the payload) and write it to `store`.

The plain-dict write path keeps an emit-time interposition point for the
belt-and-suspenders redaction sweep (do NOT couple the write to
auto-serialization). Returns the `run_id`.

* **Parameters:**
  * **store** ([`MutableMapping`](https://docs.python.org/3/library/typing.html#typing.MutableMapping)) – A `MutableMapping[str, dict]` (default:
    [`foley.stores.make_run_store()`](foley.stores.html.md#foley.stores.make_run_store); a dict in tests).
  * **manifest** ([`RunManifest`](foley.obs.run_artifact.html.md#foley.obs.run_artifact.RunManifest)) – The [`RunManifest`](#foley.obs.RunManifest) to persist.
  * **redactor** – An optional [`Redactor`](foley.obs.redact.html.md#foley.obs.redact.Redactor) applied to the full
    payload before the write (the emit-time net).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.obs.enable(\*\*overrides)

Turn observability on process-wide (and apply any [`ObsConfig`](#foley.obs.ObsConfig) overrides).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.facade_run(op, , inputs=None, params=None)

The get-or-create seam every façade wraps its body in.

Nested (a run is already active) → a child span into the SAME manifest, no emit
(the outer owner emits). Enabled + top-level → a new recorder that emits one
manifest on exit. Disabled → the zero-cost `_NULL_RUN`.

### foley.obs.get_tracer(, prefer_otel=True)

Return the effective [`Tracer`](#foley.obs.Tracer) (OTel-backed when available, else no-op).

* **Parameters:**
  **prefer_otel** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When `True` (default) and `opentelemetry` is importable, return
  an `OTelTracer` (itself a free no-op until the host configures an SDK);
  any construction failure falls back to the no-op. `False` forces the stdlib
  [`NoOpTracer`](#foley.obs.NoOpTracer) — the hermetic-test lever (this dev env may have otel).
* **Return type:**
  [`Tracer`](foley.obs.trace.html.md#foley.obs.trace.Tracer)
* **Returns:**
  A [`Tracer`](#foley.obs.Tracer) (never raises).

### foley.obs.ingest_digest(report)

A leak-free digest of an [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) for a manifest.

Records the per-clip **outcomes** (id, status, QC status, notes) + summary counts —
NOT the full `SoundRecord`s. The records carry `caption` (which equals the
raw generation prompt for a generated clip) + `tags` and already live in the meta
store keyed by the id referenced in `result_ids`, so embedding them would both
leak prompt text into the manifest and duplicate data. Duck-typed over the report
(`.summary()` + `.results`) to avoid an obs → index import coupling.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.obs.is_enabled()

Whether observability is on (via [`enable()`](#foley.obs.enable) or `$FOLEY_OBS` in {1,true,yes}).

`force_disabled` (set by [`foley.runtime.offline_scope()`](foley.runtime.html.md#foley.runtime.offline_scope) for a telemetry-off
posture) and a telemetry-off runtime (`$FOLEY_OFFLINE`) hard-override both — so
offline mode’s “nothing leaves the device” contract holds even when `$FOLEY_OBS`
is exported.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.obs.load_run(store, run_id)

Load and typed-rehydrate a [`RunManifest`](#foley.obs.RunManifest) from `store` (the read helper).

* **Return type:**
  [`RunManifest`](foley.obs.run_artifact.html.md#foley.obs.run_artifact.RunManifest)

### foley.obs.redact_text(text, , mode=RedactionMode.hash, salt='foley-obs-v1', preview_chars=0)

Redact one string per `mode`.

* **Parameters:**
  * **text** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The (possibly sensitive) string, or `None`.
  * **mode** ([`RedactionMode`](foley.obs.redact.html.md#foley.obs.redact.RedactionMode)) – `off` → `None`; `full` → `text` verbatim; `hash` (default) →
    `{"sha256": <salted hex>, "len": <n>}` (+ `"preview"` only if
    `preview_chars > 0`).
  * **salt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Salt mixed into the hash (injectable; default fixed for diffability).
  * **preview_chars** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – If > 0 (hash mode), include a leading `text[:preview_chars]`
    preview. Default 0 → **zero content leak**.
* **Returns:**
  `None`, the raw string, or a hash dict — depending on `mode`.

### foley.obs.reset()

Restore the default config (test teardown; clears injected store/tracer/clock).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.run(op='run', , inputs=None, params=None, \*\*overrides)

Open an explicit run scope that aggregates nested façade calls into ONE manifest.

Forces observability on for the scope even when it is merely *disabled* (the #7
`find()` aggregation entrypoint). The one thing it does **not** override is the
hard-off `force_disabled` flag: [`foley.runtime.offline_scope()`](foley.runtime.html.md#foley.runtime.offline_scope) sets it for a
telemetry-off posture, so an explicit `run()` inside offline mode records and
exports **nothing** — the “nothing leaves the device” contract holds on the
`find()`/`weave()` paths too, not just the `facade_run` ones. Get-or-create: a
nested [`run()`](#foley.obs.run) reuses the active recorder. `overrides` are per-scope
[`ObsConfig`](#foley.obs.ObsConfig) fields (e.g. `run_store`, `prefer_otel`, `clock`).

### Modules

| [`recorder`](foley.obs.recorder.html.md#module-foley.obs.recorder)         | The run-recorder: owns the manifest, drives the OTel mirror, off by default (#11).   |
|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`redact`](foley.obs.redact.html.md#module-foley.obs.redact)             | Redaction of sensitive narration / prompt / query text in telemetry (#11).           |
| [`run_artifact`](foley.obs.run_artifact.html.md#module-foley.obs.run_artifact) | The reproducible run-artifact SSOT — `RunManifest` + `SpanRecord` (#11).             |
| [`trace`](foley.obs.trace.html.md#module-foley.obs.trace)               | The OpenTelemetry MIRROR seam for foley's observability (#11).                       |
