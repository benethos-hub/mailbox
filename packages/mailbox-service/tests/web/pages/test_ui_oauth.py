"""The OAuth round trip through the UI and the API: off to the provider,
back through the bounce page, the account connected."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Candidate,
    Discovery,
    Grant,
    ProviderType,
)
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)

from ...conftest import CHEAP, admin_bearer, bearer_for, browser_admin
from ...integration.test_oauth import (
    Clock,
    TokenEndpoint,
    factory,
    granted,
    id_token,
)
from ...integration.test_oauth_device import PENDING, code, signed_in
from ...ui_helpers import csrf_of, post, sign_in

pytestmark = pytest.mark.usefixtures("master_key")


@pytest.fixture
def endpoint() -> TokenEndpoint:
    return TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org", name="Me")),
        granted("at-2", "rt-2", id_token=id_token(email="me@example.org")),
    )


def build(
    endpoint: TokenEndpoint,
    clock: Clock | None = None,
    app: App | None = None,
    **settings: Any,
) -> tuple[TestClient, Services]:
    config = Settings(storage="memory", **settings)
    app = app or App(microsoft_endpoints(), "client-1", SecretStr("app-secret"))
    client = OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)))
    services = build_services(
        config,
        provider_factory=factory,
        oauth_clients={ProviderType.MICROSOFT: client},
        password_hasher=CHEAP,
        **({"clock": clock} if clock is not None else {}),
    )
    services.vault.initialize()
    return TestClient(create_app(config, services)), services


@pytest.fixture
def browser(endpoint: TokenEndpoint) -> tuple[TestClient, Services]:
    client, services = build(endpoint)
    sign_in(client, *browser_admin(services))
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
    # Connecting starts with the address and nothing else.
    assert "Sign in with Microsoft" not in page.text
    policy = page.headers["content-security-policy"]
    assert "form-action 'self' https://login.microsoftonline.com" in policy

    class NothingFound:
        async def discover(self, caller: Any, email: str) -> Discovery:
            return Discovery(email=email, domain="example.org")

    client.app.state.services = replace(  # type: ignore[attr-defined]
        client.app.state.services, discovery=NothingFound()
    )
    page = post(client, "/ui/accounts/discover", {"email": "me@example.org"})
    # A custom domain at Microsoft is found by no source: the way stays.
    assert "Sign in with Microsoft" in page.text
    assert 'name="login_hint" value="me@example.org"' in page.text


def test_off_to_the_provider(browser: tuple[TestClient, Services]) -> None:
    client, _ = browser
    location = _start(client, login_hint="me@example.org").headers["location"]
    parts = urlsplit(location)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.netloc == "login.microsoftonline.com"
    assert query["redirect_uri"] == "http://testserver/ui/oauth/microsoft/callback"
    assert query["login_hint"] == "me@example.org"


def test_the_redirect_uses_the_public_url(endpoint: TokenEndpoint) -> None:
    client, services = build(endpoint, public_url="https://mail.example.org/")
    sign_in(client, *browser_admin(services))
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


def test_a_made_up_refusal_shows_no_words_of_its_own(
    browser: tuple[TestClient, Services],
) -> None:
    client, _ = browser
    answer = client.get(
        "/ui/oauth/microsoft/finish",
        params={
            "state": "made-up",
            "error": "access_denied",
            "error_description": "Your account is locked. Call this number",
        },
    )
    assert "microsoft did not sign in." in answer.text
    assert "Call this number" not in answer.text


def test_sign_in_again(browser: tuple[TestClient, Services]) -> None:
    client, services = browser
    _round_trip(client)
    [account_id] = services.adapters.ids()
    location = _start(client, account_id=account_id).headers["location"]
    assert parse_qs(urlsplit(location).query)["login_hint"] == ["me@example.org"]


def test_an_unknown_provider(browser: tuple[TestClient, Services]) -> None:
    client, _ = browser
    answer = post(client, "/ui/oauth/carrier-pigeon/start")
    assert "Unknown provider" in answer.text


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

    client.app.state.services = replace(  # type: ignore[attr-defined]
        client.app.state.services, discovery=Found()
    )
    page = post(client, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert "<h2>Outlook.com</h2>" in page and "recommended" in page
    # Found, so setting it up by hand stays folded.
    assert '<details class="card way">' in page
    assert 'name="login_hint" value="me@example.org"' in page
    assert "Sign in with Microsoft" in page


# --- the API --------------------------------------------------------------------------


def test_the_api_has_no_sign_in_in_a_browser(endpoint: TokenEndpoint) -> None:
    """The provider sends the browser back to the UI, which an API caller
    never sees: the API signs in with a code."""
    client, services = build(endpoint)
    answer = client.post(
        "/v1/oauth/microsoft/start", json={}, headers=admin_bearer(services)
    )
    assert answer.status_code == 404


def test_the_api_where_microsoft_is_not_offered(endpoint: TokenEndpoint) -> None:
    client, services = build(endpoint, providers=["imap", "jmap"])
    answer = client.post(
        "/v1/oauth/microsoft/device", json={}, headers=admin_bearer(services)
    )
    assert answer.status_code == 501
    assert answer.json()["error"]["code"] == "not_supported"
    assert "cannot be connected" in answer.json()["error"]["message"]


def test_the_api_needs_the_right(endpoint: TokenEndpoint) -> None:
    client, services = build(endpoint)
    headers = bearer_for(services, Grant(accounts=["*"], allow=["mail.read"]))
    answer = client.post("/v1/oauth/microsoft/device", json={}, headers=headers)
    assert answer.status_code == 403


def test_the_api_signs_in_with_a_code() -> None:
    clock = Clock()
    client, services = build(TokenEndpoint(code(), PENDING, signed_in()), clock)
    headers = admin_bearer(services)
    started = client.post("/v1/oauth/microsoft/device", json={}, headers=headers)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["user_code"] == "ABCD-EFGH" and body["interval"] == 5
    assert body["verification_uri"] == "https://microsoft.com/devicelogin"
    assert "dc-secret" not in started.text
    poll = f"/v1/oauth/microsoft/device/{body['sign_in_id']}"
    assert client.post(poll, headers=headers).json() == {
        "connected": False,
        "account": None,
    }
    clock.now += timedelta(seconds=10)
    assert client.post(poll, headers=headers).json()["connected"] is False
    clock.now += timedelta(seconds=5)
    done = client.post(poll, headers=headers).json()
    assert done["connected"] is True
    assert done["account"]["email"] == "me@example.org"
    assert client.post(poll, headers=headers).json() == done
    gone = client.post(
        "/v1/oauth/microsoft/device/made-up", headers=admin_bearer(services)
    )
    assert gone.status_code == 400


# --- signing in with a code in the UI -------------------------------------------------


def _with_code(
    endpoint: TokenEndpoint, **settings: Any
) -> tuple[TestClient, Services, Clock]:
    clock = Clock()
    client, services = build(endpoint, clock, **settings)
    sign_in(client, *browser_admin(services))
    return client, services, clock


def _check(client: TestClient, url: str, htmx: bool = True) -> httpx.Response:
    """What the code page asks, by htmx or with Check now."""
    token = csrf_of(client.get("/ui").text)
    headers = {"HX-Request": "true", "X-CSRF-Token": token} if htmx else {}
    return client.post(
        url,
        data={"csrf_token": token, "back": "/ui/accounts/new"},
        headers=headers,
        follow_redirects=False,
    )


def _code_page(client: TestClient, **fields: str) -> tuple[str, str]:
    """The page with the code, and where it asks."""
    page = post(client, "/ui/oauth/microsoft/device", fields)
    assert page.status_code == 200, page.text
    found = re.search(r'hx-post="(/ui/oauth/microsoft/device/[^"]+)"', page.text)
    assert found is not None
    return page.text, found.group(1)


def test_sign_in_with_a_code() -> None:
    client, services, clock = _with_code(TokenEndpoint(code(), PENDING, signed_in()))
    page, url = _code_page(client)
    assert '<code class="secret">ABCD-EFGH</code>' in page
    assert 'href="https://microsoft.com/devicelogin"' in page
    assert 'hx-trigger="every 5s"' in page
    # Nothing yet: htmx swaps nothing and asks again.
    answer = _check(client, url)
    assert answer.status_code == 204 and "HX-Redirect" not in answer.headers
    clock.now += timedelta(seconds=5)
    assert _check(client, url).status_code == 204
    clock.now += timedelta(seconds=5)
    answer = _check(client, url)
    [account_id] = services.adapters.ids()
    assert answer.headers["HX-Redirect"] == f"/ui/accounts/{account_id}"
    landed = client.get(answer.headers["HX-Redirect"]).text
    assert "me@example.org signed in." in landed
    assert "Sign in again with a code" in landed


def test_check_now_without_script() -> None:
    client, _, clock = _with_code(TokenEndpoint(code(), signed_in()))
    _, url = _code_page(client)
    answer = _check(client, url, htmx=False)
    assert answer.status_code == 200
    assert "microsoft has not seen the sign-in yet." in answer.text
    assert "ABCD-EFGH" in answer.text
    clock.now += timedelta(seconds=5)
    answer = _check(client, url, htmx=False)
    assert answer.status_code == 303
    assert answer.headers["location"].startswith("/ui/accounts/acc_")


def test_a_declined_code_goes_back() -> None:
    client, _, clock = _with_code(
        TokenEndpoint(code(), (400, {"error": "authorization_declined"}))
    )
    _, url = _code_page(client)
    clock.now += timedelta(seconds=5)
    answer = _check(client, url)
    assert answer.headers["HX-Redirect"] == "/ui/accounts/new"
    assert "was declined" in client.get("/ui/accounts/new").text
    answer = _check(client, url, htmx=False)
    assert answer.status_code == 303
    assert "unknown or expired" in client.get(answer.headers["location"]).text


def test_a_code_for_an_unknown_provider() -> None:
    client, _, _ = _with_code(TokenEndpoint())
    answer = post(client, "/ui/oauth/carrier-pigeon/device")
    assert "Unknown provider" in answer.text
    answer = _check(client, "/ui/oauth/carrier-pigeon/device/x", htmx=False)
    assert answer.headers["location"] == "/ui/accounts"


def test_a_code_the_provider_refuses_to_hand_out() -> None:
    client, _, _ = _with_code(TokenEndpoint((400, {"error": "invalid_client"})))
    answer = post(client, "/ui/oauth/microsoft/device")
    assert "must allow public client flows" in answer.text


@pytest.mark.parametrize(
    ("offered", "shown", "hidden"),
    [
        (["microsoft"], [], ["Set up by hand", "Set up a JMAP server by hand"]),
        (
            ["pop3"],
            ['value="pop3"', "Set up by hand"],
            ['value="imap"', "JMAP server by hand"],
        ),
        (["imap", "jmap"], ['value="imap"', "JMAP server by hand"], ['"pop3"']),
    ],
)
def test_the_connect_page_offers_what_the_deployment_does(
    offered: list[str], shown: list[str], hidden: list[str]
) -> None:
    client, _, _ = _with_code(TokenEndpoint(), providers=offered)

    class NothingFound:
        async def discover(self, caller: Any, email: str) -> Discovery:
            return Discovery(email=email, domain="example.org")

    client.app.state.services = replace(  # type: ignore[attr-defined]
        client.app.state.services, discovery=NothingFound()
    )
    page = post(client, "/ui/accounts/discover", {"email": "me@example.org"}).text
    for text in shown:
        assert text in page
    for text in hidden:
        assert text not in page
    assert ("Sign in with Microsoft" in page) == ("microsoft" in offered)


def test_with_the_project_app_away_from_localhost_only_the_code() -> None:
    project = App(microsoft_endpoints(), "project-app", loopback_only=True)
    endpoint = TokenEndpoint(code(), signed_in())
    clock = Clock()
    client, services = build(
        endpoint, clock, app=project, public_url="https://mail.example.org"
    )
    sign_in(client, *browser_admin(services))

    class NothingFound:
        async def discover(self, caller: Any, email: str) -> Discovery:
            return Discovery(email=email, domain="example.org")

    client.app.state.services = replace(  # type: ignore[attr-defined]
        client.app.state.services, discovery=NothingFound()
    )
    page = post(client, "/ui/accounts/discover", {"email": "me@example.org"}).text
    assert 'action="/ui/oauth/microsoft/start"' not in page
    assert "Sign in with Microsoft and a code" in page
    assert "only at localhost" in page
    answer = post(client, "/ui/oauth/microsoft/start")
    assert "sign in with a code" in answer.text
    # Connected with the code, the account page offers the code again only.
    _, url = _code_page(client)
    clock.now += timedelta(seconds=5)
    landed = client.get(_check(client, url).headers["HX-Redirect"]).text
    assert "Sign in again with a code" in landed
    assert 'action="/ui/oauth/microsoft/start"' not in landed
