"""Request and response shapes that exist only at the HTTP boundary,
one module per subject.

The mail types themselves come from ``data.models`` and are served as they
are. What lives here is what only a caller of the API sends or receives.
"""

from __future__ import annotations

from .accounts import AccountCreate, AccountUpdate, DiscoveryRequest
from .errors import ErrorDetail, ErrorResponse
from .mail import DraftReplacement
from .oauth import (
    DeviceOAuthStart,
    DeviceOAuthStarted,
    DeviceOAuthState,
    OAuthStart,
    OAuthStarted,
)
from .status import AccountSync, ServiceStatus, WorkerStatus
from .tokens import TokenCreate, TokenCreated, TokenInfo
from .users import (
    Me,
    MeAccount,
    MeSending,
    PasswordSet,
    PasswordSetResult,
    PermissionCatalogue,
    RoleCreate,
    RoleReplace,
    UserCreate,
    UserInfo,
    UserUpdate,
)

__all__ = [
    "AccountCreate",
    "AccountSync",
    "AccountUpdate",
    "DeviceOAuthStart",
    "DeviceOAuthStarted",
    "DeviceOAuthState",
    "DiscoveryRequest",
    "DraftReplacement",
    "ErrorDetail",
    "ErrorResponse",
    "Me",
    "MeAccount",
    "MeSending",
    "OAuthStart",
    "OAuthStarted",
    "PasswordSet",
    "PasswordSetResult",
    "PermissionCatalogue",
    "RoleCreate",
    "RoleReplace",
    "ServiceStatus",
    "TokenCreate",
    "TokenCreated",
    "TokenInfo",
    "UserCreate",
    "UserInfo",
    "UserUpdate",
    "WorkerStatus",
]
