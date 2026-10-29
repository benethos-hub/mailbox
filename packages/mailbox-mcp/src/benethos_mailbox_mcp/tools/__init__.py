"""The tools of the MCP server, one module per kind: ``reading``,
``writing``, ``drafts`` and ``sending``, the kinds ``list_accounts``
reports, ``accounts`` for ``list_accounts`` itself, and ``status`` for
``server_status``. Each module holds its tools and their part of
``TOOLS``, the catalogue.
"""

from __future__ import annotations

from . import accounts, drafts, reading, sending, status, writing
from .base import MAX_LIMIT, Tool, calling, client
from .status import Running, Seen, reporting

TOOLS = (
    *accounts.TOOLS,
    *reading.TOOLS,
    *writing.TOOLS,
    *drafts.TOOLS,
    *sending.TOOLS,
    *status.TOOLS,
)

__all__ = [
    "MAX_LIMIT",
    "TOOLS",
    "Running",
    "Seen",
    "Tool",
    "accounts",
    "calling",
    "client",
    "drafts",
    "reading",
    "reporting",
    "sending",
    "status",
    "writing",
]
