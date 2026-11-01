# Deploy the MCP server over HTTP

`foley-mcp --http` serves foley's MCP tools (`foley_score`, `foley_search`, `foley_weave`, …) over streamable HTTP, behind a bearer token. It is fail-closed: with no token, or a blank or short one (under 16 characters), it refuses to start, and a request without `Authorization: Bearer <token>` gets a `401`. This page is the reference deployment: a Docker image, a compose file, and what to put around them.

## Quick start

From the repository root:

```bash
export FOLEY_MCP_TOKEN="$(openssl rand -hex 32)"
docker build -f deploy/mcp-http/Dockerfile -t foley-mcp .
docker run --rm -p 127.0.0.1:8000:8000 -e FOLEY_MCP_TOKEN -v foley-data:/data foley-mcp
```

or, with compose (same image, a named volume, restart policy):

```bash
cd deploy/mcp-http
FOLEY_MCP_TOKEN="$(openssl rand -hex 32)" docker compose up -d --build
```

Check it:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/mcp          # 401
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer $FOLEY_MCP_TOKEN" \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

An MCP client connects to `https://<your host>/mcp` with the header `Authorization: Bearer <token>`.

## What is in the image

| Setting | Default | Change it with |
|---|---|---|
| foley extras | `mcp,freesound,openverse,wikimedia-commons` | `--build-arg FOLEY_EXTRAS=...` (add `index,clap,audio,weave` for local CLAP search and weaving; the CLAP model downloads on first use into the volume) |
| system packages | none | `--build-arg APT_PACKAGES="ffmpeg rubberband-cli"`, which weaving needs; `foley.check_requirements()` inside the container lists what is missing |
| data | `/data` (`$FOLEY_DATA_DIR`): library, sessions, runs, provenance | mount a volume there |
| listen | `0.0.0.0:8000`, path `/mcp` | remap the host side (`-p 127.0.0.1:9000:8000`); keep 8000 inside, which the healthcheck probes. `--path` after the image name changes the path |
| user | `foley` (uid 10001), not root | |
| health | an anonymous request must get a `401` | the `HEALTHCHECK` in the Dockerfile |

The healthcheck tests two things at once: that the server answers, and that the gate is closed. A container that served anonymous requests would report unhealthy.

Arguments after the image name (or `command:` in compose) are appended to `foley-mcp --http --host 0.0.0.0 --port 8000`, so `docker run … foley-mcp --offline` runs the local-first posture.

## TLS: put a reverse proxy in front

The app speaks plain HTTP. Publish the container on loopback only (as above and in the compose file) and terminate TLS in a reverse proxy on the same host. With Caddy, for instance:

```
mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy gets and renews the certificate itself. The proxy must not buffer responses: tool results stream back as server-sent events (Caddy and recent nginx with `proxy_buffering off;` are fine). Never expose port 8000 directly on a public interface: the bearer token would travel in clear text.

## Tokens and rotation

`FOLEY_MCP_TOKEN` holds the accepted tokens, separated by whitespace, so a token cannot contain whitespace (a passphrase would be split into words, and each word is refused as too short); `--token` adds more and may be repeated. Prefer the environment (or an env file with tight permissions) to `--token`, which shows in the process list.

To rotate without cutting clients off:

1. Generate the new token and restart with both: `FOLEY_MCP_TOKEN="$OLD $NEW"`.
2. Move every client to `$NEW`.
3. Restart with `FOLEY_MCP_TOKEN="$NEW"` alone.

A token is a full credential for every tool, including the paid ones (`foley_generate`, and the LLM rungs when configured). Give each client its own token so one can be revoked alone.

A fixed bearer token suits clients that let you set a request header (Claude Code, the MCP SDKs, most agent frameworks). Connectors that only speak OAuth, such as claude.ai custom connectors, cannot use it.

## Spending and sensitive narration

- The server has a cumulative spend cap across all paid tool calls for its lifetime (`foley.cost.default_max_usd`: $1, or $3 under `$FOLEY_LLM=anthropic`). Source and LLM keys (`FREESOUND_API_KEY`, `ANTHROPIC_API_KEY`, …) are read from the container environment; leave a key unset and that source or rung is simply unavailable.
- For narration that must not leave the host, run with `--offline` (compose: `command: ["--offline"]`). Only local sources are used, telemetry is off and redaction hashes text, for the server's whole lifetime. `foley_status` reports the posture in force.

## Health and readiness

- Liveness/readiness: the Docker healthcheck (anonymous request → `401`). In Kubernetes, use the same probe with an `exec` command, or an HTTP probe that accepts `401` as success if your platform allows it.
- Logs: uvicorn's access log goes to stdout (`docker logs`), one line per request with its status; `401` lines are refused requests.
- Concurrency: one process, one event loop. Generation and weaving are heavy; if many clients share one server, rate-limit at the proxy (per token or per client IP) rather than scaling the container out, because sessions and the spend cap live in one process.

## Without Docker

```bash
pip install 'foley[mcp]'
FOLEY_MCP_TOKEN="$(openssl rand -hex 32)" foley-mcp --http --host 127.0.0.1 --port 8000
```

or mount it in your own ASGI app with `foley.make_http_app(auth={"bearer_tokens": [...]})`.
