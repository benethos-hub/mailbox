"""OAuth 2.0, the wire protocol of a sign-in: the authorization code flow
with PKCE, the sign-in with a code on another device (RFC 8628),
refreshing, and a token source that keeps an adapter's access token
valid.

Provider-neutral. What differs per provider is an ``Endpoints`` value,
which each adapter that signs in with OAuth brings, e.g.
``microsoft/signin.py``. Nothing here decides who may sign in or where a
token is kept: the caller hands in how to read and store the refresh token.
Tokens are ``SecretStr`` throughout and appear in no error text.

The values are ``values``, the talk to a provider ``client``, what it
answers read in ``answers``, the token source ``tokens``.
"""

from __future__ import annotations

from .answers import identity_of
from .client import OAuthClient, authorize_url, new_pkce
from .tokens import RefreshingTokens
from .values import (
    App,
    DeviceCode,
    Endpoints,
    Identity,
    Pkce,
    Profile,
    Tokens,
    Waiting,
)

__all__ = [
    "App",
    "DeviceCode",
    "Endpoints",
    "Identity",
    "OAuthClient",
    "Pkce",
    "Profile",
    "RefreshingTokens",
    "Tokens",
    "Waiting",
    "authorize_url",
    "identity_of",
    "new_pkce",
]
