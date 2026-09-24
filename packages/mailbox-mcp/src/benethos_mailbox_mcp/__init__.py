"""MCP server for the Mailbox API, a client of its REST interface."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("benethos-mailbox-mcp")
except PackageNotFoundError:  # pragma: no cover - running from a bare tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
