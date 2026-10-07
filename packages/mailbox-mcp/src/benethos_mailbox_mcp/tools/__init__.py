"""The tools of the MCP server, one module per kind: ``reading``,
``writing``, ``drafts`` and ``sending``, the kinds ``list_accounts``
reports, and ``accounts`` for ``list_accounts`` itself. Each module
holds its tools and their part of ``TOOLS``, the catalogue.
"""

from __future__ import annotations

from . import accounts, drafts, reading, sending, writing
from .base import MAX_LIMIT, Tool, client, serving, use_client

TOOLS = (
    *accounts.TOOLS,
    *reading.TOOLS,
    *writing.TOOLS,
    *drafts.TOOLS,
    *sending.TOOLS,
)

__all__ = [
    "MAX_LIMIT",
    "TOOLS",
    "Tool",
    "accounts",
    "client",
    "drafts",
    "reading",
    "sending",
    "serving",
    "use_client",
    "writing",
]
