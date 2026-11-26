"""Which status a domain error answers with: the one place that knows,
for the JSON API's envelope and the UI's error page alike."""

from __future__ import annotations

from ..errors import (
    BadRequestError,
    ChangesExpiredError,
    ConflictError,
    CredentialError,
    CredentialMissingError,
    ForbiddenError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    RateLimitedError,
    SetupRequiredError,
    StorageUnavailableError,
    UnauthorizedError,
)

# Most specific first: the first matching class decides.
STATUS: list[tuple[type[MailboxServiceError], int]] = [
    (BadRequestError, 400),
    (UnauthorizedError, 401),
    (ForbiddenError, 403),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ChangesExpiredError, 410),
    (RateLimitedError, 429),
    (NotSupportedError, 501),
    (ProviderAuthError, 502),
    (ProviderError, 502),
    (CredentialMissingError, 409),
    (CredentialError, 500),
    (SetupRequiredError, 503),
    (StorageUnavailableError, 503),
]


def retry_after(error: MailboxServiceError) -> int | None:
    """The seconds an answer to ``error`` tells the caller to wait in
    ``Retry-After``: past a limit, and while the database is away."""
    if isinstance(error, RateLimitedError | StorageUnavailableError):
        return error.retry_after
    return None


def status_of(error: MailboxServiceError) -> int:
    for cls, status in STATUS:
        if isinstance(error, cls):
            return status
    return 500
