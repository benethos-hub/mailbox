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


class DiscoveryRequest(BaseModel):
    email: str = Field(max_length=254, description="The address to be connected.")
