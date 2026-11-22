"""The base class of every error of this package."""

from __future__ import annotations

from .redaction import redact

__all__ = ["MailboxAgentError"]


class MailboxAgentError(Exception):
    """Base class of every error this package raises on purpose.

    ``code`` is what a log line may say about the error besides its class.
    The message may quote what an upstream answered, so it is never logged.
    """

    code: str = "error"

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))

    @property
    def message(self) -> str:
        return str(self)
