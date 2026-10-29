"""The MCP server's ``server_status``, both ways, in a session of the
script's own: the core fields in their order, the service as the server
saw it, of this version and taking the token, and no part of the token
in the answer. Nothing is read from a mailbox."""

from __future__ import annotations

from mcp import ClientSession

from .mcp_session import text_of
from .run import Run

CORE = ["name", "version", "transport", "python", "mcp", "uptime_seconds"]


def _fields(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        found[key.strip()] = value.strip()
    return found


def _leaks(text: str, token: str) -> bool:
    """Whether eight characters in a row of ``token`` show in ``text``."""
    return any(token[n : n + 8] in text for n in range(len(token) - 7))


async def check_status(
    run: Run, session: ClientSession, token: str, transport: str
) -> None:
    quick = await session.call_tool("server_status", {})
    said = text_of(quick)
    core = _fields(said)
    run.check(
        f"server_status names the core over {transport}, nothing more",
        not quick.is_error
        and list(core) == CORE
        and core["name"] == "benethos-mailbox-mcp"
        and core["transport"] == transport,
        ", ".join(core),
    )
    detailed = await session.call_tool("server_status", {"details": True})
    found = _fields(text_of(detailed))
    run.check(
        "with details: the service answered, took the token, its version matches",
        not detailed.is_error
        and found.get("reachable") == "yes"
        and found.get("token_valid") == "yes"
        and found.get("service_version") == core["version"]
        and found.get("versions_match") == "yes",
        f"service {found.get('service_version')}, server {core['version']}",
    )
    run.check(
        "server_status shows no part of the token",
        not _leaks(said, token) and not _leaks(text_of(detailed), token),
    )
