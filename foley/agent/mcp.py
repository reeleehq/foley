"""The MCP surface — foley's façade as agent-callable tools (py2mcp, #12, report 05/10).

Exposes the SELECT→preview→WEAVE loop to an LLM agent (or any MCP client) as a set of
**JSON-safe** tools built with ``py2mcp`` (``mk_mcp_server`` over stdio). The single rule:
tools take/return only JSON (ids, scores, license summaries, timeline dicts, store keys) —
**never** a :class:`~foley.base.Candidate`, a :class:`~foley.weave.WeaveResult`, or numpy
audio. Heavy objects stay server-side; audio is referenced by a byte-store key.

The tools are the verbs of :mod:`foley.agent.verbs` (#193), the table the CLI is built
from too; this module serves them (stdio or authenticated HTTP) and re-exports them,
so ``mcp.foley_find`` and ``mcp.TOOLS`` keep working.
``py2mcp`` / ``fastmcp`` are imported LAZILY inside :func:`build_mcp_server` only, so
``import foley`` and ``import foley.agent`` stay dol-only.
"""

from __future__ import annotations

from typing import Optional

from . import verbs as _verbs
from .verbs import (  # re-exported: the verbs and their state live in foley.agent.verbs (#193)
    foley_find,
    foley_search,
    foley_similar_to,
    foley_preview,
    foley_refine,
    foley_pick,
    foley_drop_pick,
    foley_reject,
    foley_list_picks,
    foley_generate,
    foley_plan,
    foley_weave,
    foley_swap_clip,
    foley_set_gain,
    foley_nudge,
    foley_toggle,
    foley_set_master,
    foley_timeline_captions,
    foley_score,
    foley_guide,
    foley_capabilities,
    foley_status,
    Verb,
    VERBS,
    TOOLS,
    surface_snapshot,
    _STATE,
    _configure,
    _BUDGET_LOCK,
    _server_budget,
    _lib,
    _session,
    _byte_store,
    _runtime,
    _enum,
    _LICENSE_ROW_FIELDS,
    _license_summary,
    _candidate_row,
    _weave_result_row,
    _in_library,
    _timeline_of,
    _invalid_on_bad_input,
    _tl_op,
    _GUIDE,
    _invalid,
)


def _resolve_tools(*, include: "Optional[list[str]]" = None) -> list:
    """The tool list, optionally subset by name (``include``).

    Raises:
        ValueError: If ``include`` names a tool that does not exist (a typo would
            otherwise serve a smaller surface than asked for, silently).
    """
    tools = [v.fn for v in _verbs.VERBS if v.mcp]  # read now: a verb added is served
    if include is not None:
        by_name = {fn.__name__: fn for fn in tools}
        unknown = [n for n in include if n not in by_name]
        if unknown:
            raise ValueError(f"no such foley MCP tool(s): {unknown}; see mcp.TOOLS")
        tools = [by_name[n] for n in include]
    return [_under_bound_runtime(fn) for fn in tools]


def _under_bound_runtime(fn):
    """Run a tool under the server's bound runtime (so offline holds in every call).

    ``build_mcp_server(runtime=RuntimeConfig.offline_local())`` binds a posture; tool
    calls run in a threadpool or on tasks, whose context may not carry it, so each
    call re-enters it (model loads, sources and LLM rungs all read
    :func:`foley.runtime.current_runtime`).
    """
    import functools

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        runtime = _STATE["runtime"]
        if runtime is None or not runtime.offline:
            return fn(*args, **kwargs)
        from ..runtime import current_runtime, runtime_scope

        if current_runtime() == runtime:
            return fn(*args, **kwargs)
        # The ContextVar only: safe from many worker threads at once (offline_scope
        # would save/restore process-wide obs settings out of order).
        with runtime_scope(runtime):
            return fn(*args, **kwargs)

    return wrapped


def build_mcp_server(
    *,
    library=None,
    session: str = "default",
    runtime=None,
    byte_store=None,
    include: "Optional[list[str]]" = None,
    name: str = "foley",
    max_usd: "Optional[float]" = None,
):
    """Build the foley MCP server (lazy ``py2mcp``); registers the JSON-safe tool surface.

    Validates that every source declares a ``data_egress`` (fail-closed), binds the
    injectable library / runtime / byte-store, and hands the resolved tool functions to
    ``py2mcp.mk_mcp_server``. Never starts a server or touches the network.

    Args:
        library: The :class:`foley.index.SoundLibrary` (default: the shared one).
        session: The default session id.
        runtime: A :class:`foley.runtime.RuntimeConfig` (default: the active one).
        byte_store: A ``MutableMapping[str, bytes]`` for previews / rendered mixes.
        include: Optional subset of tool names to expose.
        name: The MCP server name.
        max_usd: The server's cumulative spend cap across every paid tool call, for
            its lifetime (default :func:`foley.cost.default_max_usd`: $1, or $3 under
            ``$FOLEY_LLM=anthropic``).

    Returns:
        A ``fastmcp.FastMCP`` server.
    """
    from ..sources.registry import _validate_egress

    _validate_egress()
    _configure(library=library, runtime=runtime, byte_store=byte_store, max_usd=max_usd)
    _STATE["default_session"] = session
    from py2mcp import mk_mcp_server  # lazy: foley[mcp]

    return mk_mcp_server(_resolve_tools(include=include), name=name)


