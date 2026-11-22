"""The error ``UnavailableError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["UnavailableError"]


class UnavailableError(MailboxAgentError):
    """An upstream did not answer. A normal condition: the work waits and
    is taken up again, nothing is decided without it."""

    code = "unavailable"
