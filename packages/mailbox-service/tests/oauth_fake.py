"""OAuth from outside: a token endpoint, the adapter that signs in with its
tokens, services that connect accounts through it, a token source."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import SecretStr

from benethos_mailbox_service.assembly import (
    Services,
    build_services,
)
from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import (
    App,
    OAuthClient,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    TokenSource,
    build_provider,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_service.errors import (
    ProviderAuthError,
)

REDIRECT = "http://127.0.0.1:8080/ui/oauth/microsoft/callback"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def id_token(**claims: Any) -> str:
    """An unsigned JWT: the service reads it, the token endpoint vouches."""

    def part(value: dict[str, Any]) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


class TokenEndpoint:
    """A token endpoint: answers with ``replies`` in turn, records the forms.
    Graph's ``/me`` answers with ``profile``, else with the address and name
    the last reply's ID token carries, so a test names the account there."""

    def __init__(self, *replies: tuple[int, dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.forms: list[dict[str, str]] = []
        self.profile: tuple[int, dict[str, Any]] | None = None
        self.profile_bearers: list[str] = []
        self._claims: dict[str, Any] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.microsoft.com":
            self.profile_bearers.append(request.headers["authorization"])
            status, body = self.profile or (
                200,
                {
                    "mail": self._claims.get("email"),
                    "userPrincipalName": self._claims.get("preferred_username"),
                    "displayName": self._claims.get("name"),
                },
            )
            return httpx.Response(status, json=body)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.forms.append(form)
        status, body = self.replies.pop(0)
        token = body.get("id_token")
        self._claims = _claims(token) if isinstance(token, str) else {}
        return httpx.Response(status, json=body)


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    claims: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return claims


def granted(
    access: str = "at-1", refresh: str | None = "rt-1", **extra: Any
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {"access_token": access, "expires_in": 3600, **extra}
    if refresh is not None:
        body["refresh_token"] = refresh
    return 200, body


def oauth_client(
    endpoint: TokenEndpoint, clock: Callable[[], datetime] = lambda: NOW
) -> OAuthClient:
    app = App(microsoft_endpoints(), "client-1", SecretStr("app-secret"))
    return OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)), clock)


class SignedInProvider(MemoryProvider):
    """An adapter that, like Graph, needs an access token to verify."""

    def __init__(self, tokens: TokenSource) -> None:
        super().__init__()
        self.tokens = tokens

    async def verify(self) -> None:
        token = await self.tokens.access_token()
        if not token.get_secret_value().startswith("at-"):
            raise ProviderAuthError("bad token")


def factory(
    kind: ProviderType,
    settings: ProviderSettings,
    credentials: CredentialReader,
    /,
    *,
    tokens: TokenSource | None = None,
) -> Reads:
    if kind is ProviderType.MICROSOFT:
        assert tokens is not None
        return SignedInProvider(tokens)
    return build_provider(kind, settings, credentials)


def services_with(
    endpoint: TokenEndpoint, clock: Callable[[], datetime] = utc_now
) -> Services:
    services = build_services(
        Settings(storage="memory"),
        provider_factory=factory,
        oauth_clients={ProviderType.MICROSOFT: oauth_client(endpoint)},
        clock=clock,
    )
    services.vault.initialize()
    return services


def state_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


PENDING = (400, {"error": "authorization_pending"})


def code(**changes: Any) -> tuple[int, dict[str, Any]]:
    """The device endpoint's answer."""
    body: dict[str, Any] = {
        "device_code": "dc-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": 900,
        "interval": 5,
        **changes,
    }
    return 200, {k: v for k, v in body.items() if v is not None}


def signed_in(email: str = "me@example.org", **extra: Any) -> tuple[int, Any]:
    return granted("at-1", "rt-1", id_token=id_token(email=email), **extra)


class Tokens:
    """A token source handing out ``values`` in turn, one per rejection."""

    def __init__(self, *values: str) -> None:
        self.values = list(values)
        self.rejected = 0
        self.forgotten = 0

    async def access_token(self) -> SecretStr:
        return SecretStr(self.values[0])

    def reject(self) -> None:
        self.rejected += 1
        if len(self.values) > 1:
            self.values.pop(0)

    def forget_refusal(self) -> None:
        self.forgotten += 1
