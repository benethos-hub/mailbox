"""The building blocks of autodiscovery, offline: DNS, public suffixes, the
guarded HTTPS fetch and the autoconfig parser."""

from __future__ import annotations

from typing import Any

import dns.exception
import dns.rdata
import dns.resolver
import httpx
import pytest

from benethos_mailbox_api.data.discovery import autoconfig
from benethos_mailbox_api.data.discovery.dns import (
    host_addresses,
    is_public_address,
    mx_hosts,
)
from benethos_mailbox_api.data.discovery.fetch import SafeFetcher
from benethos_mailbox_api.data.discovery.suffix import (
    is_public_suffix,
    registrable_domain,
)
from benethos_mailbox_api.data.models import (
    CredentialKind,
    DiscoverySourceName,
    Security,
    ServerProtocol,
)
from benethos_mailbox_api.errors import ProviderError, ProviderUnavailableError

PUBLIC = "93.184.215.14"
PUBLIC_2 = "93.184.215.15"

# --- dns ------------------------------------------------------------------------


class FakeResolver:
    def __init__(self, records: list[str] | Exception) -> None:
        self.records = records
        self.asked: list[tuple[str, str]] = []

    async def resolve(self, qname: str, rdtype: str, *, lifetime: float) -> Any:
        self.asked.append((qname, rdtype))
        if isinstance(self.records, Exception):
            raise self.records
        return [dns.rdata.from_text("IN", "MX", r) for r in self.records]


async def test_mx_hosts_by_preference() -> None:
    resolver = FakeResolver(["20 mx2.example.net.", "10 MX1.Example.net."])
    assert await mx_hosts("example.com", resolver) == [
        "mx1.example.net",
        "mx2.example.net",
    ]
    assert resolver.asked == [("example.com", "MX")]


async def test_null_mx_means_no_mail() -> None:
    assert await mx_hosts("example.com", FakeResolver(["0 ."])) == []


@pytest.mark.parametrize("error", [dns.resolver.NXDOMAIN(), dns.resolver.NoAnswer()])
async def test_no_mx_is_empty(error: Exception) -> None:
    assert await mx_hosts("example.com", FakeResolver(error)) == []


async def test_dns_timeout_is_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="timed out"):
        await mx_hosts("example.com", FakeResolver(dns.exception.Timeout()))
    with pytest.raises(ProviderUnavailableError, match="failed"):
        await mx_hosts("example.com", FakeResolver(dns.resolver.NoNameservers()))


async def test_host_addresses_of_localhost_and_nowhere() -> None:
    assert "127.0.0.1" in await host_addresses("127.0.0.1", 443)
    assert await host_addresses("does-not-exist.invalid", 443) == []


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("8.8.8.8", True),
        ("2a00:1450:4001::1", True),
        ("10.1.2.3", False),
        ("192.168.0.1", False),
        ("127.0.0.1", False),
        ("::1", False),
        ("fe80::1%3", False),
        ("100.64.0.1", False),
        ("169.254.169.254", False),
        ("224.0.0.1", False),
        ("0.0.0.0", False),
        ("::ffff:10.0.0.1", False),
        ("::ffff:8.8.8.8", True),
    ],
)
def test_public_addresses(address: str, public: bool) -> None:
    assert is_public_address(address) is public


# --- suffix ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "base"),
    [
        ("mx00.t-online.de", "t-online.de"),
        ("mail.firma.co.uk", "firma.co.uk"),
        ("mx.kunde.com.au", "kunde.com.au"),
        ("Example.DE.", "example.de"),
        ("mail.firma.neuetld", "firma.neuetld"),
        ("co.uk", None),
        ("de", None),
    ],
)
def test_registrable_domain(host: str, base: str | None) -> None:
    assert registrable_domain(host) == base


def test_public_suffixes() -> None:
    assert is_public_suffix("co.uk")
    assert is_public_suffix("de")
    assert not is_public_suffix("example.de")


# --- fetch ----------------------------------------------------------------------


def resolver(table: dict[str, list[str]]) -> Any:
    async def resolve(host: str, port: int) -> list[str]:
        return table.get(host, [])

    return resolve


def fetcher(
    handler: Any, table: dict[str, list[str]], **kwargs: Any
) -> tuple[SafeFetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    return (
        SafeFetcher(
            resolve=resolver(table), transport=httpx.MockTransport(record), **kwargs
        ),
        seen,
    )


async def test_fetch_pins_the_checked_address() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(200, content=b"<ok/>"),
        {"autoconfig.example.com": [PUBLIC]},
    )
    result = await f.get("https://autoconfig.example.com/mail/config-v1.1.xml?x=1")
    assert result is not None
    assert result.body == b"<ok/>"
    assert result.host == "autoconfig.example.com"
    [request] = seen
    assert request.url.host == PUBLIC
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "autoconfig.example.com"
    assert request.extensions["sni_hostname"] == "autoconfig.example.com"


