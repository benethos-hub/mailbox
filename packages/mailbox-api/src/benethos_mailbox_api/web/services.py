"""The domain services, for both front ends.

``main.create_app`` puts one of each on ``app.state``; a route or page gets
it here, as a FastAPI dependency or, in a helper, from the request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..domain.accounts import AccountService
from ..domain.auth import AuthService
from ..domain.discovery import DiscoveryService
from ..domain.mailbox import MailboxService
from ..domain.oauth import OAuthService
from ..domain.users import UserService


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


def get_oauth(request: Request) -> OAuthService:
    oauth: OAuthService = request.app.state.oauth
    return oauth


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


Accounts = Annotated[AccountService, Depends(get_accounts)]
Discoverer = Annotated[DiscoveryService, Depends(get_discovery)]
Mailbox = Annotated[MailboxService, Depends(get_mailbox)]
Users = Annotated[UserService, Depends(get_users)]
OAuth = Annotated[OAuthService, Depends(get_oauth)]
