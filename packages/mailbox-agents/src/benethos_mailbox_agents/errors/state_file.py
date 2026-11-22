"""The error ``StateFileError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["StateFileError"]


class StateFileError(MailboxAgentError):
    """The state file cannot be read or written: it is no SQLite file, it
    is damaged, or the disk is full. Nothing goes on without it."""

    code = "state_file"
