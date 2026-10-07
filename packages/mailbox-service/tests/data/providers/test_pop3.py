"""The POP3 adapter and its session, against a fake server: settings, the
session, the one folder, sending and discovered servers."""

from __future__ import annotations

import poplib
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import (
    CredentialKind,
    FolderRole,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.data.protocols import pop3 as pop3_protocol
from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.data.protocols.smtp import SmtpSession
from benethos_mailbox_service.data.providers import (
    Capability,
    Deletes,
    Deltas,
    Drafts,
    Reads,
    Sends,
    Watches,
    Writes,
    build_provider,
    capabilities_of,
    probe_server,
    settings_from_servers,
)
from benethos_mailbox_service.data.providers.pop3 import Pop3Provider, mappers
from benethos_mailbox_service.data.providers.pop3 import provider as pop3_module
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    NotSupportedError,
    ProviderAuthError,
    ProviderUnavailableError,
)

from ...imap_fake import make_message
from ...pop3_fake import FakePop3Server
from ...smtp_fake import FakeSmtpServer

SETTINGS = {"host": "pop.example.com", "username": "me@example.com"}
INBOX = mappers.folder_id()


def filled_server() -> FakePop3Server:
    """Five mails, one a day from the first of September."""
    box = FakePop3Server()
    for n in range(1, 6):
        box.add(
            f"uid-{n}",
            make_message(f"Mail {n}", date=datetime(2026, 9, n, 10, 0, tzinfo=UTC)),
        )
    return box


@pytest.fixture
def server() -> FakePop3Server:
    return filled_server()


def provider(
    box: FakePop3Server, smtp: FakeSmtpServer | None = None, **overrides: Any
) -> Pop3Provider:
    def credentials(field: str) -> SecretStr:
        assert field == "password"
        return SecretStr("secret")

    settings = {**SETTINGS, **overrides}
    if smtp is not None:
        settings["smtp_host"] = "smtp.example.com"
    return Pop3Provider(
        settings,
        credentials,
        session_factory=lambda s: Pop3Session(s, connection_factory=box),
        sleep=lambda seconds: None,
        smtp_factory=lambda s: SmtpSession(s, connection_factory=smtp),
    )


def subjects(items: list[Any]) -> list[str | None]:
    return [item.subject for item in items]


# --- settings and capabilities ----------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"username": "u"}, "settings.host"),
        ({"host": "h"}, "settings.username"),
        ({**SETTINGS, "security": "none"}, "without encryption"),
        ({**SETTINGS, "auth": "xoauth2"}, "settings.auth"),
        ({**SETTINGS, "port": 70000}, "settings.port"),
    ],
)
def test_invalid_settings(settings: dict[str, Any], message: str) -> None:
    with pytest.raises(BadRequestError, match=message):
        Pop3Provider(settings, lambda f: SecretStr("x"))


def test_the_default_ports(server: FakePop3Server) -> None:
    for security, port in (("tls", 995), ("starttls", 110)):
        server.calls.clear()
        anyio_run(provider(server, security=security).verify)
        assert server.calls[0] == ("connect", "pop.example.com", port, security)


def test_no_flags_folders_search_or_drafts(server: FakePop3Server) -> None:
    assert provider(server).capabilities == frozenset()
    with_smtp = provider(server, smtp=FakeSmtpServer())
    assert with_smtp.capabilities == {Capability.SEND}


def test_the_registry_builds_it(server: FakePop3Server) -> None:
    built = build_provider(ProviderType.POP3, SETTINGS, lambda f: SecretStr("x"))
    assert isinstance(built, Pop3Provider)


# --- the session ------------------------------------------------------------------


async def test_verify_logs_in_reads_the_unique_ids_and_quits(
    server: FakePop3Server,
) -> None:
    await provider(server).verify()
    names = [call[0] for call in server.calls]
    assert names == ["connect", "user", "pass", "uidl", "rset", "quit"]


async def test_a_rejected_login(server: FakePop3Server) -> None:
    server.password = "other"
    adapter = provider(server)
    with pytest.raises(ProviderAuthError):
        await adapter.verify()
    # No new attempt until the credential changes or the account is verified.
    with pytest.raises(ProviderAuthError, match="rejected the login before"):
        await adapter.folder_states()


@pytest.mark.parametrize(
    "refusal", [b"-ERR [IN-USE] mailbox locked", b"-ERR [SYS/TEMP] try again later"]
)
async def test_a_login_refused_for_now_is_no_rejection(
    server: FakePop3Server, refusal: bytes
) -> None:
    server.login_refusal = refusal
    with pytest.raises(ProviderUnavailableError, match="for now"):
        await provider(server).verify()


async def test_a_server_without_uidl_is_refused(server: FakePop3Server) -> None:
    server.uidl = False
    with pytest.raises(NotSupportedError, match="UIDL"):
        await provider(server).verify()


