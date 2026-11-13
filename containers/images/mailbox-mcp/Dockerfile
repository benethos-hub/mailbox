# syntax=docker/dockerfile:1
#
# The MCP server, benethos-mailbox-mcp, over streamable HTTP. Build context:
# the repository root, where the workspace lockfile lives:
#
#   docker build -f containers/images/mailbox-mcp/Dockerfile .
#
# Only the MCP package, the client it is built on and the common package
# go into the image. It reaches mail through the REST API of the service
# alone (MAILBOX_SERVICE_URL, MAILBOX_SERVICE_TOKEN).

# Base images are named in FROM directly, each by its tag and the digest
# of that tag, so a build is reproducible and Dependabot updates both,
# also when an image is rebuilt under the same tag.

FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

# --- build: a virtual environment with the MCP server and its dependencies ----
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# The workspace needs every member's pyproject.toml. The lockfile pins all.
COPY pyproject.toml uv.lock ./
COPY packages packages
RUN uv sync --frozen --no-dev --no-editable --package benethos-mailbox-mcp

# --- runtime -------------------------------------------------------------------
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

RUN useradd --system --uid 10001 --user-group --home-dir /app \
        --shell /usr/sbin/nologin mailbox \
    && mkdir -p /app

COPY --from=build /opt/venv /opt/venv

# Streamable HTTP on every interface inside the container. The compose file
# publishes the port on the host's loopback address alone. Set
# MAILBOX_MCP_BEARER_TOKEN, and MAILBOX_MCP_ALLOWED_HOSTS to the Host values
# clients use. MAILBOX_SERVICE_TOKEN is the token of the user the server acts as.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MAILBOX_MCP_TRANSPORT=streamable-http \
    MAILBOX_MCP_HOST=0.0.0.0 \
    MAILBOX_MCP_PORT=8000 \
    MAILBOX_MCP_PATH=/mcp \
    MAILBOX_MCP_LOG_LEVEL=INFO

WORKDIR /app
USER 10001
EXPOSE 8000

# The port accepts connections. Every HTTP request needs the bearer token,
# so the check stays below HTTP.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ.get('MAILBOX_MCP_PORT', '8000'))), 3).close()"]

ENTRYPOINT ["benethos-mailbox-mcp"]
