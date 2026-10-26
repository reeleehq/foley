"""The OpenTelemetry MIRROR seam for foley's observability (#11).

foley's reproducible run-artifact (the :class:`~foley.obs.run_artifact.RunManifest`)
is built by the recorder from its own clock + id-factory, **independent of any
tracer** — so a bare ``pip install foley`` still emits a complete manifest with zero
dependencies. This module is *only* the optional OpenTelemetry **mirror**: when the
``foley[obs]`` extra is installed, foley additionally emits vendor-neutral OTel GenAI
spans (consumable by Langfuse / Datadog / Honeycomb / …); when it is not, a
stdlib :class:`NoOpTracer` makes every instrumentation call a free no-op.

``opentelemetry`` is imported **lazily inside** :class:`OTelTracer` only, never at
module top level, so importing this module (and ``import foley``) stays dol-only.
foley never configures an SDK / exporter — that is the host application's job
(``trace.set_tracer_provider(...)``); until it does, even the OTel-backed tracer is a
free ``ProxyTracer`` no-op, so instrumentation is safe and ~zero-cost by default.
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from typing import ContextManager, Optional, Protocol, runtime_checkable

from .._version import foley_version as _foley_version

#: The GenAI semantic-convention attribute keys foley emits. HARDCODED as strings on
#: purpose — the ``opentelemetry.semconv._incubating`` constants are Development-
#: stability and shift across minor versions. This dict is the single place they are named.
GENAI = {
    "operation": "gen_ai.operation.name",  # 'embeddings' | 'generate_content'
    "provider": "gen_ai.provider.name",
    "request_model": "gen_ai.request.model",
    "response_model": "gen_ai.response.model",
    "input_tokens": "gen_ai.usage.input_tokens",  # #7 decompose/refine/judge LLM spans
    "output_tokens": "gen_ai.usage.output_tokens",  # #7 decompose/refine/judge LLM spans
    "finish_reasons": "gen_ai.response.finish_reasons",  # #7 LLM stop_reason (STABLE)
    "data_source_id": "gen_ai.data_source.id",  # the index/library id (retrieval)
    "error_type": "error.type",  # STABLE
}


@runtime_checkable
class Span(Protocol):
    """The minimal mirror-span surface foley code calls (structural)."""

    trace_id: Optional[str]

    def set_attribute(self, key: str, value) -> None: ...
    def record_exception(self, exc: BaseException) -> None: ...
    def set_status(self, ok: bool, message: Optional[str] = None) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    """Starts mirror spans; the DI seam (default no-op, OTel-backed when present)."""

    def start_as_current_span(
        self,
        name: str,
        *,
        kind: Optional[str] = None,
        attributes: Optional[dict] = None,
    ) -> "ContextManager[Span]": ...


# ---------------------------------------------------------------------------
# stdlib no-op default (a bare install has NO opentelemetry to lean on)
# ---------------------------------------------------------------------------


class NoOpSpan:
    """A zero-cost span: every method does nothing; ``trace_id`` is always ``None``."""

    trace_id = None

    def set_attribute(self, key: str, value) -> None:  # noqa: D102
        pass

    def record_exception(self, exc: BaseException) -> None:  # noqa: D102
        pass

    def set_status(self, ok: bool, message: Optional[str] = None) -> None:  # noqa: D102
        pass


_NOOP_SPAN = NoOpSpan()


class NoOpTracer:
    """The default :class:`Tracer` — yields the shared :data:`_NOOP_SPAN`, zero deps."""

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        kind: Optional[str] = None,
        attributes: Optional[dict] = None,
    ):
        """Yield the no-op span (context-manager protocol; nothing is recorded)."""
        yield _NOOP_SPAN


_NOOP_TRACER = NoOpTracer()


# ---------------------------------------------------------------------------
# lazy OTel-backed mirror (only touched when foley[obs] is installed)
# ---------------------------------------------------------------------------


class _OTelMirror:
    """Wraps a live OpenTelemetry span behind the :class:`Span` protocol."""

    def __init__(self, span):
        self._span = span

    @property
    def trace_id(self) -> Optional[str]:
        """The 32-hex trace id — only when a recording SDK is configured, else ``None``."""
        ctx = self._span.get_span_context()
        return format(ctx.trace_id, "032x") if ctx.is_valid else None

    def set_attribute(self, key: str, value) -> None:  # noqa: D102
        self._span.set_attribute(key, value)

    def record_exception(self, exc: BaseException) -> None:  # noqa: D102
        self._span.record_exception(exc)

    def set_status(self, ok: bool, message: Optional[str] = None) -> None:  # noqa: D102
        from opentelemetry.trace import Status, StatusCode

        # The caller (RunRecorder) sets the semconv error.type (the exception class
        # name) explicitly; the status description carries only the redacted message.
        self._span.set_status(
            Status(StatusCode.OK) if ok else Status(StatusCode.ERROR, message or "")
        )


class OTelTracer:
    """An OpenTelemetry-backed :class:`Tracer` (lazy import; requires ``foley[obs]``)."""

    def __init__(self):
        from opentelemetry import trace  # lazy: foley[obs]; keeps import foley dol-only

        self._otel = trace.get_tracer("foley", _foley_version())

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        kind: Optional[str] = None,
        attributes: Optional[dict] = None,
    ):
        """Open a real OTel span, mapping ``kind`` to ``SpanKind`` and yielding a mirror."""
        from opentelemetry.trace import SpanKind

        span_kind = (
            getattr(SpanKind, kind, SpanKind.INTERNAL) if kind else SpanKind.INTERNAL
        )
        # foley OWNS exception recording via the mirror (redacted), so disable OTel's
        # auto record_exception / set_status_on_exception to avoid a double event + a
        # raw-message leak on the auto-recorded exception.
        with self._otel.start_as_current_span(
            name,
            kind=span_kind,
            attributes=attributes or {},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            yield _OTelMirror(span)


def _otel_importable() -> bool:
    # NOT cached: find_spec is cheap (called once per top-level run scope) and caching
    # would freeze a bare-install process into the no-op path even after opentelemetry
    # is installed mid-process (or, in tests, across an install/uninstall).
    return importlib.util.find_spec("opentelemetry") is not None


def get_tracer(*, prefer_otel: bool = True) -> Tracer:
    """Return the effective :class:`Tracer` (OTel-backed when available, else no-op).

    Args:
        prefer_otel: When ``True`` (default) and ``opentelemetry`` is importable, return
            an :class:`OTelTracer` (itself a free no-op until the host configures an SDK);
            any construction failure falls back to the no-op. ``False`` forces the stdlib
            :class:`NoOpTracer` — the hermetic-test lever (this dev env may have otel).

    Returns:
        A :class:`Tracer` (never raises).
    """
    if prefer_otel and _otel_importable():
        try:
            return OTelTracer()
        except Exception:  # pragma: no cover - defensive fallback
            return _NOOP_TRACER
    return _NOOP_TRACER
