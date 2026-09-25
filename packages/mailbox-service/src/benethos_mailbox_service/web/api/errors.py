"""Domain errors as the API answers them: the status (``web.errors``) and
the one error envelope."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ...errors import MailboxServiceError, RateLimitedError
from ..errors import status_of
from .schemas import ErrorResponse

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


def api_error(exc: MailboxServiceError) -> JSONResponse:
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
    format, which the schema documents on its own (``validation_error``)."""
    code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    return error_response(exc.status_code, code, str(exc.detail), exc.headers)


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
