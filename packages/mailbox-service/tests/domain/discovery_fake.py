"""Discovery from outside: sources and a network that answer as a test
says, the service on them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anyio

from benethos_mailbox_service.data.discovery import (
    Finding,
    Query,
)
from benethos_mailbox_service.data.models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.domain.discovery.service import DiscoveryService
from benethos_mailbox_service.errors import (
    ProviderError,
    ProviderUnavailableError,
)

from ..clocks import Seconds
from ..conftest import admin_access

ADMIN = admin_access("usr_admin", "admin")


AUTOCONFIG = DiscoverySourceName.AUTOCONFIG
ISPDB = DiscoverySourceName.ISPDB
MX = DiscoverySourceName.MX

PRESET = DiscoverySourceName.PRESET


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


def found(*candidates: Candidate, by: str | None = None, **kw: Any) -> Finding:
    return Finding(candidates=candidates, answered_by=by, **kw)


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


def service(
    *sources: FakeSource,
    network: Network | None = None,
    clock: Seconds | None = None,
    **kwargs: Any,
) -> DiscoveryService:
    network = network or Network()
    return DiscoveryService(
        sources,
        probe=network.probe,
        check_host=network.check,
        trusted_hosts=kwargs.pop("trusted_hosts", {"imap.bigmail.example"}),
        clock=clock or Seconds(),
        **kwargs,
    )
