"""Dependencies shared by the routers: who is calling, and the services.

The web layer only establishes the caller. What the caller may do is decided
in the domain.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..data.models import MessageFilter
from ..data.models.messages import SEARCH_TEXT_PATTERN
from ..domain.access import Access
from ..domain.accounts import AccountService
from ..domain.auth import AuthService
from ..domain.discovery import DiscoveryService
from ..domain.mailbox import MailboxService
from ..domain.users import UserService

_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def get_accounts(request: Request) -> AccountService:
    accounts: AccountService = request.app.state.accounts
    return accounts


def get_mailbox(request: Request) -> MailboxService:
    mailbox: MailboxService = request.app.state.mailbox
    return mailbox


def get_discovery(request: Request) -> DiscoveryService:
    discovery: DiscoveryService = request.app.state.discovery
    return discovery


def get_users(request: Request) -> UserService:
    users: UserService = request.app.state.users
    return users


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def authenticate(
    auth: Annotated[AuthService, Depends(get_auth)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Access:
    return auth.authenticate(credentials.credentials if credentials else None)


Accounts = Annotated[AccountService, Depends(get_accounts)]
Discoverer = Annotated[DiscoveryService, Depends(get_discovery)]
Mailbox = Annotated[MailboxService, Depends(get_mailbox)]
Users = Annotated[UserService, Depends(get_users)]
Caller = Annotated[Access, Depends(authenticate)]


# --- search parameters, shared by the lists ----------------------------------------


def message_filter(
    q: Annotated[
        str | None,
        Query(
            pattern=SEARCH_TEXT_PATTERN,
            description="Text anywhere: headers and body",
        ),
    ] = None,
    sender: Annotated[
        str | None,
        Query(
            alias="from",
            pattern=SEARCH_TEXT_PATTERN,
            description="Part of the sender's address or name",
        ),
    ] = None,
    to: Annotated[
        str | None,
        Query(pattern=SEARCH_TEXT_PATTERN, description="Part of a To address"),
    ] = None,
    subject: Annotated[
        str | None,
        Query(pattern=SEARCH_TEXT_PATTERN, description="Part of the subject"),
    ] = None,
    after: Annotated[
        date | None, Query(description="From this day on, e.g. 2026-09-01")
    ] = None,
    before: Annotated[
        date | None, Query(description="Up to this day, not including it")
    ] = None,
    unread: bool | None = None,
    starred: bool | None = None,
    has_attachments: bool | None = None,
) -> MessageFilter:
    return MessageFilter(
        text=q,
        sender=sender,
        to=to,
        subject=subject,
        after=after,
        before=before,
        unread=unread,
        starred=starred,
        has_attachments=has_attachments,
    )


Search = Annotated[MessageFilter, Depends(message_filter)]
