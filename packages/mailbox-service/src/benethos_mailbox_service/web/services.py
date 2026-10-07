"""The domain services, for both front ends.

``assembly.web`` puts them on ``app.state.services``, one object with
one attribute per service. A route or page gets a service here, as a
FastAPI dependency or, in a helper, from the request.
"""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Depends, Request

from ..domain.accounts import AccountService, OAuthService
from ..domain.activity import ActivityLog, Audit
from ..domain.auth import AuthService
from ..domain.discovery import DiscoveryService
from ..domain.mailbox import MailboxService
from ..domain.system import RecoveryKey, ServiceLog, StatusService
from ..domain.users import PasswordService, RoleService, TokenService, UserService
from ..domain.webhooks import WebhookService
from .state import app_services


class Services(Protocol):
    """What the web layer needs of the assembled services."""

    accounts: AccountService
    auth: AuthService
    users: UserService
    roles: RoleService
    tokens: TokenService
    passwords: PasswordService
    mailbox: MailboxService
    discovery: DiscoveryService
    oauth: OAuthService
    webhooks: WebhookService
    status: StatusService
    recovery: RecoveryKey
    log: ServiceLog
    audit: Audit
    activity: ActivityLog


def services_of(request: Request) -> Services:
    return app_services(request.app)


def get_accounts(request: Request) -> AccountService:
    return services_of(request).accounts


def get_mailbox(request: Request) -> MailboxService:
    return services_of(request).mailbox


def get_discovery(request: Request) -> DiscoveryService:
    return services_of(request).discovery


def get_users(request: Request) -> UserService:
    return services_of(request).users


def get_roles(request: Request) -> RoleService:
    return services_of(request).roles


def get_tokens(request: Request) -> TokenService:
    return services_of(request).tokens


def get_passwords(request: Request) -> PasswordService:
    return services_of(request).passwords


def get_oauth(request: Request) -> OAuthService:
    return services_of(request).oauth


def get_webhooks(request: Request) -> WebhookService:
    return services_of(request).webhooks


def get_auth(request: Request) -> AuthService:
    return services_of(request).auth


def get_status(request: Request) -> StatusService:
    return services_of(request).status


def get_log(request: Request) -> ServiceLog:
    return services_of(request).log


def get_recovery(request: Request) -> RecoveryKey:
    return services_of(request).recovery


def get_audit(request: Request) -> Audit:
    return services_of(request).audit


Accounts = Annotated[AccountService, Depends(get_accounts)]
Auth = Annotated[AuthService, Depends(get_auth)]
Discoverer = Annotated[DiscoveryService, Depends(get_discovery)]
Mailbox = Annotated[MailboxService, Depends(get_mailbox)]
Users = Annotated[UserService, Depends(get_users)]
Roles = Annotated[RoleService, Depends(get_roles)]
Tokens = Annotated[TokenService, Depends(get_tokens)]
Passwords = Annotated[PasswordService, Depends(get_passwords)]
OAuth = Annotated[OAuthService, Depends(get_oauth)]
Webhooks = Annotated[WebhookService, Depends(get_webhooks)]
Status = Annotated[StatusService, Depends(get_status)]
Recovery = Annotated[RecoveryKey, Depends(get_recovery)]
Log = Annotated[ServiceLog, Depends(get_log)]
Activities = Annotated[Audit, Depends(get_audit)]
