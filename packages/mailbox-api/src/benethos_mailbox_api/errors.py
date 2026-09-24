"""Error hierarchy, shared by every layer.

Cross-cutting like ``config``: imports no layer. An error names what went
wrong with a stable ``code`` and carries no HTTP status. ``web.errors`` maps
each class onto one, so the domain and the data layer stay free of HTTP.
"""

from __future__ import annotations


class MailboxApiError(Exception):
    """Base class of every anticipated failure."""

    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(MailboxApiError):
    code = "not_found"


class ConflictError(MailboxApiError):
    code = "conflict"


class NotSupportedError(MailboxApiError):
    """The provider behind an account cannot do what was asked."""

    code = "not_supported"


class ProviderAuthError(MailboxApiError):
    """The provider rejected the stored credentials. The account needs a reconnect."""

    code = "provider_auth_failed"


class ProviderError(MailboxApiError):
    """The provider failed or was unreachable."""

    code = "provider_error"
