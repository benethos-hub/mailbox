"""OAuth: the sign-in with PKCE, tokens and their refresh, the flow that
connects an account. The token endpoint is ``httpx.MockTransport``."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.http import ApiClient
from benethos_mailbox_api.data.models import Grant, ProviderType
from benethos_mailbox_api.data.providers import (
    CredentialReader,
    MailProvider,
    ProviderSettings,
    TokenSource,
    build_provider,
)
from benethos_mailbox_api.data.providers.memory import MemoryProvider
from benethos_mailbox_api.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_api.data.providers.protocols.oauth import (
    App,
    OAuthClient,
    RefreshingTokens,
    Tokens,
    authorize_url,
    identity_of,
    new_pkce,
)
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.domain.access import Access
from benethos_mailbox_api.domain.accounts import REFRESH_TOKEN
from benethos_mailbox_api.errors import (
    BadRequestError,
    ForbiddenError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from benethos_mailbox_api.main import Services, build_services

from .conftest import ADMIN


@pytest.fixture(autouse=True)
def master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The vault needs a key to store refresh tokens."""
    monkeypatch.setenv("MAILBOX_API_MASTER_KEY", encode_recovery(cipher.new_key()))


REDIRECT = "http://127.0.0.1:8080/ui/oauth/microsoft/callback"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def id_token(**claims: Any) -> str:
    """An unsigned JWT: the service reads it, the token endpoint vouches."""

    def part(value: dict[str, Any]) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


class TokenEndpoint:
    """A token endpoint: answers with ``replies`` in turn, records the forms."""

    def __init__(self, *replies: tuple[int, dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.forms: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.forms.append(form)
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)


def granted(
    access: str = "at-1", refresh: str | None = "rt-1", **extra: Any
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {"access_token": access, "expires_in": 3600, **extra}
    if refresh is not None:
        body["refresh_token"] = refresh
    return 200, body


def client(
    endpoint: TokenEndpoint, clock: Callable[[], datetime] = lambda: NOW
) -> OAuthClient:
    app = App(microsoft_endpoints(), "client-1", SecretStr("app-secret"))
    return OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)), clock)


# --- the pieces -----------------------------------------------------------------------


def test_pkce_challenge_is_the_s256_of_the_verifier() -> None:
    pkce = new_pkce()
    digest = hashlib.sha256(pkce.verifier.encode()).digest()
    assert pkce.challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert len(pkce.verifier) >= 43


def test_the_sign_in_address() -> None:
    app = App(microsoft_endpoints("consumers"), "client-1")
    url = authorize_url(app, REDIRECT, "st", new_pkce(), login_hint="a@example.org")
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.netloc == "login.microsoftonline.com"
    assert parts.path == "/consumers/oauth2/v2.0/authorize"
    assert query["client_id"] == "client-1" and query["state"] == "st"
    assert query["redirect_uri"] == REDIRECT
    assert query["code_challenge_method"] == "S256"
    assert query["login_hint"] == "a@example.org"
    scopes = query["scope"].split()
    assert "offline_access" in scopes
    assert "https://graph.microsoft.com/Mail.Send" in scopes


@pytest.mark.parametrize(
    "tenant", ["common", "organizations", "contoso.onmicrosoft.com"]
)
def test_tenants(tenant: str) -> None:
    assert f"/{tenant}/" in microsoft_endpoints(tenant).token_url


def test_a_tenant_cannot_change_the_host() -> None:
    with pytest.raises(BadRequestError):
        microsoft_endpoints("evil.example/x?")


def test_identity_from_the_id_token() -> None:
    who = identity_of(id_token(preferred_username="Me@Example.org", name="Me"))
    assert who is not None and who.email == "me@example.org" and who.name == "Me"
    assert identity_of("not a token") is None


async def test_the_code_is_exchanged() -> None:
    endpoint = TokenEndpoint(granted(id_token=id_token(email="me@example.org")))
    tokens = await client(endpoint).exchange("the-code", REDIRECT, "the-verifier")
    [form] = endpoint.forms
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code" and form["code_verifier"] == "the-verifier"
    assert form["redirect_uri"] == REDIRECT
    assert form["client_id"] == "client-1" and form["client_secret"] == "app-secret"
    assert tokens.access_token.get_secret_value() == "at-1"
    assert tokens.refresh_token is not None
    assert tokens.expires_at == NOW + timedelta(hours=1)
    assert tokens.identity is not None and tokens.identity.email == "me@example.org"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        ("invalid_grant", ProviderAuthError),
        ("interaction_required", ProviderAuthError),
        ("invalid_client", ProviderError),
        ("server_error", ProviderError),
    ],
)
async def test_refusals(error: str, kind: type[Exception]) -> None:
    endpoint = TokenEndpoint((400, {"error": error, "error_description": "x"}))
    with pytest.raises(kind) as raised:
        await client(endpoint).refresh(SecretStr("rt-secret"))
    assert error in str(raised.value)
    assert "rt-secret" not in str(raised.value) and "app-secret" not in str(
        raised.value
    )


