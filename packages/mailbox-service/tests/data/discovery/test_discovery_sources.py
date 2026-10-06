"""The discovery sources, offline: presets, ISP autoconfig, JMAP, ISPDB, MX."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import dns.exception
import dns.name
import dns.resolver
import httpx
import pytest

from benethos_mailbox_service.data.discovery import Finding, Query
from benethos_mailbox_service.data.discovery.dns import srv_targets
from benethos_mailbox_service.data.discovery.isp import IspAutoconfigSource
from benethos_mailbox_service.data.discovery.ispdb import IspdbSource
from benethos_mailbox_service.data.discovery.jmap import JmapSource
from benethos_mailbox_service.data.discovery.mx import MxLookup, MxSource
from benethos_mailbox_service.data.discovery.presets import PresetSource, bundled
from benethos_mailbox_service.data.discovery.suffix import (
    registrable_domain,
)
from benethos_mailbox_service.data.models import (
    CredentialKind,
    DiscoverySourceName,
    ProviderType,
)
from benethos_mailbox_service.data.protocols.http import SafeFetcher
from benethos_mailbox_service.errors import ProviderError, ProviderUnavailableError

from ...conftest import PUBLIC

QUERY = Query(email="me+x@firma.example", domain="firma.example")


def config(host: str) -> bytes:
    return f"""<clientConfig version="1.1"><emailProvider id="x">
      <displayName>Found</displayName>
      <incomingServer type="imap"><hostname>{host}</hostname><port>993</port>
      <socketType>SSL</socketType><username>%EMAILADDRESS%</username>
      <authentication>password-cleartext</authentication></incomingServer>
      </emailProvider></clientConfig>""".encode()


def fetcher(
    answers: dict[str, httpx.Response | Exception], seen: list[httpx.Request]
) -> SafeFetcher:
    """Answers by 'host/path', every host resolves to a public address."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = answers.get(request.headers["host"] + request.url.path)
        if isinstance(answer, Exception):
            raise answer
        return answer or httpx.Response(404)

    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC]

    return SafeFetcher(resolve=resolve, transport=httpx.MockTransport(handler))


# --- presets --------------------------------------------------------------------


def test_bundled_presets_are_consistent() -> None:
    presets = bundled().all
    assert presets
    ids = [p.id for p in presets]
    assert len(ids) == len(set(ids))
    domains = [d for p in presets for d in p.domains]
    assert len(domains) == len(set(domains)), "a domain in two presets"
    mx = [d for p in presets for d in p.mx_domains]
    assert len(mx) == len(set(mx)), "an MX domain in two presets"
    for domain in domains + mx:
        assert domain == domain.lower()
        assert registrable_domain(domain) == domain, domain
    for preset in presets:
        assert preset.candidates or preset.hints, preset.id
        for candidate in preset.candidates:
            protocols = [s.protocol for s in candidate.servers]
            # The server it reads mail from comes first.
            assert protocols[0].value == candidate.provider.value, preset.id
            for server in candidate.servers:
                if candidate.credential is CredentialKind.API_TOKEN:
                    assert server.username is None and server.path, preset.id
                else:
                    assert server.username == "%EMAILADDRESS%"
    assert "imap.gmail.com" in bundled().server_hosts()
    assert "api.fastmail.com" in bundled().server_hosts()


async def test_preset_source_by_domain() -> None:
    source = PresetSource()
    found = await source.lookup(Query("a@gmail.com", "gmail.com"))
    [candidate] = found.candidates
    assert candidate.name == "Gmail"
    assert candidate.source is DiscoverySourceName.PRESET
    assert candidate.credential is CredentialKind.APP_PASSWORD
    assert candidate.servers[0].host == "imap.gmail.com"
    assert found.answered_by is None
    assert (await source.lookup(QUERY)).candidates == ()


async def test_preset_without_access_gives_only_a_hint() -> None:
    found = await PresetSource().lookup(Query("a@tuta.com", "tuta.com"))
    assert found.candidates == ()
    assert "no access" in found.hints[0].text


