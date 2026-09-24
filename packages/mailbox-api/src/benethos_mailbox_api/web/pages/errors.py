"""Errors in the configuration UI: a page, not JSON."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import Request
from fastapi.responses import HTMLResponse

from .templates import render


def error_page(
    request: Request, status: int, message: str, title: str | None = None
) -> HTMLResponse:
    return render(
        request,
        "pages/error.html",
        page="error",
        status_code=status,
        title=title or HTTPStatus(status).phrase,
        message=message,
    )
