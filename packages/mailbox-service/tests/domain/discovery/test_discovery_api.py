"""Autodiscovery: input, limits and rights, the assembly and the API."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.discovery import (
    default_sources,
)
from benethos_mailbox_service.data.models import (
    DiscoverySourceName,
    Grant,
)
from benethos_mailbox_service.data.protocols import SafeFetcher
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ForbiddenError,
    RateLimitedError,
)

from ...conftest import admin_bearer, bearer_for
from .test_discovery import (
    ADMIN,
    AUTOCONFIG,
    ISPDB,
    MX,
    PRESET,
    Clock,
    FakeSource,
    found,
    imap,
    service,
)

# --- input, limits, rights --------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "message"),
    [
        ("nope", "not a valid email address"),
        ("@firma.example", "not a valid email address"),
        ("me@", "not a valid email address"),
        ("m e@firma.example", "not a valid email address"),
        ("me@" + "a" * 64 + ".example", "not a valid email domain"),
        ("me\t@firma.example", "not a valid email address"),
        ("me@firma\x00.example", "not a valid email address"),
        ("me@firma.example:8443", "not a valid email domain"),
        ("me@firma.example/path", "not a valid email domain"),
        ("me@[127.0.0.1]", "not a valid email domain"),
        ("me@xn--zz.example", "not a valid email domain"),
        ("me@-firma.example", "not a valid email domain"),
        ("me@firma_x.example", "not a valid email domain"),
        ("me@x:8443", "not a valid email domain"),
        ("me@co.uk", "public suffix"),
        ("me@de", "public suffix"),
    ],
)
async def test_invalid_addresses(email: str, message: str) -> None:
    source = FakeSource(ISPDB)
    with pytest.raises(BadRequestError, match=message):
        await service(source).discover(ADMIN, email)
    assert source.queries == []


async def test_idn_domain_ascii_for_sources_unicode_in_the_answer() -> None:
    source = FakeSource(ISPDB)
    result = await service(source).discover(ADMIN, "me@Bücher.example")
    assert source.queries[0].domain == "xn--bcher-kva.example"
    assert result.domain == "bücher.example"


async def test_rate_limit_per_user() -> None:
    clock = Clock()
    s = service(FakeSource(ISPDB), clock=clock, per_user=2)
    other = Access.admin("usr_other", "other")
    await s.discover(ADMIN, "a@firma.example")
    clock.now += 10
    await s.discover(ADMIN, "a@firma.example")
    with pytest.raises(RateLimitedError) as caught:
        await s.discover(ADMIN, "a@firma.example")
    assert caught.value.retry_after == 51
    await s.discover(other, "a@firma.example")
    clock.now += 51
    await s.discover(ADMIN, "a@firma.example")


async def test_discovery_needs_accounts_connect() -> None:
    s = service(FakeSource(ISPDB))
    every_account = Access(
        "usr_1", "one", [Grant(accounts=["*"], allow=["accounts.manage"])]
    )
    with pytest.raises(ForbiddenError, match="discover_account"):
        await s.discover(every_account, "a@firma.example")
    connects = Access("usr_2", "all", [], service=["discover_account"])
    await s.discover(connects, "a@firma.example")


# --- assembly and API ---------------------------------------------------------------


def test_default_sources_in_order_and_ispdb_switch() -> None:
    fetcher = SafeFetcher()
    assert [s.name for s in default_sources(fetcher, ispdb=True)] == [
        PRESET,
        AUTOCONFIG,
        DiscoverySourceName.JMAP,
        ISPDB,
        MX,
    ]
    assert [s.name for s in default_sources(fetcher, ispdb=False)] == [
        PRESET,
        AUTOCONFIG,
        DiscoverySourceName.JMAP,
        MX,
    ]


def test_settings_switch_ispdb_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_DISCOVERY_ISPDB", "false")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS", '["mail.intern.example"]'
    )
    settings = Settings()
    assert settings.discovery_ispdb is False
    assert settings.discovery_internal_hosts == ["mail.intern.example"]
    services = build_services(settings)
    assert ISPDB not in services.discovery.sources


def test_the_limit_comes_from_the_settings() -> None:
    settings = Settings(storage="memory", discovery_per_minute=3)
    assert build_services(settings).discovery.per_user == 3


@pytest.fixture
def api() -> tuple[Any, TestClient]:
    settings = Settings(storage="memory")
    discovery = service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))), per_user=2
    )
    services = build_services(settings, discovery=discovery)
    client = TestClient(create_app(settings, services), headers=admin_bearer(services))
    return services, client


def test_post_discovery(api: tuple[Any, TestClient]) -> None:
    _, client = api
    response = client.post("/v1/discovery", json={"email": "me@firma.example"})
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["settings"]["host"] == "imap.firma.example"
    assert body["candidates"][0]["confirmed"] is True
    assert body["sources"] == [{"source": "ispdb", "outcome": "found", "message": None}]


def test_post_discovery_errors(api: tuple[Any, TestClient]) -> None:
    services, client = api
    assert client.post("/v1/discovery", json={"email": "nope"}).status_code == 400
    assert client.post("/v1/discovery", json={}).status_code == 422
    client.post("/v1/discovery", json={"email": "a@firma.example"})
    client.post("/v1/discovery", json={"email": "a@firma.example"})
    limited = client.post("/v1/discovery", json={"email": "a@firma.example"})
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0

    reader = bearer_for(services, Grant(accounts=["*"], allow=["accounts.read"]))
    denied = client.post(
        "/v1/discovery", json={"email": "a@firma.example"}, headers=reader
    )
    assert denied.status_code == 403


@pytest.mark.parametrize(
    "email",
    ["a@x:8443", "me@firma\t.example", "me@xn--zz.example", "me@firma.exa\u2028mple"],
)
def test_a_broken_domain_is_a_bad_request(
    api: tuple[Any, TestClient], email: str
) -> None:
    """A 400 through the API as well, never a 500."""
    _, client = api
    response = client.post("/v1/discovery", json={"email": email})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "bad_request"


def test_openapi_names_the_right(api: tuple[Any, TestClient]) -> None:
    _, client = api
    operation = client.get("/openapi.json").json()["paths"]["/v1/discovery"]["post"]
    assert operation["operationId"] == "discover_account"
    assert operation["x-permission"] == "accounts.connect"
    assert "429" in operation["responses"]
