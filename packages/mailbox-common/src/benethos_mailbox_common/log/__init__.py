"""The lines of a log and the secrets kept out of them. Callers import
the modules from here, ``from benethos_mailbox_common.log import lines,
redact``."""

from __future__ import annotations

from . import lines, redact

__all__ = ["lines", "redact"]
