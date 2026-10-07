"""What the client raises. Every error is a ``MailboxError``, and its
message says what went wrong in words a person can act on."""

from __future__ import annotations


class MailboxError(Exception):
    """Every failure of the client."""


class ConfigurationError(MailboxError):
    """The client cannot start: no token, or an address it refuses."""


class ServiceUnavailableError(MailboxError):
    """mailbox-service is not running or not reachable."""


class ServiceTimeoutError(MailboxError):
    """mailbox-service took the request but did not answer in time."""


class ApiError(MailboxError):
    """The REST API answered with an error."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{message} ({code}, HTTP {status})")
        self.status = status
        self.code = code
        self.message = message
