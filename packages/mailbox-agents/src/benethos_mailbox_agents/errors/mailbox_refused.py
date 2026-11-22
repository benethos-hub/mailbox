"""The error ``MailboxRefusedError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["MailboxRefusedError"]


class MailboxRefusedError(MailboxAgentError):
    """The mailbox service refused a request with a 4xx, its ``status``,
    or the request was not sent, as it could only be refused: no status."""

    code = "mailbox_refused"

    def __init__(self, message: str, *, status: int | None = None, reason: str) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
