"""Signing an account in with its provider: in a browser, or with a code."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from ....data.models import Account


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
