"""Web layer: HTTP and nothing else.

Two front ends on one domain: ``api`` serves the JSON API under ``/v1``
(and ``/health``), ``pages`` the configuration UI under ``/ui``. Both check
input, call the domain and answer; neither decides what a caller may do.
FastAPI is imported here and nowhere below. May import ``domain`` and
``data``.

This module only puts the two together, and sends an error to the front
end whose request failed: a page for the UI, the error envelope for the
API.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException

from ..errors import MailboxApiError
from . import api, pages
from .api.errors import api_error, http_error, status_of
from .pages.errors import error_page


def install(app: FastAPI) -> None:
    api.install(app)
    pages.install(app)

    @app.exception_handler(MailboxApiError)
    async def _domain_error(request: Request, exc: MailboxApiError) -> Response:
        if pages.owns(request):
            return error_page(request, status_of(exc), exc.message)
        return api_error(exc)

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
        return await request_validation_exception_handler(request, exc)
