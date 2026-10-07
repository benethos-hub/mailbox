"""OAuth 2.0, the wire protocol of a sign-in: the authorization code flow
with PKCE, the sign-in with a code on another device (RFC 8628),
refreshing, and a token source that keeps an adapter's access token
valid.

Provider-neutral. What differs per provider is an ``Endpoints`` value,
which each adapter that signs in with OAuth brings, e.g.
``microsoft/signin.py``. Nothing here decides who may sign in or where a
token is kept: the caller hands in how to read and store the refresh token.
Tokens are ``SecretStr`` throughout and appear in no error text.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import anyio
from pydantic import SecretStr

from ...common import redact
from ...common.clock import utc_now
from ...common.opaque import from_base64, to_base64
from ...errors import (
    BadRequestError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
)
from .http import ApiClient

# An access token counts as spent this long before it runs out.
MARGIN = timedelta(minutes=1)
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# What RFC 8628 suggests where the provider names no lifetime or interval.
DEVICE_LIFETIME = 900
DEVICE_INTERVAL = 5


@dataclass(frozen=True)
class Profile:
    """Where a provider says whose mailbox an access token opens: a JSON
    document at ``url``, the address in the first of ``email`` that is
    set, the name in ``name``. ``scopes`` are asked for at the sign-in
    only: a refresh token granted before them would not cover them."""

    url: str
    email: tuple[str, ...]
    name: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Endpoints:
    """Where a provider signs users in and hands out tokens, and what a
    mail adapter asks for. With ``profile``, the address of an account
    comes from there, else from the ID token. ``device_url`` hands out
    codes for a sign-in on another device, None where there is none."""

    provider: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    profile: Profile | None = None
    device_url: str | None = None

    @property
    def sign_in_scopes(self) -> tuple[str, ...]:
        """What a sign-in asks for: the adapter's scopes and the profile's."""
        return self.scopes + (self.profile.scopes if self.profile else ())


@dataclass(frozen=True)
class App:
    """The OAuth client a deployment signs in with: one the operator
    registered, or the project's. Without a secret it is a public client,
    which proves itself by PKCE alone. ``loopback_only``: the provider
    sends a browser back to localhost only, as for the project's app."""

    endpoints: Endpoints
    client_id: str
    client_secret: SecretStr | None = None
    loopback_only: bool = False


@dataclass(frozen=True)
class Identity:
    """Who signed in: as the provider's profile says, or else the ID token.
    Both come straight from the provider over verified TLS, so the token's
    signature is not checked again."""

    email: str | None
    name: str | None


@dataclass(frozen=True)
class Tokens:
    access_token: SecretStr
    expires_at: datetime
    refresh_token: SecretStr | None
    identity: Identity | None = None


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class Waiting:
    """The person has not signed in yet. ``slow_down``: the provider asks
    to be asked less often."""

    slow_down: bool = False


class _StillWaiting(Exception):
    def __init__(self, slow_down: bool) -> None:
        super().__init__("authorization pending")
        self.slow_down = slow_down


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


