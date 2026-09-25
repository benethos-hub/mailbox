"""The OAuth round trip through the UI and the API: off to the provider,
back through the bounce page, the account connected."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.http import ApiClient
from benethos_mailbox_api.data.models import (
    Candidate,
    Discovery,
    Grant,
    ProviderType,
)
from benethos_mailbox_api.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_api.data.providers.protocols.oauth import App, OAuthClient
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.main import Services, build_services, create_app

from .conftest import API_KEY, bearer_for
from .test_oauth import TokenEndpoint, factory, granted, id_token
from .ui_helpers import post, sign_in


@pytest.fixture(autouse=True)
def master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_API_MASTER_KEY", encode_recovery(cipher.new_key()))


@pytest.fixture
def endpoint() -> TokenEndpoint:
    return TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org", name="Me")),
        granted("at-2", "rt-2", id_token=id_token(email="me@example.org")),
    )


def build(endpoint: TokenEndpoint, **settings: Any) -> tuple[TestClient, Services]:
    config = Settings(storage="memory", api_key=SecretStr(API_KEY), **settings)
    app = App(microsoft_endpoints(), "client-1", SecretStr("app-secret"))
    client = OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)))
    services = build_services(
        config,
        provider_factory=factory,
        oauth_clients={ProviderType.MICROSOFT: client},
    )
    services.vault.initialize()
    return TestClient(create_app(config, services)), services


@pytest.fixture
def browser(endpoint: TokenEndpoint) -> tuple[TestClient, Services]:
    client, services = build(endpoint)
    sign_in(client)
    return client, services


def _start(client: TestClient, **fields: str) -> httpx.Response:
    answer = post(client, "/ui/oauth/microsoft/start", fields, follow_redirects=False)
    assert answer.status_code == 303, answer.text
    return answer


def _round_trip(client: TestClient, **fields: str) -> httpx.Response:
    location = _start(client, **fields).headers["location"]
    state = parse_qs(urlsplit(location).query)["state"][0]
    bounce = client.get(
        "/ui/oauth/microsoft/callback", params={"code": "the-code", "state": state}
    )
    target = re.search(r'url=([^"]+)"', bounce.text)
    assert target is not None
    return client.get(target.group(1).replace("&amp;", "&"))


def test_the_sign_in_is_offered(browser: tuple[TestClient, Services]) -> None:
    client, _ = browser
    page = client.get("/ui/accounts/new")
    assert "Sign in with Microsoft" in page.text
    policy = page.headers["content-security-policy"]
    assert "form-action 'self' https://login.microsoftonline.com" in policy


def test_off_to_the_provider(browser: tuple[TestClient, Services]) -> None:
    client, _ = browser
    location = _start(client, login_hint="me@example.org").headers["location"]
    parts = urlsplit(location)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.netloc == "login.microsoftonline.com"
    assert query["redirect_uri"] == "http://testserver/ui/oauth/microsoft/callback"
    assert query["login_hint"] == "me@example.org"


def test_the_redirect_uses_the_public_url(endpoint: TokenEndpoint) -> None:
    client, _ = build(endpoint, public_url="https://mail.example.org/")
    sign_in(client)
    location = _start(client).headers["location"]
    redirect = parse_qs(urlsplit(location).query)["redirect_uri"][0]
    assert redirect == "https://mail.example.org/ui/oauth/microsoft/callback"


def test_back_through_the_bounce_page(browser: tuple[TestClient, Services]) -> None:
    client, services = browser
    # As the browser comes back from the provider: without the session.
    bounce = TestClient(client.app).get(
        "/ui/oauth/microsoft/callback",
        params={"code": "c", "state": "s", "other": "dropped"},
    )
    assert bounce.status_code == 200
    assert 'http-equiv="refresh"' in bounce.text
    assert "/ui/oauth/microsoft/finish?code=c&amp;state=s" in bounce.text
    assert "dropped" not in bounce.text
    finished = _round_trip(client)
    assert "me@example.org signed in." in finished.text
    [account_id] = services.adapters.ids()
    assert finished.url.path == f"/ui/accounts/{account_id}"
    assert "Sign in again" in finished.text and "New password" not in finished.text


def test_finish_needs_a_session(endpoint: TokenEndpoint) -> None:
    client, _ = build(endpoint)
    answer = client.get(
        "/ui/oauth/microsoft/finish",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert answer.status_code == 303
    assert answer.headers["location"].startswith("/ui/login")


def test_the_provider_refused(browser: tuple[TestClient, Services]) -> None:
    client, services = browser
    location = _start(client).headers["location"]
    state = parse_qs(urlsplit(location).query)["state"][0]
    answer = client.get(
        "/ui/oauth/microsoft/finish",
        params={
            "state": state,
            "error": "access_denied",
            "error_description": "the user said no",
        },
    )
    assert "microsoft did not sign in: the user said no" in answer.text
    again = client.get(
        "/ui/oauth/microsoft/finish", params={"state": state, "code": "c"}
    )
    assert "unknown or expired" in again.text
    assert services.adapters.ids() == []


def test_sign_in_again(browser: tuple[TestClient, Services]) -> None:
    client, services = browser
    _round_trip(client)
    [account_id] = services.adapters.ids()
    location = _start(client, account_id=account_id).headers["location"]
    assert parse_qs(urlsplit(location).query)["login_hint"] == ["me@example.org"]


def test_an_unknown_provider(browser: tuple[TestClient, Services]) -> None:
    client, _ = browser
    answer = post(client, "/ui/oauth/carrier-pigeon/start", follow_redirects=False)
    assert "Unknown+provider" in answer.headers["location"]


def test_discovery_offers_the_sign_in(browser: tuple[TestClient, Services]) -> None:
    client, _ = browser

    class Found:
        async def discover(self, caller: Any, email: str) -> Discovery:
            return Discovery(
                email=email,
                domain="example.org",
                candidates=[
                    Candidate(
                        provider=ProviderType.IMAP,
                        name="Outlook.com",
                        credential="oauth",
                        oauth_provider="microsoft",
                        source="preset",
                        confirmed=True,
                    )
                ],
            )

    client.app.state.discovery = Found()  # type: ignore[attr-defined]
    page = post(client, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert "2. Outlook.com" in page
    assert 'name="login_hint" value="me@example.org"' in page
    assert "Sign in with Microsoft" in page


# --- the API --------------------------------------------------------------------------


def test_the_api_starts_a_sign_in(endpoint: TokenEndpoint) -> None:
    client, _ = build(endpoint)
    answer = client.post(
        "/v1/oauth/microsoft/start",
        json={"login_hint": "me@example.org"},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert answer.status_code == 200, answer.text
    url = answer.json()["url"]
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/")
    assert (
        "redirect_uri=http%3A%2F%2Ftestserver%2Fui%2Foauth%2Fmicrosoft%2Fcallback"
        in url
    )


def test_the_api_without_an_app(client: TestClient) -> None:
    answer = client.post("/v1/oauth/microsoft/start", json={})
    assert answer.status_code == 501
    assert answer.json()["error"]["code"] == "not_supported"


def test_the_api_needs_the_right(endpoint: TokenEndpoint) -> None:
    client, services = build(endpoint)
    headers = bearer_for(services, Grant(accounts=["*"], allow=["mail.read"]))
    answer = client.post("/v1/oauth/microsoft/start", json={}, headers=headers)
    assert answer.status_code == 403
