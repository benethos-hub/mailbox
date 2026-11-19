"""Connecting and changing an account, and finding its servers."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr

from ....data.models import ProviderType


class AccountCreate(BaseModel):
    provider: ProviderType
    email: str
    display_name: str | None = None
    settings: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description=(
            "Provider-specific connection settings: host, port, ... "
            "`authserv_id`: for IMAP, POP3 and JMAP, the receiving server's "
            "name as it starts its Authentication-Results, several with "
            "commas, a leading dot for every host below a domain. It turns "
            "on the sender check."
        ),
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
            "one. E.g. `smtp_host`, `smtp_port`, `smtp_security` for sending, "
            "`authserv_id` for the sender check."
        ),
    )
    credentials: dict[str, SecretStr] = Field(
        default_factory=dict,
        description="New secrets such as `password`. Stored encrypted, never returned.",
    )


class DiscoveryRequest(BaseModel):
    email: str = Field(max_length=254, description="The address to be connected.")


class ServerName(BaseModel):
    """A receiving server's name as the newest mails of the inbox carry it."""

    id: str = Field(
        description="The name, in lower case, as it starts an "
        "Authentication-Results entry."
    )
    count: int = Field(description="How many of the mails read carry it.")
    top: int = Field(
        description="How many of the mails read carry it as their topmost "
        "entry. A server adds its entry on top, one a mail brought along "
        "stands below."
    )


class ServerNameList(BaseModel):
    """The names receiving servers wrote into the newest mails of the
    inbox, those most often on top first."""

    mails: int = Field(
        description="How many mails were read, ten at most. 0 for an empty "
        "inbox and for an account that names its server itself."
    )
    items: list[ServerName]
