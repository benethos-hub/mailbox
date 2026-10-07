"""Signing an account in with its provider, with a code."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from ....data.models import Account


class DeviceOAuthStart(BaseModel):
    account_id: str | None = Field(
        default=None, description="Sign this account in again. Left out: connect."
    )


class DeviceOAuthStarted(BaseModel):
    sign_in_id: str = Field(description="Names this sign-in when polling it.")
    user_code: str = Field(description="What the person enters at the provider.")
    verification_uri: str = Field(
        description="The provider's page where the person enters the code."
    )
    expires_at: AwareDatetime = Field(description="When the code runs out.")
    interval: int = Field(description="Seconds to wait between two polls.")


class DeviceOAuthState(BaseModel):
    connected: bool = Field(
        description="The person signed in, and the account is connected."
    )
    account: Account | None = Field(
        default=None, description="The account connected or signed in again."
    )
