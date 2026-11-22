"""The error ``ServiceVersionError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["ServiceVersionError"]


class ServiceVersionError(MailboxAgentError):
    """The mailbox service runs another version than the agents take, or
    names none that can be read. Nothing goes on against it: what the
    service does there has not been measured with these agents."""

    code = "service_version"
