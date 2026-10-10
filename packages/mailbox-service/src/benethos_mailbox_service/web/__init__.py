"""Web layer: HTTP and nothing else.

Two front ends on one domain: ``api`` serves the JSON API under ``/v1``
(and ``/health``), ``pages`` the configuration UI under ``/ui``. Both check
input, call the domain and answer. Neither decides what a caller may do.
FastAPI is imported here and nowhere below. May import ``domain`` and
``data``.

This module only puts the two together, and sends an error to the front
end whose request failed: a page for the UI, the error envelope for the
API.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException

from benethos_mailbox_common.log import redact

from ..errors import MailboxServiceError, RateLimitedError
from . import api, pages
from .api.errors import api_error, http_error, validation_error
from .errors import status_of
from .limits import BodyLimit, RequestLimit, RequestLimits
from .pages.errors import error_page
from .pages.session import carries_session
from .state import app_settings


def install(app: FastAPI) -> None:
    api.install(app)
    pages.install(app)
    app.state.request_limits = RequestLimits.of(app_settings(app))
    app.add_middleware(BodyLimit)
    # Added last, so it runs first: a refused request is not read.
    app.add_middleware(RequestLimit, credential=_credential, refuse=_answer)

    @app.exception_handler(MailboxServiceError)
    async def _domain_error(request: Request, exc: MailboxServiceError) -> Response:
        return _answer(request, exc)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> Response:
        if pages.owns(request):
            return error_page(request, exc.status_code, str(exc.detail))
        return http_error(exc)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> Response:
        if pages.owns(request):
            return error_page(
                request,
                400,
                "Some fields were missing or not valid. Go back and check them.",
                title="Incomplete form",
            )
        return validation_error(exc)


def _answer(request: Request, exc: MailboxServiceError) -> Response:
    """A domain error as the front end of the request answers it."""
    if not pages.owns(request):
        return api_error(exc)
    page = error_page(request, status_of(exc), redact.redact(exc.message))
    if isinstance(exc, RateLimitedError):
        page.headers["Retry-After"] = str(exc.retry_after)
    return page


def _credential(request: Request) -> bool:
    """Whether a request carries a credential, counted where it is checked:
    a known session for the UI, a bearer token for the API under its
    prefix, where every route checks it."""
    if pages.owns(request):
        return carries_session(request)
    return (
        request.url.path.startswith(f"{api.PREFIX}/")
        and "authorization" in request.headers
    )
