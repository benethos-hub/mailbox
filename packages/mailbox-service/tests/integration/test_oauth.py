"""OAuth: the flow that connects an account. The token endpoint is
``httpx.MockTransport``. The fakes here serve the other OAuth tests too."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.domain.accounts.adapters import REFRESH_TOKEN
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ForbiddenError,
    NotSupportedError,
    ProviderAuthError,
)

from ..clocks import Clock
from ..conftest import ADMIN, admin_access
from ..oauth_fake import (
    NOW,
    REDIRECT,
    SignedInProvider,
    TokenEndpoint,
    granted,
    id_token,
    services_with,
    state_of,
)

# The vault needs a key to store refresh tokens.
pytestmark = pytest.mark.usefixtures("master_key")

# --- connecting an account ------------------------------------------------------------


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
    clock = Clock(NOW)
    services = services_with(TokenEndpoint(), clock)
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    clock.now += timedelta(minutes=11)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")


async def test_only_the_starter_cancels_a_sign_in() -> None:
    services = services_with(TokenEndpoint(granted(id_token=id_token(email="a@b.c"))))
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    services.oauth.cancel(admin_access("usr_other", "other admin"), state)
    await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    services.oauth.cancel(ADMIN, state)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.finish(ADMIN, ProviderType.MICROSOFT, state, "c")


async def test_a_sign_in_belongs_to_who_started_it() -> None:
    services = services_with(TokenEndpoint(granted(id_token=id_token(email="a@b.c"))))
    state = state_of(services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT))
    other = admin_access("usr_other", "other admin")
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
