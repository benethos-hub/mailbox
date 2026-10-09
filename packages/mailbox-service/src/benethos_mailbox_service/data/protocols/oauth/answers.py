"""What a provider answers, read: the tokens a token endpoint hands out,
a code for another device, an ID token's claims, a profile, and a
refusal as this project's error, without anything that was sent.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, RootModel

from ....common.opaque import from_base64
from ....errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from .. import wire
from ..http import Answer
from .values import Identity


class Granted(wire.Shape):
    """What a token endpoint hands out (RFC 6749 5.1)."""

    access_token: str = Field(min_length=1)
    expires_in: wire.Seconds = None
    refresh_token: Annotated[str | None, wire.OrNone] = None
    id_token: Annotated[str | None, wire.OrNone] = None


class Code(wire.Shape):
    """A code for a sign-in on another device (RFC 8628 3.2). Some
    providers spell it ``verification_url``."""

    device_code: str = Field(min_length=1)
    user_code: str = Field(min_length=1)
    verification_uri: Annotated[str | None, wire.OrNone] = None
    verification_url: Annotated[str | None, wire.OrNone] = None
    expires_in: wire.Seconds = None
    interval: wire.Seconds = None


class _Refusal(wire.Shape):
    """An error of a token endpoint (RFC 6749 5.2)."""

    error: Annotated[str | None, wire.OrNone] = None


class Fields(RootModel[dict[str, Annotated[str | None, wire.OrNone]]]):
    """A profile: its text fields, any other field None."""


class _Claims(wire.Shape):
    email: Annotated[str | None, wire.OrNone] = None
    preferred_username: Annotated[str | None, wire.OrNone] = None
    name: Annotated[str | None, wire.OrNone] = None


class StillWaitingError(Exception):
    def __init__(self, slow_down: bool) -> None:
        super().__init__("authorization pending")
        self.slow_down = slow_down


def identity_of(id_token: str) -> Identity | None:
    """The address and name an ID token carries, or None if it is unreadable."""
    try:
        payload = from_base64(id_token.split(".")[1])
    except (IndexError, ValueError):
        return None
    claims = wire.read(_Claims, payload)
    if claims is None:
        return None
    email = claims.email or claims.preferred_username
    return Identity(
        email=email.strip().lower() if email else None,
        name=claims.name or None,
    )


def error_of(answer: Answer) -> str | None:
    """The error a token endpoint names. None for a gateway's HTML page:
    the status says enough."""
    refusal = wire.read(_Refusal, answer.body)
    return refusal.error if refusal is not None else None


def refusal(provider: str, status: int, error: str | None) -> Exception:
    """The token endpoint's error, without anything that was sent."""
    if error in ("authorization_pending", "slow_down"):
        return StillWaitingError(slow_down=error == "slow_down")
    if error == "authorization_declined":
        return BadRequestError(f"the sign-in at {provider} was declined")
    if error in ("expired_token", "bad_verification_code"):
        return BadRequestError(f"the code for {provider} has expired: start again")
    if error in ("invalid_grant", "interaction_required", "consent_required"):
        # The user has to sign in again: revoked, expired, password changed.
        return ProviderAuthError(f"{provider} asks to sign in again ({error})")
    if status >= 500 or error == "temporarily_unavailable":
        return ProviderUnavailableError(
            f"{provider} could not answer the token request ({error or status})"
        )
    if error in ("invalid_client", "unauthorized_client"):
        return ProviderError(
            f"{provider} refused this service's app ({error}): check the "
            "client id, the secret and how the app is registered"
        )
    return ProviderError(f"{provider} refused the token request ({error or status})")
