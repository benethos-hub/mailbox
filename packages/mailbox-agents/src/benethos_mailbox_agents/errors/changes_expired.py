"""The error ``ChangesExpiredError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["ChangesExpiredError"]


class ChangesExpiredError(MailboxAgentError):
    """The stored feed state is older than the service keeps changes for."""

    code = "changes_expired"
