"""Talking to a provider: the address the browser is sent to with PKCE,
and the token endpoint, for the code the browser came back with, a code
for another device, and a refresh.

What the provider answers is read in ``answers``. Keeping an access
token valid is ``tokens``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.parse import urlencode

from pydantic import SecretStr

from benethos_mailbox_common.log import redact
from benethos_mailbox_common.values import secret

from ....common.clock import utc_now
from ....common.opaque import to_base64
from ....errors import NotSupportedError, ProviderError
from .. import wire
from ..http import ApiClient
from .answers import (
    Code,
    Fields,
    Granted,
    StillWaitingError,
    error_of,
    identity_of,
    refusal,
)
from .values import App, DeviceCode, Identity, Pkce, Profile, Tokens, Waiting

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# What RFC 8628 suggests where the provider names no lifetime or interval.
DEVICE_LIFETIME = 900
DEVICE_INTERVAL = 5


def new_pkce() -> Pkce:
    """A code verifier and its S256 challenge (RFC 7636)."""
    # 64 bytes: 86 characters, within the 43 to 128 the RFC allows.
    verifier = secret.token(64)
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
        "scope": " ".join(app.endpoints.sign_in_scopes),
        "state": state,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        **dict(app.endpoints.authorize_params),
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
        error = error_of(answer)
        if error in ("invalid_client", "unauthorized_client"):
            # Microsoft: AADSTS70002, the app is no public client.
            raise ProviderError(
                f"{endpoints.provider} refuses a sign-in with a code for this "
                f"service's app ({error}): the app must allow public client flows"
            )
        if not answer.ok:
            raise refusal(endpoints.provider, answer.status, error)
        without = f"{endpoints.provider} answered without a code"
        code = wire.parse(Code, answer.body, without)
        uri = code.verification_uri or code.verification_url
        if not uri:
            raise ProviderError(without)
        if not uri.startswith("https://"):
            raise ProviderError(
                f"{endpoints.provider} named a sign-in page without HTTPS"
            )
        redact.note(code.device_code)
        return DeviceCode(
            device_code=SecretStr(code.device_code),
            user_code=code.user_code,
            verification_uri=uri,
            expires_in=code.expires_in or DEVICE_LIFETIME,
            interval=code.interval or DEVICE_INTERVAL,
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
        except StillWaitingError as waiting:
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
        unknown = f"{provider} did not say whose mailbox this is ({answer.status})"
        if not answer.ok:
            raise ProviderError(unknown)
        fields = wire.parse(Fields, answer.body, unknown).root
        email = next((v for f in profile.email if (v := fields.get(f))), None)
        name = fields.get(profile.name) if profile.name else None
        return Identity(
            email=email.strip().lower() if email else None,
            name=name or None,
        )

    async def refresh(self, refresh_token: SecretStr) -> Tokens:
        """New tokens for a refresh token. The provider may hand out a new
        refresh token too. The old one may then stop working."""
        endpoints = self.app.endpoints
        return await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.get_secret_value(),
            },
            endpoints.scopes if endpoints.refresh_scopes else None,
        )

    async def _token(
        self, grant: dict[str, str], scopes: tuple[str, ...] | None
    ) -> Tokens:
        """``scopes`` None: the grant carries them already, as a device
        code, or the provider takes them from the refresh token."""
        form = {**grant, "client_id": self.app.client_id}
        if scopes is not None:
            form["scope"] = " ".join(scopes)
        if self.app.client_secret is not None:
            form["client_secret"] = self.app.client_secret.get_secret_value()
        answer = await self._http.request(
            "POST", self.app.endpoints.token_url, form=form
        )
        if not answer.ok:
            raise refusal(self.app.endpoints.provider, answer.status, error_of(answer))
        granted = wire.parse(
            Granted,
            answer.body,
            "the token endpoint answered without an access token",
        )
        return self._tokens(granted)

    def _tokens(self, granted: Granted) -> Tokens:
        redact.note(granted.access_token)
        refresh = granted.refresh_token
        if refresh is not None:
            redact.note(refresh)
        seconds = granted.expires_in or 3600
        return Tokens(
            access_token=SecretStr(granted.access_token),
            expires_at=self.clock() + timedelta(seconds=seconds),
            refresh_token=SecretStr(refresh) if refresh is not None else None,
            identity=identity_of(granted.id_token) if granted.id_token else None,
        )
