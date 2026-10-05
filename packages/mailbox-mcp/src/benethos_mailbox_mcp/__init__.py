"""mailbox-mcp, the MCP server of Mailbox: a client of the REST
interface of mailbox-service."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("benethos-mailbox-mcp")
except PackageNotFoundError:  # pragma: no cover - running from a bare tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
