# foley.obs.trace

The OpenTelemetry MIRROR seam for foley’s observability (#11).

foley’s reproducible run-artifact (the [`RunManifest`](foley.obs.run_artifact.html.md#foley.obs.run_artifact.RunManifest))
is built by the recorder from its own clock + id-factory, \*\*independent of any
tracer\*\* — so a bare `pip install foley` still emits a complete manifest with zero
dependencies. This module is *only* the optional OpenTelemetry **mirror**: when the
`foley[obs]` extra is installed, foley additionally emits vendor-neutral OTel GenAI
spans (consumable by Langfuse / Datadog / Honeycomb / …); when it is not, a
stdlib [`NoOpTracer`](#foley.obs.trace.NoOpTracer) makes every instrumentation call a free no-op.

`opentelemetry` is imported **lazily inside** [`OTelTracer`](#foley.obs.trace.OTelTracer) only, never at
module top level, so importing this module (and `import foley`) stays dol-only.
foley never configures an SDK / exporter — that is the host application’s job
(`trace.set_tracer_provider(...)`); until it does, even the OTel-backed tracer is a
free `ProxyTracer` no-op, so instrumentation is safe and ~zero-cost by default.

### Module Attributes

| [`GENAI`](#foley.obs.trace.GENAI)   | The GenAI semantic-convention attribute keys foley emits.   |
|----------------------------------------------------------|-------------------------------------------------------------|

### Functions

| [`get_tracer`](#foley.obs.trace.get_tracer)(\*[, prefer_otel])   | Return the effective [`Tracer`](#foley.obs.trace.Tracer) (OTel-backed when available, else no-op).   |
|----------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|

### Classes

| [`NoOpSpan`](#foley.obs.trace.NoOpSpan)()                 | A zero-cost span: every method does nothing; `trace_id` is always `None`.                                             |
|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`NoOpTracer`](#foley.obs.trace.NoOpTracer)()               | The default [`Tracer`](#foley.obs.trace.Tracer) — yields the shared `_NOOP_SPAN`, zero deps.      |
| [`OTelTracer`](#foley.obs.trace.OTelTracer)()               | An OpenTelemetry-backed [`Tracer`](#foley.obs.trace.Tracer) (lazy import; requires `foley[obs]`). |
| [`Span`](#foley.obs.trace.Span)(\*args, \*\*kwargs)   | The minimal mirror-span surface foley code calls (structural).                                                        |
| [`Tracer`](#foley.obs.trace.Tracer)(\*args, \*\*kwargs) | Starts mirror spans; the DI seam (default no-op, OTel-backed when present).                                           |

### foley.obs.trace.GENAI *= {'data_source_id': 'gen_ai.data_source.id', 'error_type': 'error.type', 'finish_reasons': 'gen_ai.response.finish_reasons', 'input_tokens': 'gen_ai.usage.input_tokens', 'operation': 'gen_ai.operation.name', 'output_tokens': 'gen_ai.usage.output_tokens', 'provider': 'gen_ai.provider.name', 'request_model': 'gen_ai.request.model', 'response_model': 'gen_ai.response.model'}*

The GenAI semantic-convention attribute keys foley emits. HARDCODED as strings on
purpose — the `opentelemetry.semconv._incubating` constants are Development-
stability and shift across minor versions. This dict is the single place they are named.

### *class* foley.obs.trace.NoOpSpan

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A zero-cost span: every method does nothing; `trace_id` is always `None`.

### *class* foley.obs.trace.NoOpTracer

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default [`Tracer`](#foley.obs.trace.Tracer) — yields the shared `_NOOP_SPAN`, zero deps.

#### start_as_current_span(name, , kind=None, attributes=None)

Yield the no-op span (context-manager protocol; nothing is recorded).

### *class* foley.obs.trace.OTelTracer

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An OpenTelemetry-backed [`Tracer`](#foley.obs.trace.Tracer) (lazy import; requires `foley[obs]`).

#### start_as_current_span(name, , kind=None, attributes=None)

Open a real OTel span, mapping `kind` to `SpanKind` and yielding a mirror.

### *class* foley.obs.trace.Span(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

The minimal mirror-span surface foley code calls (structural).

#### record_exception(exc)

Record `exc` on the span.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_attribute(key, value)

Set one attribute on the span.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### set_status(ok, message=None)

Mark the span ok or failed, with an optional message.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.obs.trace.Tracer(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Starts mirror spans; the DI seam (default no-op, OTel-backed when present).

#### start_as_current_span(name, , kind=None, attributes=None)

Start a span named `name` and make it current for the `with` block.

* **Return type:**
  [`ContextManager`](https://docs.python.org/3/library/typing.html#typing.ContextManager)[[`Span`](#foley.obs.trace.Span)]

### foley.obs.trace.get_tracer(, prefer_otel=True)

Return the effective [`Tracer`](#foley.obs.trace.Tracer) (OTel-backed when available, else no-op).

* **Parameters:**
  **prefer_otel** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When `True` (default) and `opentelemetry` is importable, return
  an [`OTelTracer`](#foley.obs.trace.OTelTracer) (itself a free no-op until the host configures an SDK);
  any construction failure falls back to the no-op. `False` forces the stdlib
  [`NoOpTracer`](#foley.obs.trace.NoOpTracer) — the hermetic-test lever (this dev env may have otel).
* **Return type:**
  [`Tracer`](#foley.obs.trace.Tracer)
* **Returns:**
  A [`Tracer`](#foley.obs.trace.Tracer) (never raises).
