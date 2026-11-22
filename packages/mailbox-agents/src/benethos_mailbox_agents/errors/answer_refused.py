"""The error ``AnswerRefusedError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["AnswerRefusedError"]


class AnswerRefusedError(MailboxAgentError):
    """An answer of the model failed the schema or the gateway refused the
    request. ``reason`` is ``schema`` or ``request``."""

    code = "answer_refused"

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason
