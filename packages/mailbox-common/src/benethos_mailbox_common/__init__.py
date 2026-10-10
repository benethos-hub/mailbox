"""mailbox-common: what the service and the MCP server of Mailbox both
need, held once, in groups, one per concern: ``mail``, ``log``, ``paths``
and ``values``. A module imports only inside its group, so a group can
be cut out as a package of its own. Callers import a module from its
group, ``from benethos_mailbox_common.log import lines``, never deeper.
This file imports no group."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("benethos-mailbox-common")
except PackageNotFoundError:  # pragma: no cover - running from a bare tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
