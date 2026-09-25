"""The domain services, for both front ends.

``main.create_app`` puts them on ``app.state.services``, one object with
one attribute per service; a route or page gets a service here, as a
FastAPI dependency or, in a helper, from the request.
"""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Depends, Request

from ..domain.accounts import AccountService
from ..domain.auth import AuthService
from ..domain.discovery import DiscoveryService
from ..domain.mailbox import MailboxService
from ..domain.oauth import OAuthService
from ..domain.users import UserService


class Services(Protocol):
    """What the web layer needs of the assembled services."""

    accounts: AccountService
    auth: AuthService
    users: UserService
    mailbox: MailboxService
    discovery: DiscoveryService
    oauth: OAuthService


def services_of(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_accounts(request: Request) -> AccountService:
    return services_of(request).accounts


def get_mailbox(request: Request) -> MailboxService:
    return services_of(request).mailbox


def get_discovery(request: Request) -> DiscoveryService:
    return services_of(request).discovery


def get_users(request: Request) -> UserService:
    return services_of(request).users


def get_oauth(request: Request) -> OAuthService:
    return services_of(request).oauth


def get_auth(request: Request) -> AuthService:
    return services_of(request).auth


Accounts = Annotated[AccountService, Depends(get_accounts)]
Auth = Annotated[AuthService, Depends(get_auth)]
Discoverer = Annotated[DiscoveryService, Depends(get_discovery)]
Mailbox = Annotated[MailboxService, Depends(get_mailbox)]
Users = Annotated[UserService, Depends(get_users)]
OAuth = Annotated[OAuthService, Depends(get_oauth)]