# --- ISP autoconfig ---------------------------------------------------------------


async def test_isp_autoconfig_subdomain_first() -> None:
    seen: list[httpx.Request] = []
    source = IspAutoconfigSource(
        fetcher(
            {
                "autoconfig.firma.example/mail/config-v1.1.xml": httpx.Response(
                    200, content=config("imap.firma.example")
                )
            },
            seen,
        )
    )
    found = await source.lookup(QUERY)
    [candidate] = found.candidates
    assert candidate.source is DiscoverySourceName.AUTOCONFIG
    assert candidate.servers[0].host == "imap.firma.example"
    assert found.answered_by == "autoconfig.firma.example"
    assert len(seen) == 1
    assert seen[0].url.params["emailaddress"] == "me+x@firma.example"


async def test_isp_autoconfig_then_well_known() -> None:
    seen: list[httpx.Request] = []
    path = "firma.example/.well-known/autoconfig/mail/config-v1.1.xml"
    source = IspAutoconfigSource(
        fetcher({path: httpx.Response(200, content=config("mail.firma.example"))}, seen)
    )
    found = await source.lookup(QUERY)
    assert found.candidates[0].servers[0].host == "mail.firma.example"
    assert found.answered_by == "firma.example"
    assert [r.headers["host"] for r in seen] == [
        "autoconfig.firma.example",
        "firma.example",
    ]


async def test_isp_autoconfig_nothing() -> None:
    seen: list[httpx.Request] = []
    found = await IspAutoconfigSource(fetcher({}, seen)).lookup(QUERY)
    assert found.candidates == ()
    assert len(seen) == 2


async def test_isp_autoconfig_file_without_usable_server_is_nothing() -> None:
    plain = config("imap.firma.example").replace(b"SSL", b"plain")
    source = IspAutoconfigSource(
        fetcher(
            {
                "autoconfig.firma.example/mail/config-v1.1.xml": httpx.Response(
                    200, content=plain
                )
            },
            [],
        )
    )
    assert (await source.lookup(QUERY)).candidates == ()


async def test_isp_autoconfig_error_reported_when_nothing_else_answers() -> None:
    source = IspAutoconfigSource(
        fetcher(
            {
                "autoconfig.firma.example/mail/config-v1.1.xml": httpx.Response(
                    200, content=b"<x"
                )
            },
            [],
        )
    )
    with pytest.raises(ProviderError, match="not valid"):
        await source.lookup(QUERY)


async def test_isp_autoconfig_error_then_success() -> None:
    source = IspAutoconfigSource(
        fetcher(
            {
                "autoconfig.firma.example/mail/config-v1.1.xml": httpx.ConnectError(
                    "x"
                ),
                "firma.example/.well-known/autoconfig/mail/config-v1.1.xml": (
                    httpx.Response(200, content=config("imap.firma.example"))
                ),
            },
            [],
        )
    )
    assert len((await source.lookup(QUERY)).candidates) == 1


# --- ISPDB ------------------------------------------------------------------------


async def test_ispdb() -> None:
    seen: list[httpx.Request] = []
    source = IspdbSource(
        fetcher(
            {
                "autoconfig.thunderbird.net/v1.1/firma.example": httpx.Response(
                    200, content=config("imap.hoster.example")
                )
            },
            seen,
        )
    )
    found = await source.lookup(QUERY)
    assert found.candidates[0].source is DiscoverySourceName.ISPDB
    assert found.answered_by == "autoconfig.thunderbird.net"
    assert (await source.for_domain("other.example", DiscoverySourceName.MX)) == (
        await source.lookup(Query("a@other.example", "other.example"))
    )


# --- MX ---------------------------------------------------------------------------


def mx(*hosts: str) -> MxLookup:
    async def lookup(domain: str) -> list[str]:
        return list(hosts)

    return lookup


