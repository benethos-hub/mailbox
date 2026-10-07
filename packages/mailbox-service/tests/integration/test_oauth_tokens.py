"""OAuth: the sign-in with PKCE, tokens and their refresh. The token
endpoint is ``httpx.MockTransport``."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import (
    App,
    Identity,
    OAuthClient,
    RefreshingTokens,
    Tokens,
    authorize_url,
    identity_of,
    new_pkce,
)
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_service.errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from .test_oauth import (
    NOW,
    REDIRECT,
    Clock,
    TokenEndpoint,
    granted,
    id_token,
    oauth_client,
)

# The vault needs a key to store refresh tokens.
pytestmark = pytest.mark.usefixtures("master_key")

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
    assert "https://graph.microsoft.com/User.Read" in scopes


async def test_a_refresh_asks_only_for_what_the_adapter_needs() -> None:
    # A refresh token granted before User.Read was asked for does not
    # cover it: asking for it again would end the account's access.
    endpoint = TokenEndpoint(granted(), granted("at-2"))
    oauth = oauth_client(endpoint)
    await oauth.exchange("c", REDIRECT, "v")
    await oauth.refresh(SecretStr("rt-1"))
    exchanged, refreshed = (set(form["scope"].split()) for form in endpoint.forms)
    assert "https://graph.microsoft.com/User.Read" in exchanged
    assert "https://graph.microsoft.com/User.Read" not in refreshed
    assert refreshed == set(microsoft_endpoints().scopes)


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
    claims = base64.urlsafe_b64encode(b'["no", "object"]').decode().rstrip("=")
    assert identity_of(f"head.{claims}.sig") is None


async def test_the_code_is_exchanged() -> None:
    endpoint = TokenEndpoint(granted(id_token=id_token(email="me@example.org")))
    tokens = await oauth_client(endpoint).exchange("the-code", REDIRECT, "the-verifier")
    [form] = endpoint.forms
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code" and form["code_verifier"] == "the-verifier"
    assert form["redirect_uri"] == REDIRECT
    assert form["client_id"] == "client-1" and form["client_secret"] == "app-secret"
    assert tokens.access_token.get_secret_value() == "at-1"
    assert tokens.refresh_token is not None
    assert tokens.expires_at == NOW + timedelta(hours=1)
    assert tokens.identity is not None and tokens.identity.email == "me@example.org"
    assert endpoint.profile_bearers == ["Bearer at-1"]


async def test_the_mailbox_says_who_signed_in_not_the_id_token() -> None:
    # Anyone who manages a work or school tenant may set the email claim.
    endpoint = TokenEndpoint(granted(id_token=id_token(email="boss@example.org")))
    endpoint.profile = (
        200,
        {"mail": "Me@Example.org", "userPrincipalName": "x", "displayName": "Me"},
    )
    tokens = await oauth_client(endpoint).exchange("c", REDIRECT, "v")
    assert tokens.identity == Identity(email="me@example.org", name="Me")


async def test_without_a_mail_address_the_sign_in_name() -> None:
    endpoint = TokenEndpoint(granted())
    endpoint.profile = (200, {"mail": None, "userPrincipalName": "me@outlook.example"})
    tokens = await oauth_client(endpoint).exchange("c", REDIRECT, "v")
    assert tokens.identity == Identity(email="me@outlook.example", name=None)


@pytest.mark.parametrize("answer", [(403, {"error": "denied"}), (200, ["x"])])
async def test_a_profile_that_does_not_answer(answer: tuple[int, Any]) -> None:
    endpoint = TokenEndpoint(granted(id_token=id_token(email="me@example.org")))
    endpoint.profile = answer
    with pytest.raises(ProviderError, match="whose mailbox"):
        await oauth_client(endpoint).exchange("c", REDIRECT, "v")


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
        await oauth_client(endpoint).refresh(SecretStr("rt-secret"))
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


async def test_the_access_token_is_refreshed_before_it_runs_out() -> None:
    clock = Clock()
    endpoint = TokenEndpoint(granted("at-1", "rt-2"), granted("at-2", "rt-2"))
    stored: list[str] = []
    kept = {"refresh": SecretStr("rt-1")}

    def store(value: SecretStr) -> None:
        stored.append(value.get_secret_value())
        kept["refresh"] = value

    source = RefreshingTokens(
        oauth_client(endpoint, clock), lambda: kept["refresh"], store, clock
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
        oauth_client(endpoint),
        lambda: SecretStr("rt"),
        lambda _: None,
        lambda: NOW,
        current,
    )
    assert (await source.access_token()).get_secret_value() == "at-0"
    source.reject()
    assert (await source.access_token()).get_secret_value() == "at-1"


async def test_a_refused_refresh_is_not_asked_again() -> None:
    endpoint = TokenEndpoint((400, {"error": "invalid_grant"}), granted())
    source = RefreshingTokens(
        oauth_client(endpoint), lambda: SecretStr("rt"), lambda _: None, lambda: NOW
    )
    for _ in range(2):
        with pytest.raises(ProviderAuthError, match="sign in again"):
            await source.access_token()
    assert len(endpoint.forms) == 1


async def test_a_forgotten_refusal_is_asked_again() -> None:
    endpoint = TokenEndpoint((400, {"error": "invalid_grant"}), granted("at-1", None))
    source = RefreshingTokens(
        oauth_client(endpoint), lambda: SecretStr("rt"), lambda _: None, lambda: NOW
    )
    with pytest.raises(ProviderAuthError):
        await source.access_token()
    source.forget_refusal()
    assert (await source.access_token()).get_secret_value() == "at-1"


async def test_a_gateway_page_instead_of_json() -> None:
    def gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    app = App(microsoft_endpoints(), "client-1", SecretStr("app-secret"))
    oauth = OAuthClient(app, ApiClient(transport=httpx.MockTransport(gateway)))
    with pytest.raises(ProviderError, match="502"):
        await oauth.refresh(SecretStr("rt"))


async def test_refreshes_at_once_share_one_request() -> None:
    endpoint = TokenEndpoint(granted())
    source = RefreshingTokens(
        oauth_client(endpoint), lambda: SecretStr("rt"), lambda _: None, lambda: NOW
    )
    tokens = await asyncio.gather(*(source.access_token() for _ in range(5)))
    assert {t.get_secret_value() for t in tokens} == {"at-1"}
    assert len(endpoint.forms) == 1