def new_pkce() -> Pkce:
    """A code verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return Pkce(verifier, to_base64(digest))


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
        "scope": " ".join(app.endpoints.sign_in_scopes),
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
        """The tokens for the code the browser came back with, and who
        signed in."""
        tokens = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            self.app.endpoints.sign_in_scopes,
        )
        return await self._identified(tokens)

    async def device_code(self) -> DeviceCode:
        """A code for a person to sign in with, on any device."""
        endpoints = self.app.endpoints
        if endpoints.device_url is None:
            raise NotSupportedError(f"{endpoints.provider} has no sign-in with a code")
        answer = await self._http.request(
            "POST",
            endpoints.device_url,
            form={
                "client_id": self.app.client_id,
                "scope": " ".join(endpoints.sign_in_scopes),
            },
        )
        body = _json(answer)
        error = body.get("error") if isinstance(body, dict) else None
        if error in ("invalid_client", "unauthorized_client"):
            # Microsoft: AADSTS70002, the app is no public client.
            raise ProviderError(
                f"{endpoints.provider} refuses a sign-in with a code for this "
                f"service's app ({error}): the app must allow public client flows"
            )
        if not answer.ok or not isinstance(body, dict):
            raise _refused(endpoints.provider, answer.status, body)
        code = body.get("device_code")
        user_code = body.get("user_code")
        # Some providers spell it verification_url.
        uri = body.get("verification_uri") or body.get("verification_url")
        if not (
            isinstance(code, str)
            and code
            and isinstance(user_code, str)
            and user_code
            and isinstance(uri, str)
        ):
            raise ProviderError(f"{endpoints.provider} answered without a code")
        if not uri.startswith("https://"):
            raise ProviderError(
                f"{endpoints.provider} named a sign-in page without HTTPS"
            )
        redact.note(code)
        return DeviceCode(
            device_code=SecretStr(code),
            user_code=user_code,
            verification_uri=uri,
            expires_in=_seconds(body.get("expires_in"), DEVICE_LIFETIME),
            interval=_seconds(body.get("interval"), DEVICE_INTERVAL),
        )

    async def poll_device(self, device_code: SecretStr) -> Tokens | Waiting:
        """The tokens once the person entered the code and signed in, and
        who signed in. Until then ``Waiting``."""
        try:
            tokens = await self._token(
                {
                    "grant_type": DEVICE_GRANT,
                    "device_code": device_code.get_secret_value(),
                },
                None,
            )
        except _StillWaiting as waiting:
            return Waiting(slow_down=waiting.slow_down)
        return await self._identified(tokens)

    async def _identified(self, tokens: Tokens) -> Tokens:
        """The tokens with who signed in, as the provider's profile says."""
        profile = self.app.endpoints.profile
        if profile is None:
            return tokens
        return replace(tokens, identity=await self._profile(profile, tokens))

    async def _profile(self, profile: Profile, tokens: Tokens) -> Identity:
        """The mailbox the access token opens, as the provider's API says.
        An ID token may carry an address its owner typed in."""
        provider = self.app.endpoints.provider
        answer = await self._http.request(
            "GET",
            profile.url,
            headers={
                "Authorization": f"Bearer {tokens.access_token.get_secret_value()}"
            },
        )
        try:
            body = answer.json() if answer.ok else None
        except ProviderError:
            body = None
        if not isinstance(body, dict):
            raise ProviderError(
                f"{provider} did not say whose mailbox this is ({answer.status})"
            )
        email = next(
            (v for f in profile.email if isinstance(v := body.get(f), str) and v),
            None,
        )
        name = body.get(profile.name) if profile.name else None
        return Identity(
            email=email.strip().lower() if email else None,
            name=name if isinstance(name, str) and name else None,
        )

    async def refresh(self, refresh_token: SecretStr) -> Tokens:
        """New tokens for a refresh token. The provider may hand out a new
        refresh token too. The old one may then stop working."""
        return await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.get_secret_value(),
            },
            self.app.endpoints.scopes,
        )

    async def _token(
        self, grant: dict[str, str], scopes: tuple[str, ...] | None
    ) -> Tokens:
        """``scopes`` None: the grant carries them already, as a device code."""
        form = {**grant, "client_id": self.app.client_id}
        if scopes is not None:
            form["scope"] = " ".join(scopes)
        if self.app.client_secret is not None:
            form["client_secret"] = self.app.client_secret.get_secret_value()
        answer = await self._http.request(
            "POST", self.app.endpoints.token_url, form=form
        )
        body = _json(answer)
        if not answer.ok or not isinstance(body, dict):
            raise _refused(self.app.endpoints.provider, answer.status, body)
        return self._tokens(body)

    def _tokens(self, body: dict[str, Any]) -> Tokens:
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderError("the token endpoint answered without an access token")
        seconds = _seconds(body.get("expires_in"), 3600)
        refresh = body.get("refresh_token")
        id_token = body.get("id_token")
        redact.note(access)
        if isinstance(refresh, str):
            redact.note(refresh)
        return Tokens(
            access_token=SecretStr(access),
            expires_at=self.clock() + timedelta(seconds=seconds),
            refresh_token=SecretStr(refresh) if isinstance(refresh, str) else None,
            identity=identity_of(id_token) if isinstance(id_token, str) else None,
        )


def identity_of(id_token: str) -> Identity | None:
    """The address and name an ID token carries, or None if it is unreadable."""
    try:
        claims = json.loads(from_base64(id_token.split(".")[1]))
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


def _json(answer: Any) -> Any:
    try:
        return answer.json()
    except ProviderError:
        return None  # a gateway's HTML page: the status says enough


def _seconds(value: object, default: int) -> int:
    """A positive number of seconds as a provider wrote it, else ``default``."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and value.isdigit():
        seconds = int(value)
    else:
        return default
    return seconds if seconds > 0 else default


def _refused(provider: str, status: int, body: Any) -> Exception:
    """The token endpoint's error, without anything that was sent."""
    error = body.get("error") if isinstance(body, dict) else None
    if error in ("authorization_pending", "slow_down"):
        return _StillWaiting(slow_down=error == "slow_down")
    if error == "authorization_declined":
        return BadRequestError(f"the sign-in at {provider} was declined")
    if error in ("expired_token", "bad_verification_code"):
        return BadRequestError(f"the code for {provider} has expired: start again")
    if error in ("invalid_grant", "interaction_required", "consent_required"):
        # The user has to sign in again: revoked, expired, password changed.
        return ProviderAuthError(f"{provider} asks to sign in again ({error})")
    if error in ("invalid_client", "unauthorized_client"):
        return ProviderError(
            f"{provider} refused this service's app ({error}): check the "
            "client id, the secret and how the app is registered"
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
        on_refresh: Callable[[], object] | None = None,
    ) -> None:
        """``clock`` defaults to the client's: the one that stamped
        ``expires_at`` decides when a token is spent. ``on_refresh`` is
        called after each refresh, for the log of the service."""
        self._on_refresh = on_refresh
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

    def forget_refusal(self) -> None:
        self._refused = None

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
        if self._on_refresh is not None:
            self._on_refresh()
        return tokens
