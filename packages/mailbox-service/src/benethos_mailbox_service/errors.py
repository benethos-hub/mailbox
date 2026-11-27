"""Error hierarchy, shared by every layer.

Cross-cutting like ``config``: imports no layer. An error names what went
wrong with a stable ``code`` and carries no HTTP status. ``web.api.errors`` maps
each class onto one, so the domain and the data layer stay free of HTTP.
"""

from __future__ import annotations

from benethos_mailbox_common.storage import errors as storage_errors


class MailboxServiceError(Exception):
    """Base class of every anticipated failure."""

    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def noting(self, note: str) -> MailboxServiceError:
        """The same failure, with what is so now added to its message, as
        a step that failed after another one was done."""
        self.message = f"{self.message}: {note}"
        self.args = (self.message,)
        return self


class NotFoundError(MailboxServiceError, storage_errors.NotFoundError):
    code = "not_found"


class MessageNotFoundError(NotFoundError):
    """The message itself is not where it was said to be. The sync of ids
    acts on this alone, not on a missing attachment, draft or folder."""


def missing(what: str, name: str | None = None) -> NotFoundError:
    """``<what> <name> not found``: a record or an item that is not there."""
    return NotFoundError(f"{what} {name} not found" if name else f"{what} not found")


def missing_message(name: str | None = None) -> MessageNotFoundError:
    """``message <name> not found``, as ``missing`` for a message."""
    return MessageNotFoundError(
        f"message {name} not found" if name else "message not found"
    )


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


class ConflictError(MailboxServiceError, storage_errors.ConflictError):
    """The record collides with what is stored: an id or a unique value
    taken, or a reference to a record that is gone."""

    code = "conflict"


class ChangesExpiredError(MailboxServiceError):
    """A point in the change feed older than the changes kept, or one this
    service never handed out. The client starts again from a new state."""

    code = "changes_expired"


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


class StorageError(MailboxServiceError, storage_errors.StorageError):
    """The service's own storage failed: busy, damaged or unreadable."""

    code = "storage_error"


class StorageInUseError(StorageError, storage_errors.StorageInUseError):
    """A running service holds the lock of the database on a server."""


class SchemaNotEmptyError(StorageError, storage_errors.SchemaNotEmptyError):
    """A schema on a server that holds tables, where a restore or a move
    goes into an empty one only."""


class StorageUnavailableError(StorageError, storage_errors.StorageUnavailableError):
    """The service's own database cannot be reached, for now. Its message
    is the same whatever happened: ``cause`` says what, for the log
    alone, and ``retry_after`` the seconds until the next attempt."""

    code = "service_unavailable"
    MESSAGE = "the service is not available at the moment"

    def __init__(self, retry_after: int, cause: str = "") -> None:
        super().__init__(self.MESSAGE)
        self.retry_after = retry_after
        self.cause = cause


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


class OutcomeUnknownError(ProviderUnavailableError):
    """The request went out and the answer did not come: whether the
    provider did what it asked cannot be told. A caller sees the same as
    for a provider away. The outbox does not simply send again."""


# What the storage of mailbox-common raises for the service: its own
# classes, each a subclass of the one of the storage.
STORAGE_ERRORS = storage_errors.Errors(
    failed=StorageError,
    conflict=ConflictError,
    missing=missing,
    in_use=StorageInUseError,
    not_empty=SchemaNotEmptyError,
    unavailable=StorageUnavailableError,
)
