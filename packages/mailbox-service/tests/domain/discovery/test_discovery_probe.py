"""Autodiscovery: probing the servers found, POP3 and JMAP beside IMAP."""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from benethos_mailbox_service.data.models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.domain.discovery import service as discovery_module

from .test_discovery import (
    ADMIN,
    AUTOCONFIG,
    ISPDB,
    MX,
    PRESET,
    FakeSource,
    Network,
    found,
    imap,
    service,
)

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


async def test_the_probe_connects_to_the_address_just_checked() -> None:
    network = Network()
    await service(
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))), network=network
    ).discover(ADMIN, "me@firma.example")
    assert network.connected_to == ["93.184.215.14"]


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


def pop3(host: str, source: DiscoverySourceName) -> Candidate:
    server = MailServer(
        protocol=ServerProtocol.POP3, host=host, port=995, security=Security.TLS
    )
    return Candidate(
        provider=ProviderType.POP3,
        name=host,
        credential=CredentialKind.PASSWORD,
        servers=[server],
        source=source,
    )


async def test_pop3_is_offered_where_no_imap_is() -> None:
    network = Network()
    s = service(
        FakeSource(ISPDB, found(pop3("pop.firma.example", ISPDB))), network=network
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.provider is ProviderType.POP3
    assert candidate.servers[0].reachable is True
    assert network.probed == ["pop.firma.example"]
    assert candidate.settings == {
        "host": "pop.firma.example",
        "port": 995,
        "security": "tls",
        "username": "me@firma.example",
    }
    assert discovery_module.connectable([candidate]) == [candidate]


async def test_pop3_is_left_out_beside_imap() -> None:
    s = service(
        FakeSource(ISPDB, found(pop3("pop.firma.example", ISPDB))),
        FakeSource(PRESET, found(imap("imap.firma.example", PRESET))),
    )
    candidates = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert [c.provider for c in candidates] == [ProviderType.IMAP]


async def test_kinds_not_offered_are_left_out() -> None:
    sources = (
        FakeSource(ISPDB, found(pop3("pop.firma.example", ISPDB))),
        FakeSource(PRESET, found(imap("imap.firma.example", PRESET))),
    )
    s = service(*sources, offered={ProviderType.POP3, ProviderType.JMAP})
    candidates = (await s.discover(ADMIN, "me@firma.example")).candidates
    # Without IMAP, POP3 is what there is.
    assert [c.provider for c in candidates] == [ProviderType.POP3]
    s = service(*sources, offered={ProviderType.JMAP})
    assert (await s.discover(ADMIN, "me@firma.example")).candidates == []


def test_connectable_prefers_imap() -> None:
    both = [pop3("pop.x.example", ISPDB), imap("imap.x.example", ISPDB)]
    assert [c.provider for c in discovery_module.connectable(both)] == [
        ProviderType.IMAP
    ]


def jmap(
    host: str,
    source: DiscoverySourceName,
    credential: CredentialKind = CredentialKind.PASSWORD,
) -> Candidate:
    server = MailServer(
        protocol=ServerProtocol.JMAP,
        host=host,
        port=443,
        security=Security.TLS,
        path="/jmap/session",
        reachable=True,
    )
    return Candidate(
        provider=ProviderType.JMAP,
        name=host,
        credential=credential,
        servers=[server],
        source=source,
    )


async def test_jmap_comes_before_imap_and_is_not_probed() -> None:
    network = Network()
    s = service(
        FakeSource(PRESET, found(imap("imap.firma.example", PRESET))),
        FakeSource(
            DiscoverySourceName.JMAP,
            found(
                jmap("jmap.firma.example", DiscoverySourceName.JMAP), by="firma.example"
            ),
        ),
        network=network,
    )
    candidates = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert [c.provider for c in candidates] == [ProviderType.JMAP, ProviderType.IMAP]
    assert candidates[0].confirmed
    assert candidates[0].settings == {
        "host": "jmap.firma.example",
        "port": 443,
        "path": "/jmap/session",
        "username": "me@firma.example",
    }
    assert network.probed == ["imap.firma.example"]


async def test_jmap_from_elsewhere_is_not_confirmed() -> None:
    s = service(
        FakeSource(
            DiscoverySourceName.JMAP,
            found(
                jmap("mail.hoster.example", DiscoverySourceName.JMAP),
                by="mail.hoster.example",
            ),
        )
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert not candidate.confirmed


async def test_pop3_is_left_out_beside_jmap() -> None:
    s = service(
        FakeSource(ISPDB, found(pop3("pop.firma.example", ISPDB))),
        FakeSource(
            DiscoverySourceName.JMAP,
            found(jmap("jmap.firma.example", DiscoverySourceName.JMAP)),
        ),
    )
    candidates = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert [c.provider for c in candidates] == [ProviderType.JMAP]


def test_connectable_offers_jmap_then_imap() -> None:
    token = jmap("api.x.example", PRESET, CredentialKind.API_TOKEN)
    oauth = jmap("o.x.example", PRESET, CredentialKind.OAUTH)
    found = discovery_module.connectable(
        [imap("imap.x.example", ISPDB), oauth, token, pop3("pop.x.example", ISPDB)]
    )
    assert [c.servers[0].host for c in found] == ["api.x.example", "imap.x.example"]
    assert discovery_module.connectable([pop3("pop.x.example", ISPDB), token]) == [
        token
    ]


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
