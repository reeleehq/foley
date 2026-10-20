# foley.obs.run_artifact

The reproducible run-artifact SSOT — `RunManifest` + `SpanRecord` (#11).

Every instrumented foley operation (`generate` / `add_from` / `ingest` /
`search` / `similar` — and, later, a #7 `find()` / #8 `weave()` scope) emits
one [`RunManifest`](#foley.obs.run_artifact.RunManifest): simultaneously the debug **trace** (the span tree), the
reproducible **plan/seed** record (inputs, params, seeds, chosen clips), and the
**provenance** record (credits + disclosure refs) — report 10 §1.3. It is the join
that makes foley debuggable, evaluable, and reproducible; #8’s
`SoundDesignTimeline.run_manifest_ref` will point at `RunManifest.run_id`.

Pure data: both dataclasses subclass [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin), so
`to_dict` / `to_json` / `from_dict` (incl. `spans` rehydrating element-wise to
[`SpanRecord`](#foley.obs.run_artifact.SpanRecord), exactly like `IngestReport.results`) come for free, and adding
fields later (token usage, cost, timings for #7) is schema-safe with no
`SCHEMA_VERSION` bump. The manifest **composes** the existing shapes — it embeds
`IngestReport.to_dict()` and `Credits.manifest` and references `Candidate` ids +
`LicenseRecord` generation fields — it never forks them.

### Functions

| [`emit_run_manifest`](#foley.obs.run_artifact.emit_run_manifest)(store, manifest, \*[, redactor])   | Serialize `manifest` (redacting the payload) and write it to `store`.                                                                  |
|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| [`ingest_digest`](#foley.obs.run_artifact.ingest_digest)(report)                                | A leak-free digest of an [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) for a manifest. |
| [`load_run`](#foley.obs.run_artifact.load_run)(store, run_id)                              | Load and typed-rehydrate a [`RunManifest`](#foley.obs.run_artifact.RunManifest) from `store` (the read helper).                |

### Classes

| [`RunManifest`](#foley.obs.run_artifact.RunManifest)(run_id, op[, created_at, ...])        | The reproducible run-artifact for one foley operation (trace ⊕ plan ⊕ provenance).   |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`SpanRecord`](#foley.obs.run_artifact.SpanRecord)(name, span_id[, parent_id, kind, ...]) | One node of the run's span tree (the trace half of the artifact).                    |
| [`Step`](#foley.obs.run_artifact.Step)(kind[, seq, event_index, span_id, ...])      | One SELECT-stage step of a `find()` run (the plan half of the artifact, #7).         |

### *class* foley.obs.run_artifact.RunManifest(run_id, op, created_at=None, foley_version=None, inputs=dict(), params=dict(), spans=list(), steps=list(), ingest_report=None, result_ids=list(), candidate_scores=list(), credits_ref=None, disclosure_refs=dict(), seeds=dict(), plan_ref=None, trace_ref=None, status='ok', error=None, schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The reproducible run-artifact for one foley operation (trace ⊕ plan ⊕ provenance).

Persisted by [`emit_run_manifest()`](#foley.obs.run_artifact.emit_run_manifest) into a run store keyed by `run_id`.
Sensitive prompt/query text lives redacted (see [`foley.obs.redact`](foley.obs.redact.html.md#module-foley.obs.redact)); chosen
clips are held by reference (`SoundRecord` id) so the manifest stays light and a
trace can be replayed against a fresh index.

### *class* foley.obs.run_artifact.SpanRecord(name, span_id, parent_id=None, kind=None, start_ms=None, duration_ms=None, status='ok', attributes=dict(), events=list(), error=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One node of the run’s span tree (the trace half of the artifact).

Built by the recorder from its own clock + id-factory, independent of any tracer,
so the tree is complete even when the OTel mirror is a total no-op.

### *class* foley.obs.run_artifact.Step(kind, seq=None, event_index=None, span_id=None, status='ok', detail=dict())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One SELECT-stage step of a `find()` run (the plan half of the artifact, #7).

The typed entry type of `RunManifest.steps`: a compact, redacted record of
each `decompose`/`refine`/`search`/`license_gate`/`verify`/`decide`/
`generate`/`place` stage, in `seq` order, with `span_id` joining the step
back to the [`SpanRecord`](#foley.obs.run_artifact.SpanRecord) that timed it. `detail` is a small,
already-redacted dict (event text lives under the `query` key so the redactor
catches it). Rehydrated element-wise by `RunManifest.from_dict()` exactly like
`spans` (see the module docstring).

### foley.obs.run_artifact.emit_run_manifest(store, manifest, , redactor=None)

Serialize `manifest` (redacting the payload) and write it to `store`.

The plain-dict write path keeps an emit-time interposition point for the
belt-and-suspenders redaction sweep (do NOT couple the write to
auto-serialization). Returns the `run_id`.

* **Parameters:**
  * **store** ([`MutableMapping`](https://docs.python.org/3/library/typing.html#typing.MutableMapping)) – A `MutableMapping[str, dict]` (default:
    [`foley.stores.make_run_store()`](foley.stores.html.md#foley.stores.make_run_store); a dict in tests).
  * **manifest** ([`RunManifest`](#foley.obs.run_artifact.RunManifest)) – The [`RunManifest`](#foley.obs.run_artifact.RunManifest) to persist.
  * **redactor** – An optional [`Redactor`](foley.obs.redact.html.md#foley.obs.redact.Redactor) applied to the full
    payload before the write (the emit-time net).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.obs.run_artifact.ingest_digest(report)

A leak-free digest of an [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) for a manifest.

Records the per-clip **outcomes** (id, status, QC status, notes) + summary counts —
NOT the full `SoundRecord`s. The records carry `caption` (which equals the
raw generation prompt for a generated clip) + `tags` and already live in the meta
store keyed by the id referenced in `result_ids`, so embedding them would both
leak prompt text into the manifest and duplicate data. Duck-typed over the report
(`.summary()` + `.results`) to avoid an obs → index import coupling.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.obs.run_artifact.load_run(store, run_id)

Load and typed-rehydrate a [`RunManifest`](#foley.obs.run_artifact.RunManifest) from `store` (the read helper).

* **Return type:**
  [`RunManifest`](#foley.obs.run_artifact.RunManifest)
