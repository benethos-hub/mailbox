"""Connected mailboxes: the account, its provider and its state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    IMAP = "imap"
    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    MEMORY = "memory"


class AccountStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_REAUTH = "needs_reauth"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class CredentialInfo(BaseModel):
    """That a credential is stored, never its value."""

    field: str
    updated_at: datetime


class Account(BaseModel):
    id: str
    provider: ProviderType
    email: str
    display_name: str | None = None
    status: AccountStatus = AccountStatus.CONNECTED
    credentials: list[CredentialInfo] = Field(default_factory=list)
    settings: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description=(
            "The connection settings: host, port, security, username, "
            "smtp_host, ... Never a secret; those are `credentials`."
        ),
    )
