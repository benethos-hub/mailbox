"""Autodiscovery with fake sources: trust, ranking, failures and the cache.
The fakes here serve the other discovery tests too."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest

from benethos_mailbox_service.data.discovery import (
    Finding,
    Query,
)
from benethos_mailbox_service.data.models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    Hint,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.domain.discovery import service as discovery_module
from benethos_mailbox_service.domain.discovery.service import DiscoveryService
from benethos_mailbox_service.errors import (
    ProviderError,
    ProviderUnavailableError,
)

from ...conftest import admin_access

PRESET = DiscoverySourceName.PRESET
AUTOCONFIG = DiscoverySourceName.AUTOCONFIG
ISPDB = DiscoverySourceName.ISPDB
MX = DiscoverySourceName.MX

ADMIN = admin_access("usr_admin", "admin")


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
        self.connected_to: list[str] = []

    async def check(self, host: str, port: int) -> str | None:
        if host in self.private:
            raise ProviderError(f"refused to connect to {host}")
        return None if host in self.missing else "93.184.215.14"

    async def probe(
        self,
        protocol: ServerProtocol,
        host: str,
        port: int,
        security: Security,
        address: str,
    ) -> frozenset[str]:
        self.probed.append(host)
        self.connected_to.append(address)
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
        await s.discover(admin_access(f"usr_{user}", user), "x@firma.example")
    assert set(s._calls) == {"usr_b", "usr_c"}
    clock.now += 60
    await s.discover(admin_access("usr_d", "d"), "x@firma.example")
    assert set(s._calls) == {"usr_d"}


async def test_a_failed_lookup_is_not_cached() -> None:
    source = FakeSource(ISPDB, ProviderUnavailableError("down"))
    s = service(source)
    await s.discover(ADMIN, "a@firma.example")
    await s.discover(ADMIN, "a@firma.example")
    assert len(source.queries) == 2
