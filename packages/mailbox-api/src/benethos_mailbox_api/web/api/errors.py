"""Domain errors to HTTP responses, and the one error envelope.

The only place that knows which error becomes which status code.
"""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ...errors import (
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
from .schemas import ErrorResponse

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

# Documented on every protected route, so generated clients know the shape.
DOCUMENTED_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": text}
    for status, text in {
        401: "Missing or wrong bearer token",
        403: "The caller lacks the right for this operation",
        404: "Account or resource not found",
        501: "The provider cannot do this",
        502: "The provider failed or rejected the credentials",
        503: "No user and no admin key exist yet",
    }.items()
}


def status_of(error: MailboxApiError) -> int:
    for cls, status in STATUS:
        if isinstance(error, cls):
            return status
    return 500


def api_error(exc: MailboxApiError) -> JSONResponse:
    """A domain error as the API answers it: status and envelope."""
    status = status_of(exc)
    headers = None
    if status == 401:
        headers = {"WWW-Authenticate": "Bearer"}
    elif isinstance(exc, RateLimitedError):
        headers = {"Retry-After": str(exc.retry_after)}
    return error_response(status, exc.code, exc.message, headers)


def http_error(exc: HTTPException) -> JSONResponse:
    """Framework errors (auth, unknown route) in the same envelope, so a
    client parses one error shape. Request validation keeps FastAPI's 422
    format, which the schema documents on its own."""
    code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    return error_response(exc.status_code, code, str(exc.detail), exc.headers)


def error_response(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse.model_validate({"error": {"code": code, "message": message}})
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)
