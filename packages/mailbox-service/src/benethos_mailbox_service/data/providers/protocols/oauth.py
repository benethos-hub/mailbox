"""OAuth 2.0, the wire protocol of a sign-in: the authorization code flow
with PKCE, refreshing, and a token source that keeps an adapter's access
token valid.

Provider-neutral. What differs per provider is an ``Endpoints`` value,
which each adapter that signs in with OAuth brings, e.g.
``microsoft/signin.py``. Nothing here decides who may sign in or where a
token is kept: the caller hands in how to read and store the refresh token.
Tokens are ``SecretStr`` throughout and appear in no error text.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import anyio
from pydantic import SecretStr

from ....common.clock import utc_now
from ....errors import ProviderAuthError, ProviderError
from ...http import ApiClient

# An access token counts as spent this long before it runs out.
MARGIN = timedelta(minutes=1)


@dataclass(frozen=True)
class Endpoints:
    """Where a provider signs users in and hands out tokens, and what a
    mail adapter asks for."""

    provider: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class App:
    """The OAuth client an operator registered for this deployment."""

    endpoints: Endpoints
    client_id: str
    client_secret: SecretStr | None = None


@dataclass(frozen=True)
class Identity:
    """Who signed in, as the ID token says. Received straight from the token
    endpoint over verified TLS, so its signature is not checked again."""

    email: str | None
    name: str | None


@dataclass(frozen=True)
class Tokens:
    access_token: SecretStr
    expires_at: datetime
    refresh_token: SecretStr | None
    identity: Identity | None = None


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


def new_pkce() -> Pkce:
    """A code verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return Pkce(verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode())


def authorize_url(
    app: App,
    redirect_uri: str,
    state: str,
    pkce: Pkce,
    login_hint: str | None = None,
) -> str:
    """Where to send the browser to sign in."""
    query = {
        "client_id": app.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(app.endpoints.scopes),
        "state": state,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        query["login_hint"] = login_hint
    return f"{app.endpoints.authorize_url}?{urlencode(query)}"


class OAuthClient:
    """Talks to one provider's token endpoint for one registered app."""

    def __init__(
        self,
        app: App,
        http: ApiClient,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.app = app
        self._http = http
        # Stamps ``expires_at``. A token source judges expiry by the same clock.
        self.clock = clock

    async def close(self) -> None:
        await self._http.close()

    async def exchange(self, code: str, redirect_uri: str, verifier: str) -> Tokens:
        """The tokens for the code the browser came back with."""
        return await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }
        )

    async def refresh(self, refresh_token: SecretStr) -> Tokens:
        """New tokens for a refresh token. The provider may hand out a new
        refresh token too. The old one may then stop working."""
        return await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.get_secret_value(),
            }
        )

    async def _token(self, grant: dict[str, str]) -> Tokens:
        form = {
            **grant,
            "client_id": self.app.client_id,
            "scope": " ".join(self.app.endpoints.scopes),
        }
        if self.app.client_secret is not None:
            form["client_secret"] = self.app.client_secret.get_secret_value()
        answer = await self._http.request(
            "POST", self.app.endpoints.token_url, form=form
        )
        try:
            body = answer.json()
        except ProviderError:
            body = None  # a gateway's HTML page: the status says enough
        if not answer.ok or not isinstance(body, dict):
            raise _refused(self.app.endpoints.provider, answer.status, body)
        return self._tokens(body)

    def _tokens(self, body: dict[str, Any]) -> Tokens:
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderError("the token endpoint answered without an access token")
        lifetime = body.get("expires_in")
        seconds = int(lifetime) if isinstance(lifetime, int | str) else 3600
        refresh = body.get("refresh_token")
        id_token = body.get("id_token")
        return Tokens(
            access_token=SecretStr(access),
            expires_at=self.clock() + timedelta(seconds=seconds),
            refresh_token=SecretStr(refresh) if isinstance(refresh, str) else None,
            identity=identity_of(id_token) if isinstance(id_token, str) else None,
        )


def identity_of(id_token: str) -> Identity | None:
    """The address and name an ID token carries, or None if it is unreadable."""
    try:
        payload = id_token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError):
        return None
    if not isinstance(claims, dict):
        return None
    email = claims.get("email") or claims.get("preferred_username")
    name = claims.get("name")
    return Identity(
        email=str(email).strip().lower() if email else None,
        name=str(name) if name else None,
    )


def _refused(provider: str, status: int, body: Any) -> Exception:
    """The token endpoint's error, without anything that was sent."""
    error = body.get("error") if isinstance(body, dict) else None
    if error in ("invalid_grant", "interaction_required", "consent_required"):
        # The user has to sign in again: revoked, expired, password changed.
        return ProviderAuthError(f"{provider} asks to sign in again ({error})")
    if error in ("invalid_client", "unauthorized_client"):
        return ProviderError(
            f"{provider} refused this service's app ({error}): check the "
            "client id and secret"
        )
    return ProviderError(f"{provider} refused the token request ({error or status})")


class RefreshingTokens:
    """A ``TokenSource``: the access token in memory, refreshed shortly
    before it runs out. A new refresh token is stored at once, before the
    access token is used, so a rotation is never lost."""

    def __init__(
        self,
        client: OAuthClient,
        read_refresh: Callable[[], SecretStr],
        store_refresh: Callable[[SecretStr], None],
        clock: Callable[[], datetime] | None = None,
        current: Tokens | None = None,
    ) -> None:
        """``clock`` defaults to the client's: the one that stamped
        ``expires_at`` decides when a token is spent."""
        self._client = client
        self._read = read_refresh
        self._store = store_refresh
        self._clock = clock or client.clock
        self._current = current
        self._lock = anyio.Lock()
        # A refresh the provider refused: asked no more with this token.
        self._refused: ProviderAuthError | None = None

    async def access_token(self) -> SecretStr:
        async with self._lock:
            if self._refused is not None:
                raise self._refused
            if self._current is None or self._spent(self._current):
                self._current = await self._renew()
            return self._current.access_token

    def reject(self) -> None:
        self._current = None

    def _spent(self, tokens: Tokens) -> bool:
        return tokens.expires_at - MARGIN <= self._clock()

    async def _renew(self) -> Tokens:
        old = self._read()
        try:
            tokens = await self._client.refresh(old)
        except ProviderAuthError as exc:
            self._refused = exc
            raise
        new = tokens.refresh_token
        if new is not None and new.get_secret_value() != old.get_secret_value():
            self._store(new)
        return tokens
