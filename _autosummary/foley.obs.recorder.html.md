# foley.obs.recorder

The run-recorder: owns the manifest, drives the OTel mirror, off by default (#11).

This is where the manifest-first design lives. A [`RunRecorder`](#foley.obs.recorder.RunRecorder) builds the
[`RunManifest`](foley.obs.run_artifact.html.md#foley.obs.run_artifact.RunManifest) + its span tree from its own clock +
id-factory — **independent of the tracer** — so the artifact is complete with a total
no-op tracer. The façades reach it through [`facade_run()`](#foley.obs.recorder.facade_run) (a get-or-create,
off-by-default context manager) and [`current_run()`](#foley.obs.recorder.current_run); a #7 `find()` opens an
explicit [`run()`](#foley.obs.recorder.run) scope so nested façade calls aggregate into **one** manifest.

Discipline (mirroring the rest of foley): **off by default** — a plain
`import foley` + a plain `foley.generate(...)` is a byte-for-byte no-op that
touches no store and stays dol-only. `foley.obs.enable()` / `$FOLEY_OBS=1` /
`with foley.obs.run(...)` turn it on. Emitting a manifest needs NO extra (all
stdlib); only the OTel span mirror needs `foley[obs]`. Recording never raises into a
façade — a store-write failure degrades gracefully.

### Functions

| [`configure`](#foley.obs.recorder.configure)(\*\*overrides)             | Apply [`ObsConfig`](#foley.obs.recorder.ObsConfig) overrides WITHOUT flipping `enabled` (the test-injection seam).   |
|---------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| [`current_run`](#foley.obs.recorder.current_run)()                        | The active [`RunRecorder`](#foley.obs.recorder.RunRecorder), or `_NULL_RUN` (for the shared child span).               |
| [`disable`](#foley.obs.recorder.disable)()                            | Turn observability off process-wide (façades revert to a byte-for-byte no-op).                                                     |
| [`enable`](#foley.obs.recorder.enable)(\*\*overrides)                | Turn observability on process-wide (and apply any [`ObsConfig`](#foley.obs.recorder.ObsConfig) overrides).           |
| [`facade_run`](#foley.obs.recorder.facade_run)(op, \*[, inputs, params]) | The get-or-create seam every façade wraps its body in.                                                                             |
| [`is_enabled`](#foley.obs.recorder.is_enabled)()                         | Whether observability is on (via [`enable()`](#foley.obs.recorder.enable) or `$FOLEY_OBS` in {1,true,yes}).       |
| [`reset`](#foley.obs.recorder.reset)()                              | Restore the default config (test teardown; clears injected store/tracer/clock).                                                    |
| [`run`](#foley.obs.recorder.run)([op, inputs, params])            | Open an explicit run scope that aggregates nested façade calls into ONE manifest.                                                  |

### Classes

| [`ObsConfig`](#foley.obs.recorder.ObsConfig)([enabled, force_disabled, ...])        | Process-wide observability configuration (flipped by [`enable()`](#foley.obs.recorder.enable)/[`disable()`](#foley.obs.recorder.disable)).   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`RunRecorder`](#foley.obs.recorder.RunRecorder)(manifest, \*, tracer, redactor, ...) | Builds one `RunManifest` (span tree + composed shapes), tracer-independent.                                                                                                   |

### *class* foley.obs.recorder.ObsConfig(enabled=False, force_disabled=False, redaction_mode=RedactionMode.hash, salt='foley-obs-v1', prefer_otel=True, run_store=None, tracer=None, clock=<built-in function time>, id_factory=<function ObsConfig.<lambda>>, now=<function \_iso_now>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Process-wide observability configuration (flipped by [`enable()`](#foley.obs.recorder.enable)/[`disable()`](#foley.obs.recorder.disable)).

#### clock()

time() -> floating-point number

Return the current time in seconds since the Epoch.
Fractions of a second may be present if the system clock provides them.

#### now()

ISO-8601 UTC timestamp (real wall-clock; overridden to `None` in tests).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.obs.recorder.RunRecorder(manifest, , tracer, redactor, run_store, clock, id_factory)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Builds one `RunManifest` (span tree + composed shapes), tracer-independent.

#### add_candidate_scores(scores)

Append candidate scores to the manifest.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### add_disclosure_ref(sound_id, ref)

Record the disclosure reference for `sound_id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### add_result_ids(ids)

Append result sound ids to the manifest.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### add_seed(sound_id, seed)

Record the (redacted) generation seed for `sound_id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### add_step(step)

Append a SELECT-stage `Step` (#7), deep-redacting `detail` at record time.

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

#### set_credits_ref(credits_manifest)

Record the credits manifest reference.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_error(message)

Mark the manifest as failed with `message`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_ingest_report(report_dict)

Record the ingest report on the manifest.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_inputs(\*\*inputs)

Merge `inputs` into the manifest inputs, redacting sensitive text.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_params(\*\*params)

Merge `params` into the manifest parameters.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_plan_ref(plan_ref)

Fill the reserved #8 `plan_ref` slot (a light join dict — no text).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_status(status)

Set the manifest status.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### span(name, , kind=None, \*\*attributes)

Open a span: append a `SpanRecord` (from our own clock/ids) + mirror it.

### foley.obs.recorder.configure(\*\*overrides)

Apply [`ObsConfig`](#foley.obs.recorder.ObsConfig) overrides WITHOUT flipping `enabled` (the test-injection seam).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.recorder.current_run()

The active [`RunRecorder`](#foley.obs.recorder.RunRecorder), or `_NULL_RUN` (for the shared child span).

### foley.obs.recorder.disable()

Turn observability off process-wide (façades revert to a byte-for-byte no-op).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.recorder.enable(\*\*overrides)

Turn observability on process-wide (and apply any [`ObsConfig`](#foley.obs.recorder.ObsConfig) overrides).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.recorder.facade_run(op, , inputs=None, params=None)

The get-or-create seam every façade wraps its body in.

Nested (a run is already active) → a child span into the SAME manifest, no emit
(the outer owner emits). Enabled + top-level → a new recorder that emits one
manifest on exit. Disabled → the zero-cost `_NULL_RUN`.

### foley.obs.recorder.is_enabled()

Whether observability is on (via [`enable()`](#foley.obs.recorder.enable) or `$FOLEY_OBS` in {1,true,yes}).

`force_disabled` (set by [`foley.runtime.offline_scope()`](foley.runtime.html.md#foley.runtime.offline_scope) for a telemetry-off
posture) and a telemetry-off runtime (`$FOLEY_OFFLINE`) hard-override both — so
offline mode’s “nothing leaves the device” contract holds even when `$FOLEY_OBS`
is exported.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.obs.recorder.reset()

Restore the default config (test teardown; clears injected store/tracer/clock).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.obs.recorder.run(op='run', , inputs=None, params=None, \*\*overrides)

Open an explicit run scope that aggregates nested façade calls into ONE manifest.

Forces observability on for the scope even when it is merely *disabled* (the #7
`find()` aggregation entrypoint). The one thing it does **not** override is the
hard-off `force_disabled` flag: [`foley.runtime.offline_scope()`](foley.runtime.html.md#foley.runtime.offline_scope) sets it for a
telemetry-off posture, so an explicit `run()` inside offline mode records and
exports **nothing** — the “nothing leaves the device” contract holds on the
`find()`/`weave()` paths too, not just the `facade_run` ones. Get-or-create: a
nested [`run()`](#foley.obs.recorder.run) reuses the active recorder. `overrides` are per-scope
[`ObsConfig`](#foley.obs.recorder.ObsConfig) fields (e.g. `run_store`, `prefer_otel`, `clock`).
