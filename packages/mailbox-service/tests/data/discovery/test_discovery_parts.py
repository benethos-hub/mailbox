"""The building blocks of autodiscovery, offline: DNS, public suffixes and
the autoconfig parser."""

from __future__ import annotations

from typing import Any

import dns.exception
import dns.rdata
import dns.resolver
import pytest

from benethos_mailbox_service.data.discovery import autoconfig
from benethos_mailbox_service.data.discovery.dns import mx_hosts
from benethos_mailbox_service.data.discovery.suffix import (
    registrable_domain,
)
from benethos_mailbox_service.data.models import (
    CredentialKind,
    DiscoverySourceName,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.data.protocols.http import (
    host_addresses,
    is_public_address,
)
from benethos_mailbox_service.errors import ProviderError, ProviderUnavailableError

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
        ("64:ff9b::a00:1", False),
        ("64:ff9b::808:808", True),
        ("64:ff9b:1::808:808", False),
        ("2002:a00:1::1", False),
        ("::7f00:1", False),
        ("::a00:1", False),
        ("fec0::1", False),
        ("fc00::1", False),
        ("100::1", False),
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


def test_a_public_suffix_is_no_domain() -> None:
    assert registrable_domain("co.uk") is None
    assert registrable_domain("de") is None
    assert registrable_domain("example.de") == "example.de"


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


def test_parse_offers_pop3_only_without_imap() -> None:
    """The file above names POP3 and IMAP: only IMAP is kept. A file with
    POP3 alone gives a POP3 candidate (CONCEPT 5.2)."""
    xml = b"""<clientConfig><emailProvider><displayName>Old Mail</displayName>
      <incomingServer type="pop3"><hostname>pop.example.com</hostname>
      <port>995</port><socketType>SSL</socketType>
      <authentication>password-cleartext</authentication></incomingServer>
      <incomingServer type="imap"><hostname>imap.example.com</hostname>
      <port>143</port><socketType>plain</socketType>
      <authentication>password-cleartext</authentication></incomingServer>
      <outgoingServer type="smtp"><hostname>smtp.example.com</hostname>
      <port>465</port><socketType>SSL</socketType>
      <authentication>password-cleartext</authentication></outgoingServer>
      </emailProvider></clientConfig>"""
    [candidate] = autoconfig.parse(xml, "example.com", DiscoverySourceName.ISPDB)
    assert candidate.provider is ProviderType.POP3
    pop3, smtp = candidate.servers
    assert (pop3.protocol, pop3.host, pop3.port) == (
        ServerProtocol.POP3,
        "pop.example.com",
        995,
    )
    assert smtp.protocol is ServerProtocol.SMTP
    with_imap = autoconfig.parse(CONFIG, "example.com", DiscoverySourceName.ISPDB)
    assert {c.provider for c in with_imap} == {ProviderType.IMAP}


def test_parse_keeps_a_host_under_an_idn_top_level_domain() -> None:
    xml = """<clientConfig><emailProvider>
      <incomingServer type="imap"><hostname>imap.почта.рф</hostname>
      <port>993</port><socketType>SSL</socketType>
      <authentication>password-encrypted</authentication>
      </incomingServer></emailProvider></clientConfig>""".encode()
    [candidate] = autoconfig.parse(xml, "example.com", DiscoverySourceName.ISPDB)
    assert candidate.servers[0].host == "imap.xn--80a1acny.xn--p1ai"


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
