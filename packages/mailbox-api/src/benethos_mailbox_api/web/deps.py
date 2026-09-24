"""Dependencies shared by the routers: authentication and the services."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import Settings
from ..domain.accounts import AccountService
from ..domain.mailbox import MailboxService

_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_accounts(request: Request) -> AccountService:
    accounts: AccountService = request.app.state.accounts
    return accounts


def get_mailbox(request: Request) -> MailboxService:
    mailbox: MailboxService = request.app.state.mailbox
    return mailbox


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = settings.api_key.get_secret_value() if settings.api_key else None
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "MAILBOX_API_KEY is not set, so the API serves nothing",
        )
    given = credentials.credentials if credentials else ""
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or wrong bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


Accounts = Annotated[AccountService, Depends(get_accounts)]
Mailbox = Annotated[MailboxService, Depends(get_mailbox)]
