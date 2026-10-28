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

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# --- build: a virtual environment with the MCP server and its dependencies ----
FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS build
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
FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913

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
USER mailbox
EXPOSE 8000

# The port accepts connections. Every HTTP request needs the bearer token,
# so the check stays below HTTP.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ.get('MAILBOX_MCP_PORT', '8000'))), 3).close()"]

ENTRYPOINT ["benethos-mailbox-mcp"]