def _run_server(server, runtime) -> None:
    """Run ``server`` under the runtime's obs posture (offline → telemetry hard-off).

    Factored out of :func:`serve` so the offline-posture enforcement is unit-testable
    without a blocking stdio loop: when ``runtime`` is a telemetry-off (offline) posture,
    the whole serve loop runs inside :func:`foley.runtime.offline_scope`, so the
    ``--offline`` promise of "no telemetry" is actually enforced for the server's
    lifetime (with :func:`foley.obs.recorder.run` now honoring ``force_disabled``, this
    silences the ``find`` / ``weave`` paths too, not only the ``facade_run`` ones).
    """
    if runtime is not None and (runtime.offline or not runtime.telemetry):
        from ..runtime import offline_scope

        with offline_scope(runtime):
            server.run()
    else:
        server.run()


def serve(
    *, name: str = "foley", runtime=None, **kwargs
) -> None:  # pragma: no cover - blocking I/O
    """Build and run the foley MCP server over stdio (blocks); enforces an offline posture."""
    _run_server(build_mcp_server(name=name, runtime=runtime, **kwargs), runtime)


# ---------------------------------------------------------------------------
# authenticated HTTP transport (remote MCP deployment)
# ---------------------------------------------------------------------------


class _BearerAuthASGI:
    """Minimal ASGI middleware gating HTTP requests behind a bearer token (fail-closed).

    Non-HTTP scopes (``lifespan`` / ``websocket``) pass through untouched so the wrapped
    Starlette app's startup/shutdown still runs; an HTTP request without a valid
    ``Authorization: Bearer <token>`` header gets a ``401``. Transport-agnostic and
    independent of any fastmcp auth-provider API, so it stays robust across versions.
    """

    def __init__(self, app, tokens):
        self._app = app
        self._tokens = frozenset(tokens)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(b"authorization", b"").decode("latin-1")
        token = raw[7:].strip() if raw[:7].lower() == "bearer " else ""
        if token not in self._tokens:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send(
                {"type": "http.response.body", "body": b'{"error":"unauthorized"}'}
            )
            return
        await self._app(scope, receive, send)


def make_http_app(
    *,
    auth: dict,
    path: str = "/mcp",
    json_response: bool = False,
    library=None,
    runtime=None,
    byte_store=None,
    include: "Optional[list[str]]" = None,
    name: str = "foley",
):
    """Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP.

    HTTP exposes the tool surface to the network, so ``auth`` is **required and
    fail-closed**: pass ``auth={'bearer_tokens': [...]}`` (a non-empty iterable of accepted
    tokens) — a request without a matching ``Authorization: Bearer <token>`` header gets a
    ``401``. The returned app (a Starlette/ASGI callable) mounts in any ASGI host (uvicorn,
    gunicorn, a parent FastAPI). ``py2mcp`` / ``fastmcp`` are imported lazily inside
    :func:`build_mcp_server`, so ``import foley`` stays dol-only.

    Args:
        auth: ``{'bearer_tokens': [...]}`` — required; empty/missing raises (fail-closed).
        path: The MCP HTTP mount path.
        json_response: Return a single JSON response instead of an SSE stream (simple clients).
        library / runtime / byte_store / include / name: As :func:`build_mcp_server`.

    Returns:
        An ASGI application (the bearer-gated MCP HTTP app).

    Raises:
        ValueError: If ``auth`` carries no bearer tokens (no anonymous HTTP access).
    """
    tokens = set((auth or {}).get("bearer_tokens") or [])
    if not tokens:
        raise ValueError(
            "make_http_app/serve_http requires auth={'bearer_tokens': [...]} — HTTP exposes "
            "the tools to the network, so it is fail-closed (no anonymous access)."
        )
    server = build_mcp_server(
        library=library,
        runtime=runtime,
        byte_store=byte_store,
        include=include,
        name=name,
    )
    app = server.http_app(path=path, transport="http", json_response=json_response)
    return _BearerAuthASGI(app, tokens)


def serve_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    auth: dict,
    path: str = "/mcp",
    **kwargs,
) -> None:  # pragma: no cover - blocking I/O
    """Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).

    Wraps :func:`make_http_app` and runs it with uvicorn. ``auth`` is required (fail-closed).
    """
    import uvicorn

    uvicorn.run(make_http_app(auth=auth, path=path, **kwargs), host=host, port=port)


def _cli(argv: "Optional[list[str]]" = None) -> int:  # pragma: no cover - entry point
    """``foley-mcp`` console entry: serve foley over MCP (stdio)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="foley-mcp", description="Serve foley to agents over MCP (stdio or HTTP)."
    )
    parser.add_argument("--name", default="foley")
    parser.add_argument("--session", default="default")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="local-first: no external sources / telemetry",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve over authenticated streamable HTTP instead of stdio",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port")
    parser.add_argument(
        "--token",
        action="append",
        default=None,
        help="accepted bearer token (repeatable); required with --http. Falls back to "
        "$FOLEY_MCP_TOKEN.",
    )
    parser.add_argument("--path", default="/mcp", help="HTTP mount path")
    args = parser.parse_args(argv)
    runtime = None
    if args.offline:
        from ..runtime import RuntimeConfig

        runtime = RuntimeConfig.offline_local()
    if args.http:
        import os

        tokens = list(args.token or [])
        env_token = os.environ.get("FOLEY_MCP_TOKEN")
        if env_token:
            tokens.append(env_token)
        if not tokens:
            parser.error(
                "--http requires --token TOKEN (or $FOLEY_MCP_TOKEN) — fail-closed"
            )
        serve_http(
            host=args.host,
            port=args.port,
            auth={"bearer_tokens": tokens},
            path=args.path,
            session=args.session,
            runtime=runtime,
            name=args.name,
        )
        return 0
    serve(name=args.name, session=args.session, runtime=runtime)
    return 0
