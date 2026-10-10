"""The values of an OAuth sign-in: where a provider signs users in, the
app a deployment signs in with, who signed in, the tokens, and a code
for a sign-in on another device.

Values only, frozen. Talking to the provider is ``client``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class Profile:
    """Where a provider says whose mailbox an access token opens: a JSON
    document at ``url``, the address in the first of ``email`` that is
    set, the name in ``name``. ``scopes`` are asked for at the sign-in
    only: a refresh token granted before them would not cover them."""

    url: str
    email: tuple[str, ...]
    name: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Endpoints:
    """Where a provider signs users in and hands out tokens, and what a
    mail adapter asks for. With ``profile``, the address of an account
    comes from there, else from the ID token. ``device_url`` hands out
    codes for a sign-in on another device, None where there is none.
    ``authorize_params``: what the provider needs beyond RFC 6749 to
    send the browser back, and to hand out a refresh token, e.g.
    Google's ``access_type=offline``. ``refresh_scopes``: whether a
    refresh names the scopes again, as Microsoft wants it."""

    provider: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    profile: Profile | None = None
    device_url: str | None = None
    authorize_params: tuple[tuple[str, str], ...] = ()
    refresh_scopes: bool = True

    @property
    def sign_in_scopes(self) -> tuple[str, ...]:
        """What a sign-in asks for: the adapter's scopes and the profile's."""
        return self.scopes + (self.profile.scopes if self.profile else ())


@dataclass(frozen=True, slots=True)
class App:
    """The OAuth client a deployment signs in with: one the operator
    registered, or the project's. Without a secret it is a public client,
    which proves itself by PKCE alone. ``loopback_only``: the provider
    sends a browser back to localhost only, as for the project's app."""

    endpoints: Endpoints
    client_id: str
    client_secret: SecretStr | None = None
    loopback_only: bool = False


@dataclass(frozen=True, slots=True)
class Identity:
    """Who signed in: as the provider's profile says, or else the ID token.
    Both come straight from the provider over verified TLS, so the token's
    signature is not checked again."""

    email: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class Tokens:
    access_token: SecretStr
    expires_at: datetime
    refresh_token: SecretStr | None
    identity: Identity | None = None


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """A sign-in with a code (RFC 8628): the person enters ``user_code`` at
    ``verification_uri``, on any device. ``device_code`` asks for the
    tokens and never leaves the service."""

    device_code: SecretStr
    user_code: str
    verification_uri: str
    # Seconds the code is valid, and to wait between two questions for
    # the tokens.
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class Waiting:
    """The person has not signed in yet. ``slow_down``: the provider asks
    to be asked less often."""

    slow_down: bool = False


@dataclass(frozen=True, slots=True)
class Pkce:
    verifier: str
    challenge: str
