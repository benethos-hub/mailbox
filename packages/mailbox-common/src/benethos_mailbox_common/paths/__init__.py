"""Where a program finds its settings and its data, and the lock that
keeps one writer at a time. A group with a library, platformdirs.
Callers import the modules from here,
``from benethos_mailbox_common.paths import folders``."""

from __future__ import annotations

from . import folders, locks

__all__ = ["folders", "locks"]
