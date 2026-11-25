# The image of every agent, built from the repository root, which is the
# build context:
#
#   docker build -f containers/images/mailbox-agents/Dockerfile .
#
# One image for all agents: a container runs one of them, named in its
# command, `worker --agent <name>`. Two stages, after one that only holds
# the uv binary. The first installs the locked dependencies and this
# package into a virtual environment, the second copies that environment
# into an image without build tools, lockfile or sources.
#
# Both images it starts from are pinned by digest as well as tag. A tag is a
# pointer its publisher can move, the digest is the content itself, so a
# rebuild of the same commit gets the same bytes. uv has a stage of its own
# so a dependency bot that reads FROM lines sees it.

# ---- uv: only the source of the binary -------------------------------------
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

# ---- builder ---------------------------------------------------------------
FROM python:3.15-slim@sha256:63bb298d2b7b88f176f51b5189f54ce6535c997682ea70885d2132f5d473a8a5 AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

# The workspace needs every member's pyproject.toml. The lockfile pins all.
# The package is installed as a real wheel rather than an editable install,
# so /opt/venv is self-contained and can simply be copied.
COPY pyproject.toml uv.lock ./
COPY packages packages
RUN uv sync --frozen --no-dev --no-editable --package benethos-mailbox-agents

# ---- runtime ---------------------------------------------------------------
FROM python:3.15-slim@sha256:63bb298d2b7b88f176f51b5189f54ce6535c997682ea70885d2132f5d473a8a5 AS runtime

# The state file lives in /data, a volume of each agent's own. The metrics
# port binds every address of the container, since a published port reaches
# the container's address and never its loopback. Who may reach it is
# decided where it is published. No token and no key is baked in: compose
# mounts them as files and names them in *_FILE settings.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    MAILBOX_AGENTS_DATA_DIR=/data \
    MAILBOX_AGENTS_METRICS_PORT=9464

# A non-root user that owns what it writes.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /data \
    && chown agent:agent /data

COPY --from=builder /opt/venv /opt/venv

# By its id, so whatever starts the image can tell it is not root without
# reading the image's user list.
USER 10001
WORKDIR /data

EXPOSE 9464
VOLUME ["/data"]

# The health check names the agent, so it is set per service in compose:
#   benethos-mailbox-agents health --agent <name>
ENTRYPOINT ["benethos-mailbox-agents"]
CMD ["--help"]
