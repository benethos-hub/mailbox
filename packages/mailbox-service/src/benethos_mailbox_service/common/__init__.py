"""Cross-cutting helpers, like ``config`` and ``errors``: read by every layer.

Helpers that know no layer, with no I/O and no state beyond what a
caller holds: mostly what more than one layer needs (docs/ARCHITECTURE.md
2, a guide). They import the standard library and anyio, nothing else:
no layer, no other library. What the MCP server needs as well lives in
the package ``benethos_mailbox_common``.
"""
