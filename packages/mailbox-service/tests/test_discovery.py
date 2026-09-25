"""Autodiscovery in the domain and through the API, with fake sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.discovery import (
    Finding,
    Query,
    SafeFetcher,
    default_sources,
)
from benethos_mailbox_service.data.models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    Grant,
    Hint,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.domain import discovery as discovery_module
from benethos_mailbox_service.domain.access import Access
from benethos_mailbox_service.domain.discovery import DiscoveryService
from benethos_mailbox_service.errors import (
    BadRequestError,
    ForbiddenError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
)
from benethos_mailbox_service.main import build_services, create_app

from .conftest import bearer_for

PRESET = DiscoverySourceName.PRESET
AUTOCONFIG = DiscoverySourceName.AUTOCONFIG
ISPDB = DiscoverySourceName.ISPDB
MX = DiscoverySourceName.MX

ADMIN = Access.admin("usr_admin", "admin")


def imap(
    host: str,
    source: DiscoverySourceName,
    *,
    port: int = 993,
    credential: CredentialKind = CredentialKind.PASSWORD,
    username: str | None = "%EMAILADDRESS%",
    smtp: str | None = None,
) -> Candidate:
    servers = [
        MailServer(
            protocol=ServerProtocol.IMAP,
            host=host,
            port=port,
            security=Security.TLS,
            username=username,
        )
    ]
    if smtp:
        servers.append(
            MailServer(
                protocol=ServerProtocol.SMTP,
                host=smtp,
                port=465,
                security=Security.TLS,
                username=username,
            )
        )
    return Candidate(
        provider=ProviderType.IMAP,
        name=host,
        credential=credential,
        servers=servers,
        source=source,
    )


@dataclass
class FakeSource:
    name: DiscoverySourceName
    answer: Finding | Exception = field(default_factory=Finding)
    delay: float = 0.0
    queries: list[Query] = field(default_factory=list)

    async def lookup(self, query: Query) -> Finding:
        self.queries.append(query)
        if self.delay:
            await anyio.sleep(self.delay)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Network:
    """Answers the host check and the probe."""

    def __init__(self) -> None:
        self.private: set[str] = set()
        self.missing: set[str] = set()
        self.down: set[str] = set()
        self.capabilities: dict[str, frozenset[str]] = {}
        self.probed: list[str] = []

    async def check(self, host: str, port: int) -> str | None:
        if host in self.private:
            raise ProviderError(f"refused to connect to {host}")
        return None if host in self.missing else "93.184.215.14"

    async def probe(
        self, protocol: ServerProtocol, host: str, port: int, security: Security
    ) -> frozenset[str]:
        self.probed.append(host)
        if host in self.down:
            raise ProviderUnavailableError("not reachable")
        return self.capabilities.get(host, frozenset({"IMAP4REV1", "IDLE"}))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def service(
    *sources: FakeSource,
    network: Network | None = None,
    clock: Clock | None = None,
    **kwargs: Any,
) -> DiscoveryService:
    network = network or Network()
    return DiscoveryService(
        sources,
        probe=network.probe,
        check_host=network.check,
        trusted_hosts=kwargs.pop("trusted_hosts", {"imap.bigmail.example"}),
        clock=clock or Clock(),
        **kwargs,
    )


def found(*candidates: Candidate, by: str | None = None, **kw: Any) -> Finding:
    return Finding(candidates=candidates, answered_by=by, **kw)


# --- trust and ranking ----------------------------------------------------------


async def test_preset_is_confirmed_and_ready_to_use() -> None:
    network = Network()
    s = service(
        FakeSource(PRESET, found(imap("imap.bigmail.example", PRESET, smtp="smtp.x"))),
        network=network,
    )
    result = await s.discover(ADMIN, " Me@Firma.example ")
    assert result.email == "Me@Firma.example"
    assert result.domain == "firma.example"
    [candidate] = result.candidates
    assert candidate.confirmed
    imap_server, smtp_server = candidate.servers
    assert imap_server.username == "Me@Firma.example"
    assert smtp_server.username == "Me@Firma.example"
    assert imap_server.reachable is True
    assert imap_server.capabilities == ["IDLE", "IMAP4REV1"]
    assert smtp_server.reachable is None
    assert candidate.settings == {
        "host": "imap.bigmail.example",
        "port": 993,
        "security": "tls",
        "username": "Me@Firma.example",
        "auth": "password",
        # Sending: the SMTP server, with the same login.
        "smtp_host": "smtp.x",
        "smtp_port": 465,
        "smtp_security": "tls",
    }
    assert [(r.source, r.outcome) for r in result.sources] == [(PRESET, "found")]
    assert network.probed == ["imap.bigmail.example"]


@pytest.mark.parametrize(
    ("source", "host", "answered_by", "confirmed"),
    [
        # Autoconfig from the address's own domain: confirmed, wherever it points.
        (AUTOCONFIG, "mail.hoster.example", "autoconfig.firma.example", True),
        # Redirected to another domain: judged by the servers.
        (AUTOCONFIG, "mail.hoster.example", "config.hoster.example", False),
        (AUTOCONFIG, "imap.firma.example", "config.hoster.example", True),
        # ISPDB: servers in the address's domain or known from a preset.
        (ISPDB, "imap.firma.example", "autoconfig.thunderbird.net", True),
        (ISPDB, "imap.bigmail.example", "autoconfig.thunderbird.net", True),
        (ISPDB, "mail.hoster.example", "autoconfig.thunderbird.net", False),
        # MX: never, not even for a preset host.
        (MX, "imap.bigmail.example", "mx.bigmail.example", False),
    ],
)
async def test_trust_follows_the_source(
    source: DiscoverySourceName, host: str, answered_by: str, confirmed: bool
) -> None:
    s = service(FakeSource(source, found(imap(host, source), by=answered_by)))
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.confirmed is confirmed


async def test_ranking_confirmed_then_reachable_then_source_order() -> None:
    network = Network()
    network.down.add("imap.down.firma.example")
    s = service(
        FakeSource(
            AUTOCONFIG,
            found(imap("imap.down.firma.example", AUTOCONFIG), by="firma.example"),
        ),
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))),
        FakeSource(MX, found(imap("imap.hoster.example", MX))),
        network=network,
    )
    result = await s.discover(ADMIN, "me@firma.example")
    assert [c.servers[0].host for c in result.candidates] == [
        "imap.firma.example",
        "imap.down.firma.example",
        "imap.hoster.example",
    ]
    assert result.candidates[1].servers[0].reachable is False


async def test_duplicates_are_merged_into_the_better_one() -> None:
    mx_candidate = imap("imap.firma.example", MX).model_copy(
        update={"hints": [Hint(text="from mx")]}
    )
    ispdb = imap("imap.firma.example", ISPDB, credential=CredentialKind.APP_PASSWORD)
    s = service(FakeSource(ISPDB, found(ispdb)), FakeSource(MX, found(mx_candidate)))
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.source is ISPDB
    assert candidate.credential is CredentialKind.APP_PASSWORD
    assert candidate.confirmed
    assert candidate.hints == [Hint(text="from mx")]


async def test_merge_keeps_a_confirmation_from_a_later_source() -> None:
    s = service(
        FakeSource(MX, found(imap("imap.firma.example", MX))),
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))),
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.source is MX
    assert candidate.confirmed


# --- probing ----------------------------------------------------------------------


async def test_a_server_on_a_private_address_is_dropped() -> None:
    network = Network()
    network.private.add("imap.evil.example")
    s = service(
        FakeSource(
            AUTOCONFIG, found(imap("imap.evil.example", AUTOCONFIG), by="firma.example")
        ),
        FakeSource(MX, found(imap("imap.hoster.example", MX))),
        network=network,
    )
    result = await s.discover(ADMIN, "me@firma.example")
    assert [c.servers[0].host for c in result.candidates] == ["imap.hoster.example"]
    assert "imap.evil.example" not in network.probed


async def test_a_host_that_does_not_resolve_is_unreachable() -> None:
    network = Network()
    network.missing.add("imap.firma.example")
    s = service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))), network=network
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.servers[0].reachable is False
    assert network.probed == []


async def test_oauth_only_server_asks_for_oauth() -> None:
    network = Network()
    network.capabilities["imap.firma.example"] = frozenset(
        {"IMAP4REV1", "LOGINDISABLED", "AUTH=XOAUTH2"}
    )
    s = service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))), network=network
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.credential is CredentialKind.OAUTH
    assert candidate.settings["auth"] == "xoauth2"


async def test_probes_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "MAX_PROBES", 2)
    network = Network()
    candidates = [imap(f"imap{i}.firma.example", ISPDB) for i in range(4)]
    s = service(FakeSource(ISPDB, found(*candidates)), network=network)
    result = await s.discover(ADMIN, "me@firma.example")
    assert len(result.candidates) == 4
    assert len(network.probed) == 2
    assert [c.servers[0].reachable for c in result.candidates] == [
        True,
        True,
        None,
        None,
    ]


async def test_a_slow_probe_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "PROBE_TIMEOUT", 0.01)
    network = Network()

    async def slow(*args: Any) -> frozenset[str]:
        await anyio.sleep(1)
        return frozenset()

    network.probe = slow  # type: ignore[method-assign]
    s = service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))), network=network
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.servers[0].reachable is False


async def test_candidates_without_imap_are_kept_without_settings() -> None:
    oauth = Candidate(
        provider=ProviderType.GMAIL,
        credential=CredentialKind.OAUTH,
        oauth_provider="google",
        source=PRESET,
    )
    s = service(FakeSource(PRESET, found(oauth)))
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.settings == {}
    assert candidate.confirmed


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("%EMAILLOCALPART%", "me"),
        ("%EMAILLOCALPART%@%EMAILDOMAIN%", "me@firma.example"),
        (None, "me@firma.example"),
    ],
)
async def test_username_templates(template: str | None, expected: str) -> None:
    s = service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB, username=template)))
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.servers[0].username == expected
    assert candidate.settings["username"] == expected


# --- sources: failures, hints, cache ---------------------------------------------


async def test_failures_and_timeouts_are_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_module, "SOURCE_TIMEOUT", 0.01)
    s = service(
        FakeSource(PRESET),
        FakeSource(
            AUTOCONFIG,
            ProviderUnavailableError("autoconfig.firma.example is not reachable"),
        ),
        FakeSource(ISPDB, delay=1),
        FakeSource(MX, found(imap("imap.hoster.example", MX))),
    )
    result = await s.discover(ADMIN, "me@firma.example")
    assert [(r.source, r.outcome, r.message) for r in result.sources] == [
        (PRESET, "nothing", None),
        (AUTOCONFIG, "failed", "autoconfig.firma.example is not reachable"),
        (ISPDB, "failed", "no answer in time"),
        (MX, "found", None),
    ]
    assert len(result.candidates) == 1


async def test_hints_about_the_address() -> None:
    hint = Hint(text="Tuta offers no access for other mail programs.")
    s = service(
        FakeSource(PRESET, Finding(hints=(hint,))),
        FakeSource(MX, Finding(hints=(hint,))),
    )
    result = await s.discover(ADMIN, "me@tuta.example")
    assert result.candidates == []
    assert result.hints == [hint]
    assert result.sources[0].outcome == "found"


async def test_findings_are_cached_per_domain_for_a_day() -> None:
    clock = Clock()
    source = FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB)))
    s = service(source, clock=clock, per_user=100)
    first = await s.discover(ADMIN, "a@firma.example")
    second = await s.discover(ADMIN, "b@firma.example")
    assert len(source.queries) == 1
    assert first.candidates[0].settings["username"] == "a@firma.example"
    assert second.candidates[0].settings["username"] == "b@firma.example"
    clock.now += 24 * 3600
    await s.discover(ADMIN, "a@firma.example")
    assert len(source.queries) == 2


async def test_the_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "MAX_CACHED", 2)
    clock = Clock()
    source = FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB)))
    s = service(source, clock=clock, per_user=100)
    for domain in ("one", "two", "three"):
        clock.now += 1
        await s.discover(ADMIN, f"a@{domain}.example")
    assert len(s._cache) == 2
    assert "one.example" not in s._cache
    # A finding that expired goes before a fresh one.
    clock.now += 24 * 3600 - 2
    await s.discover(ADMIN, "a@four.example")
    assert set(s._cache) == {"three.example", "four.example"}


async def test_the_callers_counted_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_module, "MAX_CALLERS", 2)
    clock = Clock()
    s = service(FakeSource(ISPDB), clock=clock, per_user=100)
    for user in ("a", "b", "c"):
        clock.now += 1
        await s.discover(Access.admin(f"usr_{user}", user), "x@firma.example")
    assert set(s._calls) == {"usr_b", "usr_c"}
    clock.now += 60
    await s.discover(Access.admin("usr_d", "d"), "x@firma.example")
    assert set(s._calls) == {"usr_d"}


async def test_a_failed_lookup_is_not_cached() -> None:
    source = FakeSource(ISPDB, ProviderUnavailableError("down"))
    s = service(source)
    await s.discover(ADMIN, "a@firma.example")
    await s.discover(ADMIN, "a@firma.example")
    assert len(source.queries) == 2


# --- input, limits, rights --------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "message"),
    [
        ("nope", "not a valid email address"),
        ("@firma.example", "not a valid email address"),
        ("me@", "not a valid email address"),
        ("m e@firma.example", "not a valid email address"),
        ("me@" + "a" * 64 + ".example", "not a valid email domain"),
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


async def test_discovery_needs_accounts_manage_on_every_account() -> None:
    s = service(FakeSource(ISPDB))
    one_account = Access(
        "usr_1", "one", [Grant(accounts=["acc_a"], allow=["accounts.manage"])]
    )
    with pytest.raises(ForbiddenError, match="discover_account"):
        await s.discover(one_account, "a@firma.example")
    everywhere = Access(
        "usr_2", "all", [Grant(accounts=["*"], allow=["discover_account"])]
    )
    await s.discover(everywhere, "a@firma.example")


# --- assembly and API ---------------------------------------------------------------


def test_default_sources_in_order_and_ispdb_switch() -> None:
    fetcher = SafeFetcher()
    assert [s.name for s in default_sources(fetcher, ispdb=True)] == [
        PRESET,
        AUTOCONFIG,
        ISPDB,
        MX,
    ]
    assert [s.name for s in default_sources(fetcher, ispdb=False)] == [
        PRESET,
        AUTOCONFIG,
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


@pytest.fixture
def api() -> tuple[Any, TestClient]:
    settings = Settings(storage="memory", api_key=SecretStr("k"))
    discovery = service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))), per_user=2
    )
    services = build_services(settings, discovery=discovery)
    client = TestClient(
        create_app(settings, services), headers={"Authorization": "Bearer k"}
    )
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


def test_openapi_names_the_right(api: tuple[Any, TestClient]) -> None:
    _, client = api
    operation = client.get("/openapi.json").json()["paths"]["/v1/discovery"]["post"]
    assert operation["operationId"] == "discover_account"
    assert operation["x-permission"] == "accounts.manage"
    assert "429" in operation["responses"]
