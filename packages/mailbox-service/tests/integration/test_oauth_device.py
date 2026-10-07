"""The sign-in with a code (RFC 8628), the project's own app as the default,
and the kinds of account a deployment offers. The provider is
``httpx.MockTransport``: it hands out the code at the device endpoint and
the tokens at the token endpoint, in the order of its replies."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from benethos_mailbox_service.assembly import (
    build_oauth,
    build_services,
    offered_providers,
)
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import (
    App,
    DeviceCode,
    Endpoints,
    OAuthClient,
    Tokens,
    Waiting,
)
from benethos_mailbox_service.data.providers import project_client_id
from benethos_mailbox_service.data.providers.microsoft import CLIENT_ID
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_service.domain.accounts.adapters import REFRESH_TOKEN
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ForbiddenError,
    NotSupportedError,
    ProviderError,
)

from ..conftest import ADMIN
from .test_oauth import (
    Clock,
    TokenEndpoint,
    granted,
    id_token,
    oauth_client,
    services_with,
)

pytestmark = pytest.mark.usefixtures("master_key")

MS = ProviderType.MICROSOFT
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


# --- the protocol ---------------------------------------------------------------------


async def test_a_code_is_handed_out() -> None:
    endpoint = TokenEndpoint(code())
    found = await oauth_client(endpoint).device_code()
    assert found == DeviceCode(
        device_code=SecretStr("dc-secret"),
        user_code="ABCD-EFGH",
        verification_uri="https://microsoft.com/devicelogin",
        expires_in=900,
        interval=5,
    )
    form = endpoint.forms[0]
    assert form["client_id"] == "client-1"
    assert "offline_access" in form["scope"] and "User.Read" in form["scope"]
    # The secret goes to the token endpoint only.
    assert "client_secret" not in form


async def test_a_code_with_what_the_provider_left_out() -> None:
    endpoint = TokenEndpoint(
        code(
            verification_uri=None,
            verification_url="https://example.org/device",
            expires_in="abc",
            interval=0,
        )
    )
    found = await oauth_client(endpoint).device_code()
    assert found.verification_uri == "https://example.org/device"
    assert (found.expires_in, found.interval) == (900, 5)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (code(user_code=None), "without a code"),
        (code(verification_uri=None), "without a code"),
        (code(verification_uri="http://example.org/device"), "without HTTPS"),
        ((401, {"error": "invalid_client"}), "must allow public client flows"),
        ((400, {"error": "invalid_scope"}), "refused the token request"),
        ((502, {}), "refused the token request"),
    ],
)
async def test_codes_that_cannot_be_used(answer: Any, message: str) -> None:
    with pytest.raises(ProviderError, match=message):
        await oauth_client(TokenEndpoint(answer)).device_code()


async def test_a_provider_without_codes() -> None:
    endpoints = Endpoints("other", "https://o.example/a", "https://o.example/t", ())
    client = OAuthClient(App(endpoints, "c"), http=None)  # type: ignore[arg-type]
    with pytest.raises(NotSupportedError, match="no sign-in with a code"):
        await client.device_code()


async def test_polling_for_the_tokens() -> None:
    endpoint = TokenEndpoint(PENDING, (400, {"error": "slow_down"}), signed_in())
    client = oauth_client(endpoint)
    device_code = SecretStr("dc-secret")
    assert await client.poll_device(device_code) == Waiting(slow_down=False)
    assert await client.poll_device(device_code) == Waiting(slow_down=True)
    tokens = await client.poll_device(device_code)
    assert isinstance(tokens, Tokens) and tokens.identity is not None
    assert tokens.identity.email == "me@example.org"
    form = endpoint.forms[0]
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
    assert form["device_code"] == "dc-secret"
    # The code carries its scopes.
    assert "scope" not in form


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("authorization_declined", "was declined"),
        ("expired_token", "has expired"),
        ("bad_verification_code", "has expired"),
    ],
)
async def test_a_poll_that_ends_the_sign_in(error: str, message: str) -> None:
    endpoint = TokenEndpoint((400, {"error": error}))
    with pytest.raises(BadRequestError, match=message):
        await oauth_client(endpoint).poll_device(SecretStr("dc-secret"))


# --- connecting with a code -----------------------------------------------------------


async def test_connect_an_account_with_a_code() -> None:
    clock = Clock()
    endpoint = TokenEndpoint(code(), PENDING, signed_in())
    services = services_with(endpoint, clock)
    oauth = services.oauth
    started = await oauth.start_device(ADMIN, MS)
    assert (started.user_code, started.interval) == ("ABCD-EFGH", 5)
    assert started.expires_at == clock.now + timedelta(seconds=900)
    assert oauth.device(ADMIN, MS, started.id) == started
    # Before the interval has passed, the provider is not asked.
    assert await oauth.poll_device(ADMIN, MS, started.id) is None
    assert len(endpoint.forms) == 1
    clock.now += timedelta(seconds=5)
    assert await oauth.poll_device(ADMIN, MS, started.id) is None
    assert len(endpoint.forms) == 2
    clock.now += timedelta(seconds=5)
    account = await oauth.poll_device(ADMIN, MS, started.id)
    assert account is not None and account.email == "me@example.org"
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-1"
    # A later poll answers with the same account, without asking.
    assert await oauth.poll_device(ADMIN, MS, started.id) == account
    assert len(endpoint.forms) == 3


async def test_a_provider_that_asks_to_slow_down() -> None:
    clock = Clock()
    endpoint = TokenEndpoint(code(), (400, {"error": "slow_down"}), signed_in())
    services = services_with(endpoint, clock)
    started = await services.oauth.start_device(ADMIN, MS)
    clock.now += timedelta(seconds=5)
    assert await services.oauth.poll_device(ADMIN, MS, started.id) is None
    clock.now += timedelta(seconds=5)
    assert await services.oauth.poll_device(ADMIN, MS, started.id) is None
    assert len(endpoint.forms) == 2, "asked after ten seconds, not five"
    clock.now += timedelta(seconds=5)
    assert await services.oauth.poll_device(ADMIN, MS, started.id) is not None


async def test_a_code_sign_in_belongs_to_who_started_it() -> None:
    clock = Clock()
    services = services_with(TokenEndpoint(code(), signed_in()), clock)
    started = await services.oauth.start_device(ADMIN, MS)
    clock.now += timedelta(seconds=5)
    other = Access.admin("usr_other", "other admin")
    for ask in (
        services.oauth.poll_device(other, MS, started.id),
        services.oauth.poll_device(ADMIN, ProviderType.GMAIL, started.id),
        services.oauth.poll_device(ADMIN, MS, "made-up"),
    ):
        with pytest.raises(BadRequestError, match="unknown or expired"):
            await ask
    with pytest.raises(BadRequestError, match="unknown or expired"):
        services.oauth.device(other, MS, started.id)
    assert await services.oauth.poll_device(ADMIN, MS, started.id) is not None


async def test_a_code_expires() -> None:
    clock = Clock()
    services = services_with(TokenEndpoint(code(expires_in=60)), clock)
    started = await services.oauth.start_device(ADMIN, MS)
    clock.now += timedelta(seconds=61)
    with pytest.raises(BadRequestError, match="has expired"):
        await services.oauth.poll_device(ADMIN, MS, started.id)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.poll_device(ADMIN, MS, started.id)


async def test_a_declined_sign_in_ends() -> None:
    clock = Clock()
    endpoint = TokenEndpoint(code(), (400, {"error": "authorization_declined"}))
    services = services_with(endpoint, clock)
    started = await services.oauth.start_device(ADMIN, MS)
    clock.now += timedelta(seconds=5)
    with pytest.raises(BadRequestError, match="declined"):
        await services.oauth.poll_device(ADMIN, MS, started.id)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        await services.oauth.poll_device(ADMIN, MS, started.id)
    assert services.adapters.ids() == []


async def test_sign_in_again_with_a_code() -> None:
    clock = Clock()
    endpoint = TokenEndpoint(
        code(),
        signed_in(),
        code(),
        signed_in("other@example.org"),
        code(),
        granted("at-3", "rt-3", id_token=id_token(email="me@example.org")),
    )
    services = services_with(endpoint, clock)
    oauth = services.oauth

    async def connect(account_id: str | None = None) -> Any:
        started = await oauth.start_device(ADMIN, MS, account_id=account_id)
        clock.now += timedelta(seconds=5)
        return await oauth.poll_device(ADMIN, MS, started.id)

    account = await connect()
    with pytest.raises(BadRequestError, match="sign in with that address"):
        await connect(account.id)
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-1"
    await connect(account.id)
    assert services.vault.read(account.id, REFRESH_TOKEN).get_secret_value() == "rt-3"


async def test_a_code_needs_the_right() -> None:
    services = services_with(TokenEndpoint(code()))
    reader = Access("usr_r", "reader", [Grant(accounts=["*"], allow=["mail.read"])])
    with pytest.raises(ForbiddenError):
        await services.oauth.start_device(reader, MS)


async def test_older_code_sign_ins_are_dropped() -> None:
    clock = Clock()
    services = services_with(TokenEndpoint(*[code()] * 6), clock)
    first = await services.oauth.start_device(ADMIN, MS)
    for _ in range(5):
        clock.now += timedelta(seconds=1)
        await services.oauth.start_device(ADMIN, MS)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        services.oauth.device(ADMIN, MS, first.id)


# --- the kinds of account a deployment offers -----------------------------------------


async def test_kinds_not_offered_cannot_be_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    endpoint = TokenEndpoint(code(), signed_in(), code(), signed_in())
    services = services_with(endpoint, clock)
    started = await services.oauth.start_device(ADMIN, MS)
    clock.now += timedelta(seconds=5)
    account = await services.oauth.poll_device(ADMIN, MS, started.id)
    assert account is not None
    monkeypatch.setattr(services.accounts, "_offered", frozenset({ProviderType.IMAP}))
    assert services.oauth.providers() == []
    with pytest.raises(NotSupportedError, match="cannot be connected"):
        await services.accounts.create(ADMIN, ProviderType.MEMORY, "a@example.org")
    with pytest.raises(NotSupportedError, match="cannot be connected"):
        await services.oauth.start_device(ADMIN, MS)
    # An account connected before keeps working and signs in again.
    again = await services.oauth.start_device(ADMIN, MS, account_id=account.id)
    clock.now += timedelta(seconds=5)
    assert await services.oauth.poll_device(ADMIN, MS, again.id) is not None


def test_the_kinds_a_deployment_offers() -> None:
    assert offered_providers(Settings(storage="memory")) is None
    assert offered_providers(Settings(storage="memory", providers=[])) is None
    assert offered_providers(
        Settings(storage="memory", providers=["IMAP", " jmap"])
    ) == {ProviderType.IMAP, ProviderType.JMAP}
    with pytest.raises(BadRequestError, match="'carrier pigeon', not a kind"):
        offered_providers(Settings(storage="memory", providers=["carrier pigeon"]))


def test_a_kind_not_known_stops_the_service() -> None:
    with pytest.raises(BadRequestError, match="not a kind of account"):
        build_services(Settings(storage="memory", providers=["imap", "fax"]))


# --- the project's app ----------------------------------------------------------------


def test_without_an_app_of_its_own_the_project_app() -> None:
    client = build_oauth(Settings(storage="memory"))[MS]
    assert client.app.client_id == CLIENT_ID == project_client_id(MS)
    assert client.app.client_secret is None and client.app.loopback_only
    assert client.app.endpoints.device_url is not None
    assert project_client_id(ProviderType.IMAP) is None


def test_an_app_of_its_own() -> None:
    settings = Settings(
        storage="memory",
        oauth_microsoft_client_id="own-app",
        oauth_microsoft_client_secret=SecretStr("own-secret"),
    )
    client = build_oauth(settings)[MS]
    assert client.app.client_id == "own-app"
    assert client.app.client_secret == SecretStr("own-secret")
    assert not client.app.loopback_only
    # One without a secret is a public client too.
    settings = Settings(storage="memory", oauth_microsoft_client_id="own-public")
    assert build_oauth(settings)[MS].app.client_secret is None


def test_an_empty_secret_is_none() -> None:
    settings = Settings(storage="memory", oauth_microsoft_client_secret=SecretStr(""))
    assert settings.oauth_microsoft_secret() is None
    assert build_oauth(settings)[MS].app.client_id == CLIENT_ID


@pytest.mark.parametrize(
    "secret",
    [
        {"oauth_microsoft_client_secret": SecretStr("lost")},
        {"oauth_microsoft_client_secret_file": "secret.txt"},
    ],
)
def test_a_secret_without_its_app_is_refused(secret: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="needs the client id of its app"):
        Settings(storage="memory", **secret)


async def test_expired_sign_ins_are_dropped_when_another_starts() -> None:
    clock = Clock()
    services = services_with(TokenEndpoint(code(expires_in=3600), code()), clock)
    first = await services.oauth.start_device(ADMIN, MS)
    services.oauth.start(ADMIN, MS, "http://localhost/ui/oauth/microsoft/callback")
    # No longer than half an hour, whatever the provider says.
    clock.now += timedelta(minutes=31)
    await services.oauth.start_device(ADMIN, MS)
    with pytest.raises(BadRequestError, match="unknown or expired"):
        services.oauth.device(ADMIN, MS, first.id)


async def test_a_code_for_an_account_of_another_kind() -> None:
    services = services_with(TokenEndpoint())
    account = await services.accounts.create(
        ADMIN, ProviderType.MEMORY, "a@example.org"
    )
    with pytest.raises(BadRequestError, match="is a memory account"):
        await services.oauth.start_device(ADMIN, MS, account_id=account.id)


def test_the_project_app_comes_back_to_localhost_only() -> None:
    import httpx

    from benethos_mailbox_service.assembly import build_services

    app = App(microsoft_endpoints(), CLIENT_ID, loopback_only=True)
    client = OAuthClient(app, ApiClient(transport=httpx.MockTransport(TokenEndpoint())))
    services = build_services(Settings(storage="memory"), oauth_clients={MS: client})
    oauth = services.oauth
    for here in (
        "http://localhost:8080/ui/oauth/microsoft/callback",
        "http://127.0.0.1:8080/ui/oauth/microsoft/callback",
        "http://[::1]:8080/ui/oauth/microsoft/callback",
    ):
        assert oauth.in_browser(MS, here)
        assert oauth.start(ADMIN, MS, here).startswith("https://login.")
    away = "https://mail.example.org/ui/oauth/microsoft/callback"
    assert not oauth.in_browser(MS, away)
    with pytest.raises(BadRequestError, match="sign in with a code"):
        oauth.start(ADMIN, MS, away)
    assert not oauth.in_browser(ProviderType.GMAIL, away)
