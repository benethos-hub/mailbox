"""mailbox-common: what the service and the MCP server of Mailbox both
need, held once. Each module stands alone. Callers import the modules,
such as ``benethos_mailbox_common.plaintext``."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("benethos-mailbox-common")
except PackageNotFoundError:  # pragma: no cover - running from a bare tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
