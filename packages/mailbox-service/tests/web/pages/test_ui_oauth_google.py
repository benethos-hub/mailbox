"""Signing in with Google through the UI: Gmail over the Gmail API, with
a Google client of the deployment's own."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Candidate, Discovery, ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.data.providers.gmail import endpoints as gmail_endpoints

from ...conftest import CHEAP, browser_admin
from ...integration.test_oauth import TokenEndpoint, factory, granted
from ...ui_helpers import post, sign_in

pytestmark = pytest.mark.usefixtures("master_key")


@pytest.fixture
def endpoint() -> TokenEndpoint:
    return TokenEndpoint(granted("at-1", "rt-1"))


def test_gmail_signs_in_at_google_in_the_browser(endpoint: TokenEndpoint) -> None:
    """Google offers no code for Gmail: the browser is the only way."""
    config = Settings(storage="memory")
    app = App(gmail_endpoints(), "client-1", SecretStr("app-secret"))
    google = OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)))
    services = build_services(
        config,
        provider_factory=factory,
        oauth_clients={ProviderType.GMAIL: google},
        password_hasher=CHEAP,
    )
    services.vault.initialize()
    client = TestClient(create_app(config, services))
    sign_in(client, *browser_admin(services))

    class Found:
        async def discover(self, caller: Any, email: str) -> Discovery:
            gmail = Candidate(
                provider=ProviderType.GMAIL,
                name="Gmail",
                credential="oauth",
                oauth_provider="gmail",
                source="preset",
                confirmed=True,
            )
            return Discovery(email=email, domain="gmail.com", candidates=[gmail])

    client.app.state.services = replace(  # type: ignore[attr-defined]
        client.app.state.services, discovery=Found()
    )
    page = post(client, "/ui/accounts/discover", {"email": "me@gmail.com"}).text
    assert "Sign in with Google" in page and "Google asks you" in page
    assert "/ui/oauth/gmail/device" not in page and "with a code" not in page
    answer = post(
        client,
        "/ui/oauth/gmail/start",
        {"login_hint": "me@gmail.com"},
        follow_redirects=False,
    )
    query = parse_qs(urlsplit(answer.headers["location"]).query)
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["redirect_uri"] == ["http://testserver/ui/oauth/gmail/callback"]