async def test_an_unreachable_server(server: FakePop3Server) -> None:
    server.failure = ConnectionRefusedError("refused")
    session = Pop3Session(pop3_protocol_server(), connection_factory=server)
    with pytest.raises(ProviderUnavailableError, match="not reachable"):
        session.login("me", "secret")


def test_long_lines_are_read(server: FakePop3Server) -> None:
    """poplib refuses lines over 2048 bytes. Mail with HTML in one line
    breaks that limit, so the module raises it."""
    assert poplib._MAXLINE >= pop3_protocol.MAX_MESSAGE_BYTES  # type: ignore[attr-defined]


async def test_capabilities_are_read_without_a_login(server: FakePop3Server) -> None:
    session = Pop3Session(pop3_protocol_server(), connection_factory=server)
    assert session.read_capabilities() == {"TOP", "UIDL", "USER"}
    assert "user" not in [call[0] for call in server.calls]


async def test_the_probe_connects_to_the_address_it_is_given(
    server: FakePop3Server,
) -> None:
    seen: list[Any] = []

    def remember(s: Any) -> Pop3Session:
        seen.append(s)
        return Pop3Session(s, connection_factory=server)

    found = await pop3_module.probe(
        "pop.example.com", 995, "tls", "192.0.2.1", session_factory=remember
    )
    assert found == {"TOP", "UIDL", "USER"}
    [probed] = seen
    assert probed.pick(probed.host, probed.port) == "192.0.2.1"
    with pytest.raises(BadRequestError):
        await pop3_module.probe("pop.example.com", 110, "none")


async def test_the_registry_probes_pop3(monkeypatch: pytest.MonkeyPatch) -> None:
    from benethos_mailbox_service.data.providers import registry

    async def probe(*args: Any) -> frozenset[str]:
        return frozenset({"UIDL"})

    monkeypatch.setattr(registry, "probe_pop3", probe)
    found = await probe_server(
        ServerProtocol.POP3, "pop.example.com", 995, Security.TLS, "192.0.2.1"
    )
    assert found == {"UIDL"}


# --- folders ----------------------------------------------------------------------


async def test_the_one_folder_is_the_inbox(server: FakePop3Server) -> None:
    [inbox] = await provider(server).list_folders()
    assert (inbox.id, inbox.role) == (INBOX, FolderRole.INBOX)
    assert server.calls == []  # known without asking the server


def test_it_reads_deletes_and_sends_and_nothing_else(
    server: FakePop3Server,
) -> None:
    """No flags, folders, drafts, push or delta: the adapter implements
    none of those, and the domain answers 501 for them."""
    adapter = provider(server, smtp=FakeSmtpServer())
    for protocol in (Reads, Deletes, Sends):
        assert isinstance(adapter, protocol)
    for protocol in (Writes, Drafts, Watches, Deltas):
        assert not isinstance(adapter, protocol)
    assert capabilities_of(adapter) == {Capability.SEND}


# --- sending ----------------------------------------------------------------------


async def test_sending_over_smtp_keeps_no_copy(server: FakePop3Server) -> None:
    smtp = FakeSmtpServer()
    sent = await provider(server, smtp=smtp).send(
        make_message("Out"), "me@example.com", ["you@example.org"]
    )
    assert sent.refused == [] and sent.sent_copy is None and sent.copy_error is None
    assert [m.recipients for m in smtp.sent] == [["you@example.org"]]
    assert len(server.messages) == 5


async def test_without_smtp_it_cannot_send(server: FakePop3Server) -> None:
    with pytest.raises(ConflictError, match="no SMTP server"):
        await provider(server).send(b"", "me@example.com", ["you@example.org"])


async def test_verify_checks_smtp_too(server: FakePop3Server) -> None:
    smtp = FakeSmtpServer(password="other")
    with pytest.raises(ProviderAuthError):
        await provider(server, smtp=smtp).verify()


# --- discovered servers -----------------------------------------------------------


def test_settings_from_discovered_servers() -> None:
    servers = [
        MailServer(
            protocol=ServerProtocol.POP3,
            host="pop.example.com",
            port=995,
            security=Security.TLS,
        ),
        MailServer(
            protocol=ServerProtocol.SMTP,
            host="smtp.example.com",
            port=587,
            security=Security.STARTTLS,
            username="login@example.com",
        ),
    ]
    settings = settings_from_servers(
        ProviderType.POP3, servers, CredentialKind.PASSWORD, "me@example.com"
    )
    assert settings == {
        "host": "pop.example.com",
        "port": 995,
        "security": "tls",
        "username": "me@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "login@example.com",
    }
    assert (
        settings_from_servers(
            ProviderType.POP3, servers[1:], CredentialKind.PASSWORD, "me@example.com"
        )
        == {}
    )


# --- helpers ----------------------------------------------------------------------


def pop3_protocol_server() -> Any:
    from benethos_mailbox_service.data.protocols import Server

    return Server(host="pop.example.com", port=995, security="tls")


def anyio_run(step: Any) -> None:
    import anyio

    anyio.run(step)
