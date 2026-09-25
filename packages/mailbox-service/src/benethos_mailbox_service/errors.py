"""Error hierarchy, shared by every layer.

Cross-cutting like ``config``: imports no layer. An error names what went
wrong with a stable ``code`` and carries no HTTP status. ``web.api.errors`` maps
each class onto one, so the domain and the data layer stay free of HTTP.
"""

from __future__ import annotations


class MailboxServiceError(Exception):
    """Base class of every anticipated failure."""

    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(MailboxServiceError):
    code = "not_found"


class MessageNotFoundError(NotFoundError):
    """The message itself is not where it was said to be. The sync of ids
    acts on this alone, not on a missing attachment, draft or folder."""


class BadRequestError(MailboxServiceError):
    """The request is well-formed but makes no sense, e.g. an unknown right."""

    code = "bad_request"


class UnauthorizedError(MailboxServiceError):
    """No valid credential: missing, wrong, expired, revoked, or user disabled."""

    code = "unauthorized"


class ForbiddenError(MailboxServiceError):
    """The caller may see the account, but not do this."""

    code = "forbidden"


class RecipientNotAllowedError(ForbiddenError):
    """No grant of the caller allows sending to these recipients."""

    code = "recipient_not_allowed"


class SetupRequiredError(MailboxServiceError):
    """The service has no way to authenticate anyone yet."""

    code = "setup_required"


class CredentialError(MailboxServiceError):
    """A stored credential cannot be decrypted."""

    code = "credential_unreadable"


class CredentialMissingError(CredentialError):
    """The account has no credential of the kind its sign-in needs."""

    code = "credential_missing"


class ConflictError(MailboxServiceError):
    """The record collides with what is stored: an id or a unique value
    taken, or a reference to a record that is gone."""

    code = "conflict"


class IdempotencyConflictError(ConflictError):
    """An Idempotency-Key used again with a different request."""

    code = "idempotency_conflict"


class RateLimitedError(MailboxServiceError):
    """The caller asked too often. ``retry_after`` is in seconds."""

    code = "rate_limited"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SendLimitError(RateLimitedError):
    """The caller has sent as many mails in 24 hours as its grants allow."""

    code = "send_limit_reached"


class StorageError(MailboxServiceError):
    """The service's own storage failed: busy, damaged or unreadable."""

    code = "storage_error"


class NotSupportedError(MailboxServiceError):
    """The provider behind an account cannot do what was asked."""

    code = "not_supported"


class ProviderAuthError(MailboxServiceError):
    """The provider rejected the stored credentials. The account needs a reconnect."""

    code = "provider_auth_failed"


class ProviderError(MailboxServiceError):
    """The provider failed or was unreachable."""

    code = "provider_error"


class ProviderUnavailableError(ProviderError):
    """The provider did not answer or dropped the connection. Worth retrying."""

    code = "provider_unavailable"
