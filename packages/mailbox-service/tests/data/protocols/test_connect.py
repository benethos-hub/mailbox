"""Connections to a mail server go to the address checked at that moment,
with TLS verified against the host name (CONCEPT 5.8, rule 6)."""

from __future__ import annotations

import socket
import ssl
from typing import Any

import pytest

from benethos_mailbox_service.data.protocols import imap, smtp
from benethos_mailbox_service.data.protocols.http import SafeFetcher
from benethos_mailbox_service.data.protocols.imap import ImapServer, ImapSession
from benethos_mailbox_service.data.protocols.smtp import SmtpServer
from benethos_mailbox_service.data.protocols.transport import tls_context
from benethos_mailbox_service.errors import ProviderError, ProviderUnavailableError

ADDRESS = "192.0.2.7"


def pick(host: str, port: int) -> str:
    return ADDRESS


def refuse(host: str, port: int) -> str:
    raise ProviderError(f"refused to connect to {host}")


class Library:
    """Stands in for IMAPClient, SMTP and SMTP_SSL: records how it is made."""

    made: list[tuple[str, int, Any]] = []

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.made.append((host, port, kwargs.get("ssl_context", kwargs.get("context"))))

    def starttls(self, context: Any = None, **kwargs: Any) -> None:
        self.made.append(("starttls", 0, context or kwargs.get("context")))


@pytest.fixture(autouse=True)
def library(monkeypatch: pytest.MonkeyPatch) -> type[Library]:
    Library.made = []
    monkeypatch.setattr(imap, "IMAPClient", Library)
    monkeypatch.setattr(smtp.smtplib, "SMTP_SSL", Library)
    monkeypatch.setattr(smtp.smtplib, "SMTP", Library)
    return Library


def test_the_context_verifies_the_host_name_on_any_address() -> None:
    context = tls_context("imap.example.org")
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED
    with socket.socket() as raw:
        wrapped = context.wrap_socket(
            raw, server_hostname=ADDRESS, do_handshake_on_connect=False
        )
        assert wrapped.server_hostname == "imap.example.org"


@pytest.mark.parametrize("security", ["tls", "starttls"])
def test_imap_connects_to_the_picked_address(security: str) -> None:
    server = ImapServer("imap.example.org", 993, security, pick=pick)
    imap._default_client(server, 5.0)
    host, port, _ = Library.made[0]
    assert (host, port) == (ADDRESS, 993)
    context = Library.made[-1][2]
    assert isinstance(context, ssl.SSLContext)
    assert context.name == "imap.example.org"  # type: ignore[attr-defined]


@pytest.mark.parametrize("security", ["tls", "starttls"])
def test_smtp_connects_to_the_picked_address(security: str) -> None:
    smtp._default_connection(SmtpServer("smtp.example.org", 465, security, pick), 5.0)
    host, port, _ = Library.made[0]
    assert (host, port) == (ADDRESS, 465)
    context = Library.made[-1][2]
    assert context.name == "smtp.example.org"


def test_without_a_pick_the_name_is_used() -> None:
    imap._default_client(ImapServer("imap.example.org", 993, "tls"), 5.0)
    assert Library.made[0][0] == "imap.example.org"


def test_a_refused_host_is_not_connected_to() -> None:
    session = ImapSession(ImapServer("imap.example.org", 993, "tls", pick=refuse))
    with pytest.raises(ProviderError, match="refused"):
        session.read_capabilities()
    assert Library.made == []


TABLE = {
    "imap.example.org": ["93.184.215.14"],
    "mail.internal": ["10.0.0.5"],
    "rebound.example.org": ["93.184.215.14", "10.0.0.5"],
}


def fetcher(internal: list[str] | None = None) -> SafeFetcher:
    return SafeFetcher(
        internal_hosts=internal or [],
        lookup=lambda host, port: TABLE.get(host.lower().rstrip("."), []),
    )


def test_connect_address_follows_the_rule_of_the_host_check() -> None:
    assert fetcher().connect_address("imap.example.org", 993) == "93.184.215.14"
    for host in ("mail.internal", "rebound.example.org"):
        with pytest.raises(ProviderError, match="non-public"):
            fetcher().connect_address(host, 993)
    assert fetcher(["mail.internal"]).connect_address("Mail.Internal.", 993) == (
        "10.0.0.5"
    )
    with pytest.raises(ProviderUnavailableError, match="does not resolve"):
        fetcher().connect_address("nowhere.example", 993)
