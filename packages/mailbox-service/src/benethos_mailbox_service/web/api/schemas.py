"""Request and response shapes that exist only at the HTTP boundary.

The mail types themselves come from ``data.models`` and are served as they
are. What lives here is what only a caller of the API sends or receives.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, SecretStr

from ...data.models import (
    SERVICE_DESCRIPTION,
    AccountStatus,
    ApiToken,
    Capability,
    DraftMessage,
    Grant,
    ProviderType,
    User,
)
from ...domain import system
from ...domain.auth import SignInState


class AccountCreate(BaseModel):
    provider: ProviderType
    email: str
    display_name: str | None = None
    settings: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description="Provider-specific connection settings: host, port, ...",
    )
    credentials: dict[str, SecretStr] = Field(
        default_factory=dict,
        description="Secrets such as `password`. Stored encrypted, never returned.",
    )


class AccountUpdate(BaseModel):
    """What ``PATCH`` changes. Fields left out stay as they are."""

    display_name: str | None = None
    settings: dict[str, str | int | bool | None] = Field(
        default_factory=dict,
        description=(
            "Settings to change, merged into the current ones. `null` removes "
            "one. E.g. `smtp_host`, `smtp_port`, `smtp_security` for sending."
        ),
    )
    credentials: dict[str, SecretStr] = Field(
        default_factory=dict,
        description="New secrets such as `password`. Stored encrypted, never returned.",
    )


class DraftReplacement(DraftMessage):
    """A draft as `create_draft` takes it, and which attachments of the
    stored draft to keep."""

    keep_attachments: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of attachments of the stored draft that go into the new one, "
            "before those `attachments` brings. Any other stored attachment "
            "is gone afterwards."
        ),
    )


class DiscoveryRequest(BaseModel):
    email: str = Field(max_length=254, description="The address to be connected.")


class OAuthStart(BaseModel):
    account_id: str | None = Field(
        default=None, description="Sign this account in again. Left out: connect."
    )
    login_hint: str | None = Field(
        default=None,
        max_length=254,
        description="The address to suggest at the provider's sign-in.",
    )


class OAuthStarted(BaseModel):
    url: str = Field(description="The provider's sign-in page, for a browser.")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """The body of every error the API raises itself."""

    error: ErrorDetail


class MeSending(BaseModel):
    """One grant that allows sending from the account. A send passes when
    one of them accepts every recipient and has sends left."""

    recipients: list[str] | None = Field(
        description="Send only to these: an address, `*@domain`. Null: to anyone."
    )
    max_sends_per_day: int | None = Field(
        description="Mails in any 24 hours under this grant. Null: no limit."
    )
    sends_left: int | None = Field(
        description=(
            "How many more the limit allows now: it less the mails the caller "
            "sent from the account in the last 24 hours. Null: no limit."
        )
    )


class MeAccount(BaseModel):
    """An account the caller may act on."""

    id: str
    email: str
    display_name: str | None = None
    operations: list[str] = Field(description="What the caller may do on it")
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "`read_and_send_anywhere`: the caller may read mail here and send "
            "it to any address, which a mail with injected instructions could "
            "use to carry data out. Narrow sending with a grant's `recipients`."
        ),
    )
    sending: list[MeSending] = Field(
        default_factory=list,
        description="One entry per grant that allows sending here. Empty: none.",
    )
    capabilities: list[Capability] = Field(
        default_factory=list,
        description=(
            "What the account can do beyond reading its inbox, as in "
            "`Account`. Without `flags`, `folders` or `search` (a POP3 "
            "account) those operations answer `501`."
        ),
    )


class Me(BaseModel):
    """The caller and its effective rights."""

    user_id: str
    name: str
    accounts: list[MeAccount] = Field(
        description="Every account the caller may act on, with its operations"
    )
    operations: list[str] = Field(
        description="Operations of the service, bound to no account"
    )


class PermissionCatalogue(BaseModel):
    groups: dict[str, list[str]] = Field(
        description="Group name to the operations it allows"
    )
    service: list[str] = Field(
        description=(
            "The groups of the service. They and `admin` are named in a user's "
            "or a role's `service`, the other groups in a grant's `allow`. "
            "`audit` is in both: in a grant its operations on accounts, in "
            "`service` `list_activity`."
        )
    )


class UserCreate(BaseModel):
    name: str
    roles: list[str] = Field(default_factory=list)
    service: list[str] = Field(default_factory=list, description=SERVICE_DESCRIPTION)
    grants: list[Grant] = Field(default_factory=list)
    ui_sign_in: bool = Field(
        default=False,
        description=(
            "May sign in to the configuration UI. Without: an API user, "
            "tokens only. A password is then set in the UI or with "
            "`POST /v1/users/{user_id}/password`."
        ),
    )


class UserUpdate(BaseModel):
    name: str | None = None
    roles: list[str] | None = None
    service: list[str] | None = Field(default=None, description=SERVICE_DESCRIPTION)
    grants: list[Grant] | None = None
    disabled: bool | None = Field(
        default=None, description="Not for the caller itself."
    )
    ui_sign_in: bool | None = Field(
        default=None,
        description=(
            "Not for the caller itself. Switched off, the user's password is "
            "deleted and its UI sessions end. Its tokens keep working."
        ),
    )


class RoleCreate(BaseModel):
    id: str
    service: list[str] = Field(default_factory=list, description=SERVICE_DESCRIPTION)
    grants: list[Grant] = Field(default_factory=list)


class RoleReplace(BaseModel):
    service: list[str] = Field(default_factory=list, description=SERVICE_DESCRIPTION)
    grants: list[Grant] = Field(default_factory=list)


class TokenCreate(BaseModel):
    name: str
    expires_at: AwareDatetime | None = Field(
        default=None, description="With a time zone, e.g. 2026-12-31T23:59:59Z"
    )


class TokenInfo(BaseModel):
    """A token without its secret."""

    id: str
    user_id: str
    name: str
    state: Literal["active", "expired", "revoked"] = Field(
        description="Whether the token authenticates now"
    )
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def of(cls, token: ApiToken, state: str) -> TokenInfo:
        return cls.model_validate(
            {**token.model_dump(exclude={"token_hash"}), "state": state}
        )


class UserInfo(User):
    """A user, with how it signs in to the UI. Never the password."""

    has_password: bool = Field(description="Whether the user has a password for the UI")
    must_change: bool = Field(
        description=(
            "Whether the password is one set for the user, a one-time "
            "password among them, to be changed at the next sign-in"
        )
    )
    last_sign_in_at: datetime | None = Field(
        description="The last sign-in to the UI, null for none yet"
    )

    @classmethod
    def of(cls, user: User, state: SignInState) -> UserInfo:
        return cls.model_validate({**user.model_dump(), **asdict(state)})


class TokenCreated(TokenInfo):
    token: str = Field(description="The token itself. Shown this once only.")


class PasswordSet(BaseModel):
    password: SecretStr | None = Field(
        default=None,
        description=(
            "The new password. Without it the service makes a one-time "
            "password and answers it."
        ),
    )


class PasswordSetResult(BaseModel):
    password: str | None = Field(
        description=(
            "The one-time password the service made, shown this once. Null "
            "when the request named the password."
        )
    )
    must_change: bool = Field(
        default=True, description="The user changes it at its next sign-in."
    )


# --- the status of the service ---------------------------------------------------


class WorkerStatus(BaseModel):
    """What the sync worker does. Kept in its memory: empty again after a
    restart."""

    interval: float = Field(description="Seconds between two rounds over the accounts")
    push: bool = Field(
        description="Whether watchers wait for a server to report a change"
    )
    last_pass_at: datetime | None = Field(
        description="When the last round ended, null before the first"
    )
    watchers: int = Field(description="How many accounts watchers may wait on at once")
    watching: int = Field(
        description="How many accounts watchers wait on now, of every account"
    )


class AccountSync(BaseModel):
    """An account and how its sync goes."""

    id: str
    email: str
    provider: ProviderType
    status: AccountStatus
    synced: bool = Field(description="Whether a sync pass does anything for it")
    watching: bool = Field(
        description="Whether a watcher waits for its server to report a change"
    )
    last_sync_at: datetime | None = Field(
        description="The last pass that succeeded, null for none since the start"
    )
    last_error: str | None = Field(
        description="Why the last pass failed. A pass that succeeds clears it"
    )
    last_error_at: datetime | None
    attention: bool = Field(
        description=(
            "Whether a person should look: the account is not connected, "
            "or its last pass failed"
        )
    )

    @classmethod
    def of(cls, health: system.AccountHealth) -> AccountSync:
        account, sync = health.account, health.sync
        return cls(
            id=account.id,
            email=account.email,
            provider=account.provider,
            status=account.status,
            synced=health.synced,
            watching=health.watching,
            last_sync_at=sync.last_sync_at,
            last_error=sync.last_error,
            last_error_at=sync.last_error_at,
            attention=health.attention,
        )


class ServiceStatus(BaseModel):
    """The sync worker and the accounts. Nothing is asked of a provider
    for it."""

    worker: WorkerStatus | None = Field(
        description="Null when the worker is switched off"
    )
    accounts: list[AccountSync]

    @classmethod
    def of(cls, status: system.ServiceStatus) -> ServiceStatus:
        worker = status.worker
        return cls(
            worker=None
            if worker is None
            else WorkerStatus(
                interval=worker.interval,
                push=worker.push,
                last_pass_at=worker.last_pass_at,
                watchers=worker.watchers,
                watching=len(worker.watching),
            ),
            accounts=[AccountSync.of(health) for health in status.accounts],
        )
