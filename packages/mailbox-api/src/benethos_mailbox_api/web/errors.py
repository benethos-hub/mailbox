"""Which status a domain error answers with: the one place that knows,
for the JSON API's envelope and the UI's error page alike."""

from __future__ import annotations

from ..errors import (
    BadRequestError,
    ConflictError,
    CredentialError,
    ForbiddenError,
    MailboxApiError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    SetupRequiredError,
    UnauthorizedError,
)

# Most specific first: the first matching class decides.
STATUS: list[tuple[type[MailboxApiError], int]] = [
    (BadRequestError, 400),
    (UnauthorizedError, 401),
    (ForbiddenError, 403),
    (NotFoundError, 404),
    (ConflictError, 409),
    (RateLimitedError, 429),
    (NotSupportedError, 501),
    (ProviderAuthError, 502),
    (ProviderUnavailableError, 502),
    (ProviderError, 502),
    (CredentialError, 500),
    (SetupRequiredError, 503),
]


def status_of(error: MailboxApiError) -> int:
    for cls, status in STATUS:
        if isinstance(error, cls):
            return status
    return 500
