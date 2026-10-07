"""Who is using the UI, and whether a form really comes from it."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Annotated, TypeVar

from fastapi import Depends, Request

from ...data.models import Account
from ...domain.rights import Access
from ..services import get_accounts
from .session import CSRF_FIELD, CSRF_HEADER, csrf_ok, current

T = TypeVar("T")


def if_allowed(
    caller: Access,
    operation: str,
    call: Callable[[], T],
    default: T,
    account_id: str | None = None,
) -> T:
    """``call()`` where the caller may do ``operation``, else
    ``default``: for a part of a page the caller may not see."""
    return call() if caller.allows(operation, account_id) else default


class CsrfRefusedError(Exception):
    """A request that changes something came without the session's token."""


async def signed_in(request: Request) -> Access:
    """The caller of a page that only shows."""
    return current(request).access


async def changing(request: Request) -> Access:
    """The caller of a request that changes something: signed in, and the
    form or the htmx header carries the session's CSRF token."""
    found = current(request)
    presented = request.headers.get(CSRF_HEADER)
    if presented is None:
        form = await request.form()
        value = form.get(CSRF_FIELD)
        presented = value if isinstance(value, str) else None
    if not csrf_ok(found.session, presented):
        raise CsrfRefusedError
    return found.access


def account_of(request: Request, caller: Access, account_id: str) -> Account:
    """The account a mail page is about. The domain decides who sees it."""
    return get_accounts(request).visible(caller, account_id)


def emails_of(accounts: Iterable[Account]) -> dict[str, str]:
    """Email by account id, to show an account readably."""
    return {account.id: account.email for account in accounts}


def account_names(request: Request, caller: Access) -> dict[str, str]:
    """``emails_of`` every account the caller sees."""
    return emails_of(get_accounts(request).list(caller))


Viewer = Annotated[Access, Depends(signed_in)]
Actor = Annotated[Access, Depends(changing)]