async def test_only_https() -> None:
    with pytest.raises(ProviderError, match="HTTPS only"):
        await ApiClient().request("GET", "http://example.org/")


async def test_an_unreachable_host() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    api = ApiClient(transport=httpx.MockTransport(fail))
    with pytest.raises(ProviderUnavailableError, match="did not answer in time"):
        await api.request("GET", "https://login.example/")


async def test_an_answer_too_large() -> None:
    api = ApiClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 20)),
        max_bytes=10,
    )
    with pytest.raises(ProviderError, match="larger than"):
        await api.request("GET", "https://login.example/")


# --- refreshing -----------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


async def test_the_access_token_is_refreshed_before_it_runs_out() -> None:
    clock = Clock()
    endpoint = TokenEndpoint(granted("at-1", "rt-2"), granted("at-2", "rt-2"))
    stored: list[str] = []
    kept = {"refresh": SecretStr("rt-1")}

    def store(value: SecretStr) -> None:
        stored.append(value.get_secret_value())
        kept["refresh"] = value

    source = RefreshingTokens(
        client(endpoint, clock), lambda: kept["refresh"], store, clock
    )
    assert (await source.access_token()).get_secret_value() == "at-1"
    assert (await source.access_token()).get_secret_value() == "at-1"
    assert len(endpoint.forms) == 1
    assert endpoint.forms[0]["refresh_token"] == "rt-1"
    # Rotated: stored at once.
    assert stored == ["rt-2"]
    clock.now += timedelta(minutes=59, seconds=30)
    assert (await source.access_token()).get_secret_value() == "at-2"
    assert endpoint.forms[1]["refresh_token"] == "rt-2"
    # The same refresh token again: nothing to store.
    assert stored == ["rt-2"]


async def test_a_rejected_token_is_fetched_anew() -> None:
    endpoint = TokenEndpoint(granted("at-1", None), granted("at-2", None))
    current = Tokens(SecretStr("at-0"), NOW + timedelta(hours=1), None)
    source = RefreshingTokens(
        client(endpoint), lambda: SecretStr("rt"), lambda _: None, lambda: NOW, current
    )
    assert (await source.access_token()).get_secret_value() == "at-0"
    source.reject()
    assert (await source.access_token()).get_secret_value() == "at-1"


async def test_refreshes_at_once_share_one_request() -> None:
    endpoint = TokenEndpoint(granted())
    source = RefreshingTokens(
        client(endpoint), lambda: SecretStr("rt"), lambda _: None, lambda: NOW
    )
    tokens = await asyncio.gather(*(source.access_token() for _ in range(5)))
    assert {t.get_secret_value() for t in tokens} == {"at-1"}
    assert len(endpoint.forms) == 1


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
) -> MailProvider:
    if kind is ProviderType.MICROSOFT:
        assert tokens is not None
        return SignedInProvider(tokens)
    return build_provider(kind, settings, credentials)


def services_with(endpoint: TokenEndpoint) -> Services:
    services = build_services(
        Settings(storage="memory"),
        provider_factory=factory,
        oauth_clients={ProviderType.MICROSOFT: client(endpoint)},
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
    services = services_with(TokenEndpoint())
    clock = Clock()
    services.oauth._clock = clock  # type: ignore[attr-defined]
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    clock.now += timedelta(minutes=11)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")


async def test_a_sign_in_belongs_to_who_started_it() -> None:
    services = services_with(TokenEndpoint())
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    other = Access.admin("usr_other", "other admin")
    with pytest.raises(ForbiddenError, match="someone else"):
        await services.oauth.finish(other, ProviderType.MICROSOFT, state, "c")


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
    assert services.accounts.all_ids() == []


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


async def test_a_connected_account_refreshes_and_keeps_the_rotation() -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org")),
        granted("at-2", "rt-2"),
    )
    services = services_with(endpoint)
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    account = await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    # After a restart the adapter has only the stored refresh token.
    adapter = services.accounts.provider(account.id)
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
    assert services.accounts.status(account.id).value == "needs_reauth"


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
    from benethos_mailbox_api.data.providers import sign_in

    endpoints = sign_in(ProviderType.MICROSOFT)
    assert endpoints.provider == "microsoft" and "/common/" in endpoints.token_url
    assert "/consumers/" in sign_in(ProviderType.MICROSOFT, "consumers").token_url
    with pytest.raises(NotSupportedError, match="do not sign in with OAuth"):
        sign_in(ProviderType.IMAP)
