"""Dependencies shared by the routers: who is calling, and the services.

The web layer only establishes the caller. What the caller may do is decided
in the domain.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..domain.access import Access
from ..domain.accounts import AccountService
from ..domain.auth import AuthService
from ..domain.mailbox import MailboxService

_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def get_accounts(request: Request) -> AccountService:
    accounts: AccountService = request.app.state.accounts
    return accounts


def get_mailbox(request: Request) -> MailboxService:
    mailbox: MailboxService = request.app.state.mailbox
    return mailbox


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def authenticate(
    auth: Annotated[AuthService, Depends(get_auth)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Access:
    return auth.authenticate(credentials.credentials if credentials else None)


Accounts = Annotated[AccountService, Depends(get_accounts)]
Mailbox = Annotated[MailboxService, Depends(get_mailbox)]
Caller = Annotated[Access, Depends(authenticate)]
