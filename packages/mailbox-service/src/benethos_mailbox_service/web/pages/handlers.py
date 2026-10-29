"""What the UI answers to the errors a page raises: to the sign-in, to
the change of a password, back to a form, or a page that says a form
expired."""

from __future__ import annotations

import inspect
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...errors import MailboxServiceError
from .deps import CsrfRefusedError
from .errors import error_page
from .forms import FormFailedError
from .session import (
    PASSWORD_PAGE,
    PATH,
    PasswordChangeRequiredError,
    SignInRequiredError,
)
from .templates import back, is_htmx


async def sign_in_required(request: Request, _: SignInRequiredError) -> Response:
    """To the sign-in page, and after it back to the page asked for, with
    its query. A form that was posted cannot be repeated by a redirect,
    so after a POST the sign-in lands on the start page."""
    target = f"{PATH}/login"
    if request.method == "GET":
        page = request.url.path
        if request.url.query:
            page += f"?{request.url.query}"
        target += f"?next={quote(page, safe='/')}"
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


async def password_change_required(
    request: Request, _: PasswordChangeRequiredError
) -> Response:
    """A password someone else set is changed before anything else."""
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": PASSWORD_PAGE})
    return RedirectResponse(PASSWORD_PAGE, status_code=303)


async def form_failed(request: Request, exc: FormFailedError) -> Response:
    if exc.again is not None:
        try:
            page = exc.again(exc.error)
            return await page if inspect.isawaitable(page) else page
        except MailboxServiceError:
            pass  # the page itself is gone: back with the message
    return back(request, exc.path, error=exc.error)


async def csrf_refused(request: Request, _: CsrfRefusedError) -> HTMLResponse:
    return error_page(
        request,
        403,
        "This form is no longer valid. Reload the page and try again.",
        title="Form expired",
    )
