"""Domain errors as the API answers them: the status (``web.errors``) and
the one error envelope."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from benethos_mailbox_common.redact import redact

from ...errors import MailboxServiceError, RateLimitedError
from ..errors import status_of
from .schemas import ErrorResponse

# What each status means, documented so generated clients know the shape.
_MEANINGS = {
    400: "The request is not valid, e.g. a cursor or a right",
    401: "Missing or wrong bearer token",
    403: "The caller lacks the right for this operation",
    404: "Account or resource not found",
    409: "The request conflicts with what is stored, e.g. a name taken",
    413: "The request body is larger than the service takes (`payload_too_large`)",
    429: "Too many requests from this token, session or address "
    "(`rate_limited`), see Retry-After",
    500: "A stored credential cannot be read, or the service's own database "
    "failed (`credential_unreadable`, `storage_error`)",
    501: "The provider cannot do this",
    502: "The provider failed or rejected the credentials",
    503: "No user exists yet",
}


def documented(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The responses a router declares, each with the error envelope."""
    return {
        status: {"model": ErrorResponse, "description": _MEANINGS[status]}
        for status in statuses
    }


# Every protected route can answer these: the web layer refuses a
# request before the resource is looked at, and the store may fail.
COMMON = (400, 401, 403, 413, 429, 500, 503)
# The caller itself and the catalogue: no record, no provider.
CALLER_ERRORS = documented(*COMMON)
# Records the service keeps: users, roles, tokens, webhooks, the audit.
RECORD_ERRORS = documented(*COMMON, 404, 409)
# Accounts and their mail: a provider is asked.
ACCOUNT_ERRORS = documented(*COMMON, 404, 409, 501, 502)


# The change feed answers 410 for a point it no longer knows.
CHANGES_ERRORS: dict[int | str, dict[str, Any]] = {
    410: {
        "model": ErrorResponse,
        "description": (
            "The state is unknown or older than the changes kept "
            "(`changes_expired`). Start again without `since`."
        ),
    }
}

# A grant may narrow sending (CONCEPT 7.5).
SEND_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ErrorResponse,
        "description": (
            "The caller lacks the right, or no grant allows these recipients "
            "(`recipient_not_allowed`)"
        ),
    },
    429: {
        "model": ErrorResponse,
        "description": "The grant's send limit is reached (`send_limit_reached`), "
        "see Retry-After",
    },
}


def api_error(exc: MailboxServiceError) -> JSONResponse:
    """A domain error as the API answers it: status and envelope."""
    status = status_of(exc)
    headers = None
    if status == 401:
        headers = {"WWW-Authenticate": "Bearer"}
    elif isinstance(exc, RateLimitedError):
        headers = {"Retry-After": str(exc.retry_after)}
    return error_response(status, exc.code, redact(exc.message), headers)


def http_error(exc: HTTPException) -> JSONResponse:
    """Framework errors (auth, unknown route) in the same envelope, so a
    client parses one error shape. Request validation keeps FastAPI's 422
    format, which the schema documents on its own (``validation_error``)."""
    code = _CODES.get(exc.status_code) or HTTPStatus(
        exc.status_code
    ).phrase.lower().replace(" ", "_")
    return error_response(exc.status_code, code, str(exc.detail), exc.headers)


# Codes that do not follow the reason phrase, which differs between
# Python versions for 413.
_CODES = {413: "payload_too_large"}


def validation_error(exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 shape, ``{"detail": [{"type", "loc", "msg"}]}``, without
    the ``input`` and ``ctx`` fields the default handler adds. Those repeat
    the request, and a request may carry a password: a body that fails
    validation must not come back in the answer, where proxies and client
    logs keep it."""
    detail = [
        {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def error_response(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse.model_validate({"error": {"code": code, "message": message}})
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)
