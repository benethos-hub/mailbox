"""The caller, users, roles and passwords."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from pydantic import BaseModel, Field, SecretStr

from ....data.models import SERVICE_DESCRIPTION, Capability, Grant, User
from ....domain.auth import SignInState


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
    second_factor: bool = Field(
        description=(
            "Whether the UI sign-in asks for a code of an authenticator app "
            "after the password. The user sets one up in the UI."
        )
    )

    @classmethod
    def of(cls, user: User, state: SignInState) -> UserInfo:
        return cls.model_validate({**user.model_dump(), **asdict(state)})


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