async def test_fetch_nothing_when_the_host_does_not_resolve() -> None:
    f, seen = fetcher(lambda r: httpx.Response(200), {})
    assert await f.get("https://autoconfig.example.com/x") is None
    assert seen == []


async def test_fetch_nothing_on_other_status() -> None:
    f, _ = fetcher(lambda r: httpx.Response(404), {"example.com": [PUBLIC]})
    assert await f.get("https://example.com/x") is None


async def test_fetch_refuses_http() -> None:
    f, seen = fetcher(lambda r: httpx.Response(200), {"example.com": [PUBLIC]})
    with pytest.raises(ProviderError, match="HTTPS only"):
        await f.get("http://example.com/x")
    assert seen == []


@pytest.mark.parametrize("private", ["127.0.0.1", "10.0.0.5", "::1", "169.254.1.1"])
async def test_fetch_refuses_private_addresses(private: str) -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(200), {"evil.example": [PUBLIC, private]}
    )
    with pytest.raises(ProviderError, match="non-public"):
        await f.get("https://evil.example/x")
    assert seen == []


async def test_fetch_allows_internal_hosts_by_name() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(200, content=b"ok"),
        {"mail.intern.example": ["10.0.0.5"]},
        internal_hosts=["Mail.Intern.Example."],
    )
    result = await f.get("https://mail.intern.example/x")
    assert result is not None and result.body == b"ok"
    assert seen[0].url.host == "10.0.0.5"


async def test_fetch_follows_redirects_and_checks_each_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if host == "autoconfig.example.com":
            return httpx.Response(
                301, headers={"location": "https://config.hoster.example/c.xml"}
            )
        return httpx.Response(200, content=b"final")

    f, seen = fetcher(
        handler,
        {"autoconfig.example.com": [PUBLIC], "config.hoster.example": [PUBLIC_2]},
    )
    result = await f.get("https://autoconfig.example.com/x")
    assert result is not None
    assert result.body == b"final"
    assert result.host == "config.hoster.example"
    assert result.url == "https://config.hoster.example/c.xml"
    assert [r.url.host for r in seen] == [PUBLIC, PUBLIC_2]


async def test_fetch_relative_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, content=request.url.path.encode())

    f, _ = fetcher(handler, {"example.com": [PUBLIC]})
    result = await f.get("https://example.com/a")
    assert result is not None and result.body == b"/b"


async def test_fetch_redirect_to_a_private_address_is_refused() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(302, headers={"location": "https://inside.example/"}),
        {"example.com": [PUBLIC], "inside.example": ["192.168.1.1"]},
    )
    with pytest.raises(ProviderError, match="non-public"):
        await f.get("https://example.com/")
    assert len(seen) == 1


async def test_fetch_redirect_to_http_is_refused() -> None:
    f, _ = fetcher(
        lambda r: httpx.Response(302, headers={"location": "http://example.com/"}),
        {"example.com": [PUBLIC]},
    )
    with pytest.raises(ProviderError, match="HTTPS only"):
        await f.get("https://example.com/")


async def test_fetch_redirect_without_location_is_nothing() -> None:
    f, _ = fetcher(lambda r: httpx.Response(302), {"example.com": [PUBLIC]})
    assert await f.get("https://example.com/") is None


async def test_fetch_stops_after_three_redirects() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(302, headers={"location": "/again"}),
        {"example.com": [PUBLIC]},
    )
    with pytest.raises(ProviderError, match="redirects"):
        await f.get("https://example.com/")
    assert len(seen) == 4


async def test_fetch_size_limit() -> None:
    f, _ = fetcher(
        lambda r: httpx.Response(200, content=b"x" * 2000),
        {"example.com": [PUBLIC]},
        max_bytes=1000,
    )
    with pytest.raises(ProviderError, match="larger than 1000 bytes"):
        await f.get("https://example.com/")


async def test_fetch_network_errors_are_unavailable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler, text in [(timeout, "in time"), (refused, "not reachable")]:
        f, _ = fetcher(handler, {"example.com": [PUBLIC]})
        with pytest.raises(ProviderUnavailableError, match=text):
            await f.get("https://example.com/")


# --- autoconfig -----------------------------------------------------------------

