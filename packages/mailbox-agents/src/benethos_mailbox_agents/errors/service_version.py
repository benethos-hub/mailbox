"""The error ``ServiceVersionError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["ServiceVersionError"]


class ServiceVersionError(MailboxAgentError):
    """The mailbox service runs a version outside the lines this package
    is tested against, or names none that can be read. Nothing goes on
    against it: what the service does there has not been measured."""

    code = "service_version"
