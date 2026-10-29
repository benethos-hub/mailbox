"""server_status: what runs, and whether it is well. The core comes from
memory and needs no request. With ``details`` it adds the service as this
server last saw it, which the server keeps up to date (``Running``): the
tool asks no one, logs nothing and never fails."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version

from .. import __version__
from .base import Tool, ToolResult, result

NAME = "benethos-mailbox-mcp"
UNKNOWN = "unknown"
# Two spaces per level below ``details:``.
_INDENT = "  "


@dataclass(frozen=True, slots=True)
class Seen:
    """The service as this server's own requests last found it.
    ``reachable`` and ``token_valid`` read yes, no or unknown.
    ``checked`` is the ``time.monotonic()`` of the last request, None for
    none."""

    token_set: bool = False
    reachable: str = UNKNOWN
    checked: float | None = None
    token_valid: str = UNKNOWN
    version: str | None = None


@dataclass(frozen=True, slots=True)
class Running:
    """What one server tells of itself: its transport, since when it
    runs, the service as it saw it and the tools it offers beside this
    one."""

    transport: str = UNKNOWN
    started: float = field(default_factory=time.monotonic)
    seen: Seen = field(default_factory=Seen)
    offered: tuple[str, ...] = ()


# The server whose status tool runs now, set around each call as
# ``base.calling`` sets the client.
_running: ContextVar[Running | None] = ContextVar("running", default=None)


@contextmanager
def reporting(running: Running) -> Iterator[None]:
    """``running`` for the status tool called inside."""
    token = _running.set(running)
    try:
        yield
    finally:
        _running.reset(token)


async def server_status(details: bool = False) -> ToolResult:
    """What this server is and how long it has run: its name and version,
    the transport, Python, the MCP library and the uptime. With `details`
    also the service as this server last saw it: whether it answered and
    how long ago, its version and whether it matches this server's,
    whether it took the token, and the tools offered, of which the client
    may hide some."""
    running = _running.get() or Running()
    return result(answer(running, details, time.monotonic()))


def answer(running: Running, details: bool, now: float) -> str:
    """One field per line, ``key: value``, the core first."""
    lines = [f"{key}: {value}" for key, value in _core(running, now)]
    if details:
        lines += ["details:", f"{_INDENT}upstream:"]
        lines += [
            f"{_INDENT * 2}{key}: {value}" for key, value in _upstream(running, now)
        ]
    return "\n".join(lines)


def _core(running: Running, now: float) -> list[tuple[str, object]]:
    python = sys.version_info
    return [
        ("name", NAME),
        ("version", __version__),
        ("transport", running.transport),
        ("python", f"{python.major}.{python.minor}.{python.micro}"),
        ("mcp", _version_of("mcp")),
        ("uptime_seconds", _seconds(now - running.started)),
    ]


def _upstream(running: Running, now: float) -> list[tuple[str, object]]:
    seen = running.seen
    checked = "never" if seen.checked is None else _seconds(now - seen.checked)
    matches = UNKNOWN if seen.version is None else _yes(seen.version == __version__)
    return [
        ("reachable", seen.reachable),
        ("checked_seconds_ago", checked),
        ("token_set", _yes(seen.token_set)),
        ("service_version", seen.version or UNKNOWN),
        ("versions_match", matches),
        ("token_valid", seen.token_valid),
        ("tools_offered", ", ".join(running.offered) or "none"),
    ]


def _version_of(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return UNKNOWN


def _seconds(span: float) -> int:
    return max(0, int(span))


def _yes(value: bool) -> str:
    return "yes" if value else "no"


TOOLS = (
    Tool(server_status, "Server status", frozenset(), open_world=False, always=True),
)
