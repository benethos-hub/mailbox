# syntax=docker/dockerfile:1
#
# The service, benethos-mailbox-service. Build context: the repository root, where
# the workspace lockfile lives:
#
#   docker build -f containers/benethos-mailbox-service/Dockerfile .
#
# Only the service package goes into the image, installed from the lockfile
# without the development tools. The MCP server is not part of it.

# Base images are named in FROM directly, so Dependabot can update them.

FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

# --- build: a virtual environment with the service and its dependencies -------
FROM python:3.14-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# The workspace needs every member's pyproject.toml. The lockfile pins all.
COPY pyproject.toml uv.lock ./
COPY packages packages
RUN uv sync --frozen --no-dev --no-editable --package benethos-mailbox-service

# --- runtime -------------------------------------------------------------------
FROM python:3.14-slim

RUN useradd --system --uid 10001 --user-group --home-dir /app \
        --shell /usr/sbin/nologin mailbox \
    && mkdir -p /app /data \
    && chown mailbox:mailbox /data

COPY --from=build /opt/venv /opt/venv

# Configuration comes from the environment only. Inside the container the
# service listens on every interface. The compose file publishes the port on
# the host's loopback address alone (CONCEPT 8.1). The master key is a file,
# mounted as a secret.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MAILBOX_SERVICE_HOST=0.0.0.0 \
    MAILBOX_SERVICE_PORT=8080 \
    MAILBOX_SERVICE_DATA_DIR=/data \
    MAILBOX_SERVICE_STORAGE=sqlite \
    MAILBOX_SERVICE_KEY_PROVIDER=file \
    MAILBOX_SERVICE_KEY_FILE=/run/secrets/master_key

WORKDIR /app
USER mailbox
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"]

ENTRYPOINT ["benethos-mailbox-service"]
CMD ["serve"]