async def test_mx_to_a_preset() -> None:
    source = MxSource(lookup_mx=mx("firma-example.mail.protection.outlook.com"))
    found = await source.lookup(QUERY)
    [candidate] = found.candidates
    assert candidate.source is DiscoverySourceName.MX
    assert candidate.name == "Outlook.com"
    assert candidate.credential is CredentialKind.OAUTH
    assert found.answered_by == "firma-example.mail.protection.outlook.com"


async def test_mx_to_ispdb_of_the_base_domain() -> None:
    seen: list[httpx.Request] = []
    ispdb = IspdbSource(
        fetcher(
            {
                "autoconfig.thunderbird.net/v1.1/hoster.co.uk": httpx.Response(
                    200, content=config("imap.hoster.co.uk")
                )
            },
            seen,
        )
    )
    source = MxSource(ispdb=ispdb, lookup_mx=mx("mx1.hoster.co.uk"))
    found = await source.lookup(QUERY)
    assert found.candidates[0].source is DiscoverySourceName.MX
    assert found.candidates[0].servers[0].host == "imap.hoster.co.uk"
    assert [r.url.path for r in seen] == ["/v1.1/hoster.co.uk"]


async def test_mx_of_the_domain_itself_says_nothing() -> None:
    source = MxSource(lookup_mx=mx("mx.firma.example", "backup.firma.example"))
    assert (await source.lookup(QUERY)).candidates == ()


async def test_mx_without_ispdb_and_unknown_host() -> None:
    source = MxSource(lookup_mx=mx("mx.unknown.example"))
    assert await source.lookup(QUERY) == Finding()


async def test_mx_tries_the_next_host() -> None:
    source = MxSource(
        ispdb=IspdbSource(fetcher({}, [])),
        lookup_mx=mx("mx.unknown.example", "alt4.aspmx.l.google.com"),
    )
    found = await source.lookup(QUERY)
    assert found.candidates[0].provider is ProviderType.IMAP
    assert found.candidates[0].name == "Gmail"


async def test_mx_to_a_provider_without_access() -> None:
    source = MxSource(lookup_mx=mx("mail.tutanota.de"))
    found = await source.lookup(QUERY)
    assert found.candidates == ()
    assert found.hints


# --- JMAP well-known ------------------------------------------------------------------


def srv(*targets: tuple[str, int]) -> Callable[[str], Awaitable[list[tuple[str, int]]]]:
    async def lookup(name: str) -> list[tuple[str, int]]:
        assert name == "_jmap._tcp.firma.example"
        return list(targets)

    return lookup


async def test_jmap_asks_for_a_password_after_redirects() -> None:
    seen: list[httpx.Request] = []
    answers: dict[str, httpx.Response | Exception] = {
        "firma.example/.well-known/jmap": httpx.Response(
            307, headers={"Location": "https://jmap.firma.example/jmap/session"}
        ),
        "jmap.firma.example/jmap/session": httpx.Response(
            401, headers={"WWW-Authenticate": 'Basic realm="x", Bearer'}
        ),
    }
    source = JmapSource(fetcher(answers, seen), lookup_srv=srv())
    found = await source.lookup(QUERY)
    [candidate] = found.candidates
    assert found.answered_by == "jmap.firma.example"
    assert candidate.provider is ProviderType.JMAP
    assert candidate.credential is CredentialKind.PASSWORD
    [server] = candidate.servers
    assert (server.host, server.port, server.path) == (
        "jmap.firma.example",
        443,
        "/jmap/session",
    )
    assert server.reachable and server.capabilities == ["AUTH=BASIC", "AUTH=BEARER"]
    assert all("authorization" not in r.headers for r in seen)


async def test_jmap_with_a_token_only() -> None:
    answers: dict[str, httpx.Response | Exception] = {
        "firma.example/.well-known/jmap": httpx.Response(
            401, headers={"WWW-Authenticate": "Bearer"}
        )
    }
    found = await JmapSource(fetcher(answers, []), lookup_srv=srv()).lookup(QUERY)
    [candidate] = found.candidates
    assert candidate.credential is CredentialKind.API_TOKEN
    assert candidate.hints and "API token" in candidate.hints[0].text