CONFIG = b"""<?xml version="1.0"?>
<clientConfig version="1.1">
  <emailProvider id="example.com">
    <domain>example.com</domain>
    <displayName>Example Mail</displayName>
    <incomingServer type="pop3">
      <hostname>pop.example.com</hostname><port>995</port>
      <socketType>SSL</socketType><username>%EMAILADDRESS%</username>
      <authentication>password-cleartext</authentication>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>imap.%EMAILDOMAIN%</hostname><port>993</port>
      <socketType>SSL</socketType><username>%EMAILADDRESS%</username>
      <authentication>password-cleartext</authentication>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>imap.example.com</hostname><port>143</port>
      <socketType>STARTTLS</socketType><username>%EMAILLOCALPART%</username>
      <authentication>OAuth2</authentication>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>plain.example.com</hostname><port>143</port>
      <socketType>plain</socketType><username>%EMAILADDRESS%</username>
      <authentication>password-cleartext</authentication>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>ntlm.example.com</hostname><port>993</port>
      <socketType>SSL</socketType><username>%EMAILADDRESS%</username>
      <authentication>NTLM</authentication>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>smtp.example.com</hostname><port>587</port>
      <socketType>STARTTLS</socketType><username>%EMAILADDRESS%</username>
      <authentication>password-cleartext</authentication>
    </outgoingServer>
    <documentation url="https://example.com/help/imap">
      <descr lang="de">IMAP einschalten</descr>
      <descr lang="en">Switch on IMAP first</descr>
    </documentation>
    <documentation url="http://example.com/insecure">
      <descr>Plain link</descr>
    </documentation>
  </emailProvider>
</clientConfig>
"""


def test_parse_keeps_what_can_be_used() -> None:
    candidates = autoconfig.parse(CONFIG, "example.com", DiscoverySourceName.ISPDB)
    assert len(candidates) == 2
    first, second = candidates
    assert first.name == "Example Mail"
    assert first.source is DiscoverySourceName.ISPDB
    assert first.credential is CredentialKind.PASSWORD
    imap, smtp = first.servers
    assert (imap.protocol, imap.host, imap.port, imap.security) == (
        ServerProtocol.IMAP,
        "imap.example.com",
        993,
        Security.TLS,
    )
    assert imap.username == "%EMAILADDRESS%"
    assert (smtp.protocol, smtp.host, smtp.port, smtp.security) == (
        ServerProtocol.SMTP,
        "smtp.example.com",
        587,
        Security.STARTTLS,
    )
    assert second.credential is CredentialKind.OAUTH
    assert second.servers[0].security is Security.STARTTLS
    assert second.servers[0].username == "%EMAILLOCALPART%"
    assert [(h.text, h.url) for h in first.hints] == [
        ("Switch on IMAP first", "https://example.com/help/imap"),
        ("Plain link", None),
    ]


@pytest.mark.parametrize(
    "xml",
    [
        b"not xml",
        b"<other/>",
        b"<clientConfig/>",
        # Entity expansion is refused, not performed.
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        b"<clientConfig><emailProvider>&a;</emailProvider></clientConfig>",
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b"<clientConfig><emailProvider>&e;</emailProvider></clientConfig>",
    ],
)
def test_parse_refuses_broken_or_hostile_files(xml: bytes) -> None:
    with pytest.raises(ProviderError):
        autoconfig.parse(xml, "example.com", DiscoverySourceName.AUTOCONFIG)


@pytest.mark.parametrize(
    ("host", "port"),
    [
        ("bad host", "993"),
        ("imap.example.com/evil", "993"),
        ("", "993"),
        ("imap.example.com", "0"),
        ("imap.example.com", "70000"),
        ("imap.example.com", "abc"),
        ("a" * 70 + ".example.com", "993"),
    ],
)
def test_parse_drops_invalid_servers(host: str, port: str) -> None:
    xml = f"""<clientConfig><emailProvider>
      <incomingServer type="imap"><hostname>{host}</hostname><port>{port}</port>
      <socketType>SSL</socketType><authentication>plain</authentication>
      </incomingServer></emailProvider></clientConfig>""".encode()
    assert autoconfig.parse(xml, "example.com", DiscoverySourceName.ISPDB) == []


def test_parse_idn_host_to_ascii() -> None:
    xml = """<clientConfig><emailProvider>
      <incomingServer type="imap"><hostname>imap.bücher.example</hostname>
      <port>993</port><socketType>SSL</socketType>
      <authentication>password-encrypted</authentication><username>x y</username>
      </incomingServer></emailProvider></clientConfig>""".encode()
    [candidate] = autoconfig.parse(xml, "example.com", DiscoverySourceName.ISPDB)
    assert candidate.servers[0].host == "imap.xn--bcher-kva.example"
    # A username that is no template and no login name is left out.
    assert candidate.servers[0].username is None


def test_parse_skips_empty_documentation() -> None:
    xml = b"""<clientConfig><emailProvider>
      <incomingServer type="imap"><hostname>imap.example.com</hostname>
      <port>993</port><socketType>SSL</socketType>
      <authentication>plain</authentication></incomingServer>
      <documentation><descr lang="en"> </descr></documentation>
      <documentation url="https://example.com/help"/>
      </emailProvider></clientConfig>"""
    [candidate] = autoconfig.parse(xml, "example.com", DiscoverySourceName.ISPDB)
    assert [(h.text, h.url) for h in candidate.hints] == [
        ("Setup instructions of the provider", "https://example.com/help")
    ]
