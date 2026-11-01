# Reference image for the authenticated HTTP MCP server (foley-mcp --http, #36/#42).
# Build from the repository root:
#   docker build -f deploy/mcp-http/Dockerfile -t foley-mcp .
# Run (the token is required, fail-closed):
#   docker run --rm -p 127.0.0.1:8000:8000 -e FOLEY_MCP_TOKEN="$(openssl rand -hex 32)" \
#     -v foley-data:/data foley-mcp
# Guide: misc/docs/deploy-mcp-http.md
FROM python:3.12-slim

# Which foley extras to install. The default serves the tools and the keyless/keyed
# retrieve sources; add e.g. "index,clap,audio,weave" for local CLAP search and weaving.
ARG FOLEY_EXTRAS="mcp,freesound,openverse,wikimedia-commons"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FOLEY_DATA_DIR=/data

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY foley ./foley
RUN pip install ".[${FOLEY_EXTRAS}]" \
    && useradd --system --uid 10001 --home-dir /data foley \
    && mkdir -p /data && chown foley /data

USER foley
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000

# Healthy = the server answers AND the gate is closed: an anonymous request must get a 401.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request as u, urllib.error as e\ntry:\n    u.urlopen('http://127.0.0.1:8000/mcp', timeout=4)\nexcept e.HTTPError as err:\n    sys.exit(err.code != 401)\nexcept Exception:\n    sys.exit(1)\nsys.exit(1)"]

# Bind all interfaces inside the container; publish the port on loopback only and put a
# TLS-terminating reverse proxy in front (the app speaks plain HTTP).
ENTRYPOINT ["foley-mcp", "--http", "--host", "0.0.0.0", "--port", "8000"]
