"""The error ``LimitReachedError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["LimitReachedError"]


class LimitReachedError(MailboxAgentError):
    """An agent asked for more model calls than its limits allow.
    ``per_day`` tells the daily limit, which passes with the day, from the
    limit per message, which does not."""

    code = "limit_reached"

    def __init__(self, message: str, *, per_day: bool) -> None:
        super().__init__(message)
        self.per_day = per_day
