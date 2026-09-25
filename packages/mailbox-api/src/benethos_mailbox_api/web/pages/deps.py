"""Who is using the UI, and whether a form really comes from it."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ...data.models import Account
from ...domain.access import Access
from ..services import get_accounts
from .session import CSRF_FIELD, CSRF_HEADER, csrf_ok, current


class CsrfRefused(Exception):
    """A request that changes something came without the session's token."""


async def signed_in(request: Request) -> Access:
    """The caller of a page that only shows."""
    return current(request)[1]


async def changing(request: Request) -> Access:
    """The caller of a request that changes something: signed in, and the
    form or the htmx header carries the session's CSRF token."""
    session, access = current(request)
    presented = request.headers.get(CSRF_HEADER)
    if presented is None:
        form = await request.form()
        value = form.get(CSRF_FIELD)
        presented = value if isinstance(value, str) else None
    if not csrf_ok(session, presented):
        raise CsrfRefused
    return access


def account_of(request: Request, caller: Access, account_id: str) -> Account:
    """The account a mail page is about. Any right on it will do, as in
    ``/v1/me``: whoever may only write drafts there sees its address too."""
    if not caller.operations_on(account_id):
        caller.require("get_account", account_id)
    accounts = get_accounts(request)
    return accounts.record(account_id)


Viewer = Annotated[Access, Depends(signed_in)]
Actor = Annotated[Access, Depends(changing)]