async def test_jmap_session_without_a_login() -> None:
    session = {"capabilities": {"urn:ietf:params:jmap:core": {}}}
    answers: dict[str, httpx.Response | Exception] = {
        "firma.example/.well-known/jmap": httpx.Response(200, json=session)
    }
    found = await JmapSource(fetcher(answers, []), lookup_srv=srv()).lookup(QUERY)
    assert found.candidates[0].credential is CredentialKind.PASSWORD


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404),
        httpx.Response(401),
        httpx.Response(401, headers={"WWW-Authenticate": "Negotiate"}),
        httpx.Response(200, content=b"<html>"),
        httpx.Response(200, json={"capabilities": {}}),
    ],
)
async def test_jmap_nothing_there(answer: httpx.Response) -> None:
    answers: dict[str, httpx.Response | Exception] = {
        "firma.example/.well-known/jmap": answer
    }
    found = await JmapSource(fetcher(answers, []), lookup_srv=srv()).lookup(QUERY)
    assert found == Finding()


async def test_jmap_through_srv() -> None:
    answers: dict[str, httpx.Response | Exception] = {
        "firma.example/.well-known/jmap": ProviderError("no TLS"),
        "mail.hoster.example:8443/.well-known/jmap": httpx.Response(
            401, headers={"WWW-Authenticate": "Basic"}
        ),
    }
    source = JmapSource(
        fetcher(answers, []), lookup_srv=srv(("mail.hoster.example", 8443))
    )
    found = await source.lookup(QUERY)
    [server] = found.candidates[0].servers
    assert (server.host, server.port) == ("mail.hoster.example", 8443)
    assert found.answered_by == "mail.hoster.example"


async def test_jmap_reports_the_error_when_nothing_answers() -> None:
    async def failing(name: str) -> list[tuple[str, int]]:
        raise ProviderUnavailableError("the DNS lookup timed out")

    source = JmapSource(fetcher({}, []), lookup_srv=failing)
    with pytest.raises(ProviderUnavailableError, match="DNS"):
        await source.lookup(QUERY)


async def test_jmap_where_the_domain_does_not_resolve() -> None:
    async def nowhere(host: str, port: int) -> list[str]:
        return []

    source = JmapSource(SafeFetcher(resolve=nowhere), lookup_srv=srv())
    assert await source.lookup(QUERY) == Finding()


# --- SRV records ----------------------------------------------------------------------


class SrvRecord:
    def __init__(self, priority: int, weight: int, port: int, target: str) -> None:
        self.priority, self.weight, self.port = priority, weight, port
        self.target = dns.name.from_text(target)


class SrvResolver:
    def __init__(self, answer: list[SrvRecord] | Exception) -> None:
        self.answer = answer

    async def resolve(self, qname: str, rdtype: str, *, lifetime: float) -> Any:
        assert rdtype == "SRV"
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_srv_targets_by_priority_and_weight() -> None:
    resolver = SrvResolver(
        [
            SrvRecord(20, 0, 443, "backup.example."),
            SrvRecord(10, 1, 443, "light.example."),
            SrvRecord(10, 5, 8443, "Heavy.Example."),
        ]
    )
    assert await srv_targets("_jmap._tcp.x", resolver) == [
        ("heavy.example", 8443),
        ("light.example", 443),
        ("backup.example", 443),
    ]


async def test_srv_saying_not_offered_and_missing() -> None:
    assert await srv_targets("x", SrvResolver([SrvRecord(0, 0, 0, ".")])) == []
    assert await srv_targets("x", SrvResolver(dns.resolver.NXDOMAIN())) == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (dns.exception.Timeout(), "timed out"),
        (dns.exception.DNSException("x"), "failed"),
    ],
)
async def test_srv_lookups_that_fail(error: Exception, message: str) -> None:
    with pytest.raises(ProviderUnavailableError, match=message):
        await srv_targets("x", SrvResolver(error))
