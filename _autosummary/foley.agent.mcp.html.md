# foley.agent.mcp

The MCP surface — foley’s façade as agent-callable tools (py2mcp, #12, report 05/10).

Exposes the SELECT→preview→WEAVE loop to an LLM agent (or any MCP client) as a set of
**JSON-safe** tools built with `py2mcp` (`mk_mcp_server` over stdio). The single rule:
tools take/return only JSON (ids, scores, license summaries, timeline dicts, store keys) —
**never** a [`Candidate`](foley.base.html.md#foley.base.Candidate), a [`WeaveResult`](foley.weave.html.md#foley.weave.WeaveResult), or numpy
audio. Heavy objects stay server-side; audio is referenced by a byte-store key.

The tools are the verbs of [`foley.agent.verbs`](foley.agent.verbs.html.md#module-foley.agent.verbs) (#193), the table the CLI is built
from too; this module serves them (stdio or authenticated HTTP) and re-exports them,
so `mcp.foley_find` and `mcp.TOOLS` keep working.
`py2mcp` / `fastmcp` are imported LAZILY inside [`build_mcp_server()`](#foley.agent.mcp.build_mcp_server) only, so
`import foley` and `import foley.agent` stay dol-only.

### Functions

| [`build_mcp_server`](#foley.agent.mcp.build_mcp_server)(\*[, library, session, ...])   | Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.    |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`make_http_app`](#foley.agent.mcp.make_http_app)(\*, auth[, path, ...])            | Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP. |
| [`serve`](#foley.agent.mcp.serve)(\*[, name, runtime])                      | Build and run the foley MCP server over stdio (blocks); enforces an offline posture. |
| [`serve_http`](#foley.agent.mcp.serve_http)(\*[, host, port, path])              | Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).     |

### foley.agent.mcp.build_mcp_server(, library=None, session='default', runtime=None, byte_store=None, include=None, name='foley', max_usd=None)

Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.

Validates that every source declares a `data_egress` (fail-closed), binds the
injectable library / runtime / byte-store, and hands the resolved tool functions to
`py2mcp.mk_mcp_server`. Never starts a server or touches the network.

* **Parameters:**
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
  * **session** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The default session id.
  * **runtime** – A [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig) (default: the active one).
  * **byte_store** – A `MutableMapping[str, bytes]` for previews / rendered mixes.
  * **include** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Optional subset of tool names to expose.
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP server name.
  * **max_usd** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – The server’s cumulative spend cap across every paid tool call, for
    its lifetime (default [`foley.cost.default_max_usd()`](foley.cost.html.md#foley.cost.default_max_usd): $1, or $3 under
    `$FOLEY_LLM=anthropic`).
* **Returns:**
  A `fastmcp.FastMCP` server.

### foley.agent.mcp.make_http_app(, auth, path='/mcp', json_response=False, library=None, runtime=None, byte_store=None, include=None, name='foley')

Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP.

HTTP exposes the tool surface to the network, so `auth` is \*\*required and
fail-closed\*\*: pass `auth={'bearer_tokens': [...]}` (a non-empty iterable of accepted
tokens) — a request without a matching `Authorization: Bearer <token>` header gets a
`401`. The returned app (a Starlette/ASGI callable) mounts in any ASGI host (uvicorn,
gunicorn, a parent FastAPI). `py2mcp` / `fastmcp` are imported lazily inside
[`build_mcp_server()`](#foley.agent.mcp.build_mcp_server), so `import foley` stays dol-only.

* **Parameters:**
  * **auth** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – `{'bearer_tokens': [...]}` — required; empty/missing raises (fail-closed).
  * **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP HTTP mount path.
  * **json_response** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Return a single JSON response instead of an SSE stream (simple clients).
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – As [`build_mcp_server()`](#foley.agent.mcp.build_mcp_server).
* **Returns:**
  An ASGI application (the bearer-gated MCP HTTP app).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `auth` carries no bearer tokens (no anonymous HTTP access).

### foley.agent.mcp.serve(, name='foley', runtime=None, \*\*kwargs)

Build and run the foley MCP server over stdio (blocks); enforces an offline posture.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.agent.mcp.serve_http(, host='127.0.0.1', port=8000, auth, path='/mcp', \*\*kwargs)

Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).

Wraps [`make_http_app()`](#foley.agent.mcp.make_http_app) and runs it with uvicorn. `auth` is required (fail-closed).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
