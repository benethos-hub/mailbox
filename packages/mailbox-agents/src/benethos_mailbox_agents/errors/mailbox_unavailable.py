"""The error ``MailboxUnavailableError``."""

from __future__ import annotations

from .unavailable import UnavailableError

__all__ = ["MailboxUnavailableError"]


class MailboxUnavailableError(UnavailableError):
    """The mailbox service did not answer, or answered with a 5xx or 429."""

    code = "mailbox_unavailable"
