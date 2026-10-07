"""OAuth: the flow that connects an account. The token endpoint is
``httpx.MockTransport``. The fakes here serve the other OAuth tests too."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
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
from benethos_mailbox_service.domain.accounts.adapters import REFRESH_TOKEN
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ForbiddenError,
    NotSupportedError,
    ProviderAuthError,
)

from ..conftest import ADMIN

# The vault needs a key to store refresh tokens.
pytestmark = pytest.mark.usefixtures("master_key")

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


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


# --- connecting an account ------------------------------------------------------------


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


async def test_connect_an_account() -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="Me@Example.org", name="Me"))
    )
    services = services_with(endpoint)
    url = services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT)
    account = await services.oauth.finish(
        ADMIN, ProviderType.MICROSOFT, state_of(url), "the-code"
    )
    assert account.email == "me@example.org" and account.display_name == "Me"
    assert account.provider is ProviderType.MICROSOFT
    assert [c.field for c in account.credentials] == [REFRESH_TOKEN]
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-1"
    # The sign-in's own tokens verified it: one request only.
    assert len(endpoint.forms) == 1
    assert services.oauth.providers() == [ProviderType.MICROSOFT]


async def test_a_state_is_used_once() -> None:
    services = services_with(TokenEndpoint(granted(id_token=id_token(email="a@b.c"))))
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")


async def test_a_state_expires() -> None:
    clock = Clock()
    services = services_with(TokenEndpoint(), clock)
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    clock.now += timedelta(minutes=11)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")


async def test_only_the_starter_cancels_a_sign_in() -> None:
    services = services_with(TokenEndpoint(granted(id_token=id_token(email="a@b.c"))))
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    services.oauth.cancel(Access.admin("usr_other", "other admin"), state)
    await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    services.oauth.cancel(ADMIN, state)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")


async def test_a_sign_in_belongs_to_who_started_it() -> None:
    services = services_with(TokenEndpoint(granted(id_token=id_token(email="a@b.c"))))
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    other = Access.admin("usr_other", "other admin")
    # Answered as an unknown one, so nobody learns it exists.
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(other, ProviderType.MICROSOFT, state, "c")
    # And it stays open for whoever started it.
    await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    assert len(services.adapters.ids()) == 1


def test_connecting_needs_the_right() -> None:
    services = services_with(TokenEndpoint())
    reader = Access("usr_r", "reader", [Grant(accounts=["*"], allow=["mail.read"])])
    with pytest.raises(ForbiddenError):
        services.oauth.start(reader, ProviderType.MICROSOFT, REDIRECT)


def test_without_an_app_there_is_no_sign_in() -> None:
    services = build_services(Settings(storage="memory"), oauth_clients={})
    with pytest.raises(NotSupportedError, match="no OAuth app"):
        services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT)
    assert services.oauth.providers() == []


async def test_no_refresh_token_no_account() -> None:
    services = services_with(TokenEndpoint(granted(refresh=None)))
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    with pytest.raises(BadRequestError, match="offline_access"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    assert services.adapters.ids() == []


async def test_sign_in_again_with_the_same_address_only() -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org")),
        granted("at-2", "rt-2", id_token=id_token(email="other@example.org")),
        granted("at-3", "rt-3", id_token=id_token(email="me@example.org")),
    )
    services = services_with(endpoint)
    oauth = services.oauth
    state = state_of(oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    account = await oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")

    url = oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT, account_id=account.id)
    assert parse_qs(urlsplit(url).query)["login_hint"] == ["me@example.org"]
    with pytest.raises(BadRequestError, match="sign in with that address"):
        await oauth.finish(ADMIN, ProviderType.MICROSOFT, state_of(url), "c")
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-1"

    url = oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT, account_id=account.id)
    await oauth.finish(ADMIN, ProviderType.MICROSOFT, state_of(url), "c")
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-3"


async def test_sign_in_again_needs_no_read_right() -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org")),
        granted("at-2", "rt-2", id_token=id_token(email="me@example.org")),
    )
    services = services_with(endpoint)
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    account = await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    manager = Access(
        "usr_m", "manager", [Grant(accounts=[account.id], allow=["accounts.manage"])]
    )
    url = services.oauth.start(
        manager, ProviderType.MICROSOFT, REDIRECT, account_id=account.id
    )
    await services.oauth.finish(manager, ProviderType.MICROSOFT, state_of(url), "c")
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-2"


async def test_a_connected_account_refreshes_and_keeps_the_rotation() -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org")),
        granted("at-2", "rt-2"),
    )
    services = services_with(endpoint)
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    account = await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    # After a restart the adapter has only the stored refresh token.
    adapter = services.adapters.get(account.id)
    assert isinstance(adapter, SignedInProvider)
    await services.accounts.verify(ADMIN, account.id)
    assert endpoint.forms[1]["refresh_token"] == "rt-1"
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-2"


async def test_a_revoked_sign_in_needs_a_new_one() -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org")),
        (400, {"error": "invalid_grant"}),
    )
    services = services_with(endpoint)
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    account = await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    with pytest.raises(ProviderAuthError):
        await services.accounts.verify(ADMIN, account.id)
    assert services.adapters.status(account.id).value == "needs_reauth"


def test_the_client_secret_from_a_file(tmp_path: Any) -> None:
    secret = tmp_path / "microsoft_client_secret"
    secret.write_text("from-a-file\n", encoding="utf-8")
    settings = Settings(
        oauth_microsoft_client_id="client-1",
        oauth_microsoft_client_secret_file=secret,
        oauth_microsoft_client_secret=SecretStr("from-the-environment"),
    )
    found = settings.oauth_microsoft_secret()
    assert found is not None and found.get_secret_value() == "from-a-file"


async def test_a_query_in_the_url_is_kept() -> None:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    api = ApiClient(transport=httpx.MockTransport(record))
    await api.request("GET", "https://graph.example/next?%24skip=10")
    await api.request("GET", "https://graph.example/list", params={"$top": "5"})
    assert seen == [
        "https://graph.example/next?%24skip=10",
        "https://graph.example/list?%24top=5",
    ]


def test_the_registry_knows_how_a_provider_signs_in() -> None:
    from benethos_mailbox_service.data.providers import sign_in

    endpoints = sign_in(ProviderType.MICROSOFT)
    assert endpoints.provider == "microsoft" and "/common/" in endpoints.token_url
    assert "/consumers/" in sign_in(ProviderType.MICROSOFT, "consumers").token_url
    with pytest.raises(NotSupportedError, match="do not sign in with OAuth"):
        sign_in(ProviderType.IMAP)
