"""The POP3 adapter and its session, against a fake server: one folder, no
flags, permanent deletion, a session per step."""

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
    MessageFilter,
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
    MessageNotFoundError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...imap_fake import make_message
from ...pop3_fake import FakePop3Server
from ...smtp_fake import FakeSmtpServer

SETTINGS = {"host": "pop.example.com", "username": "me@example.com"}
INBOX = mappers.folder_id()


@pytest.fixture
def server() -> FakePop3Server:
    box = FakePop3Server()
    for n in range(1, 6):
        box.add(
            f"uid-{n}",
            make_message(f"Mail {n}", date=datetime(2026, 9, n, 10, 0, tzinfo=UTC)),
        )
    return box


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


# --- listing and reading ----------------------------------------------------------


async def test_newest_first_with_a_cursor(server: FakePop3Server) -> None:
    adapter = provider(server)
    first = await adapter.list_messages(None, limit=2, cursor=None)
    assert subjects(first.items) == ["Mail 5", "Mail 4"]
    assert first.items[0].folder_ids == [INBOX]
    assert not first.items[0].unread and not first.items[0].starred
    second = await adapter.list_messages(INBOX, limit=2, cursor=first.next_cursor)
    assert subjects(second.items) == ["Mail 3", "Mail 2"]
    third = await adapter.list_messages(INBOX, limit=2, cursor=second.next_cursor)
    assert subjects(third.items) == ["Mail 1"] and third.next_cursor is None


async def test_a_cursor_holds_when_messages_arrive_or_leave(
    server: FakePop3Server,
) -> None:
    adapter = provider(server)
    first = await adapter.list_messages(None, limit=2, cursor=None)
    server.add("uid-6", make_message("Mail 6"))
    following = await adapter.list_messages(None, limit=2, cursor=first.next_cursor)
    assert subjects(following.items) == ["Mail 3", "Mail 2"]


async def test_a_cursor_whose_message_is_gone_goes_on_from_its_place(
    server: FakePop3Server,
) -> None:
    adapter = provider(server)
    first = await adapter.list_messages(None, limit=2, cursor=None)
    del server.messages["uid-4"]
    following = await adapter.list_messages(None, limit=2, cursor=first.next_cursor)
    assert subjects(following.items) == ["Mail 3", "Mail 2"]


async def test_lists_read_headers_only(server: FakePop3Server) -> None:
    await provider(server).list_messages(None, limit=2, cursor=None)
    names = {call[0] for call in server.calls}
    assert "top" in names and "retr" not in names


async def test_without_top_the_whole_message_gives_the_headers(
    server: FakePop3Server,
) -> None:
    server.top = False
    server.capabilities = ["UIDL", "USER"]
    page = await provider(server).list_messages(None, limit=1, cursor=None)
    assert subjects(page.items) == ["Mail 5"]


@pytest.mark.parametrize("cursor", ["junk", mappers.message_id("uid-1")])
async def test_an_invalid_cursor(server: FakePop3Server, cursor: str) -> None:
    with pytest.raises(BadRequestError, match="invalid cursor"):
        await provider(server).list_messages(None, limit=2, cursor=cursor)


async def test_another_folder_is_not_found(server: FakePop3Server) -> None:
    with pytest.raises(NotFoundError, match="folder"):
        await provider(server).list_messages("f_other", limit=2, cursor=None)


async def test_a_search_is_not_supported(server: FakePop3Server) -> None:
    adapter = provider(server)
    with pytest.raises(NotSupportedError, match="searched"):
        await adapter.list_messages(
            None, limit=2, cursor=None, search=MessageFilter(unread=True)
        )
    # An empty filter narrows nothing.
    page = await adapter.list_messages(
        None, limit=2, cursor=None, search=MessageFilter()
    )
    assert len(page.items) == 2


async def test_a_message_its_attachment_and_its_source(
    server: FakePop3Server,
) -> None:
    server.add(
        "uid-9",
        make_message(
            "With files", attachments=[("a.txt", "text/plain", b"attached text")]
        ),
    )
    adapter = provider(server)
    message_id = mappers.message_id("uid-9")
    message = await adapter.get_message(message_id)
    assert message.id == message_id and message.subject == "With files"
    assert message.text_body and message.text_body.strip() == "Hello"
    [attachment] = message.attachments
    content = await adapter.get_attachment(message_id, attachment.id)
    assert content.data == b"attached text"
    assert b"Subject: With files" in await adapter.get_raw(message_id)


@pytest.mark.parametrize("message_id", ["junk", mappers.message_id("uid-404")])
async def test_a_missing_message(server: FakePop3Server, message_id: str) -> None:
    with pytest.raises(MessageNotFoundError):
        await provider(server).get_message(message_id)


async def test_a_message_too_large_is_refused(server: FakePop3Server) -> None:
    adapter = Pop3Provider(
        SETTINGS,
        lambda f: SecretStr("secret"),
        session_factory=lambda s: Pop3Session(
            s, connection_factory=server, max_bytes=100
        ),
    )
    with pytest.raises(ProviderError, match="larger than 100 bytes"):
        await adapter.get_raw(mappers.message_id("uid-1"))


async def test_every_step_sees_the_mailbox_as_it_is_now(
    server: FakePop3Server,
) -> None:
    """A POP3 session sees the mailbox as at its login: each step logs in
    afresh and quits at once, so the server is never held locked."""
    adapter = provider(server)
    await adapter.list_messages(None, limit=1, cursor=None)
    server.add("uid-6", make_message("Mail 6"))
    page = await adapter.list_messages(None, limit=1, cursor=None)
    assert subjects(page.items) == ["Mail 6"]
    assert server.connections == 2
    assert [c[0] for c in server.calls].count("quit") == 2


# --- changing messages ------------------------------------------------------------


async def test_no_trash(server: FakePop3Server) -> None:
    with pytest.raises(NotSupportedError, match="no trash"):
        await provider(server).delete_messages(
            [mappers.message_id("uid-1")], permanent=False
        )
    assert "uid-1" in server.messages


async def test_deleting_for_good(server: FakePop3Server) -> None:
    one, two = mappers.message_id("uid-1"), mappers.message_id("uid-2")
    results = await provider(server).delete_messages(
        [one, two, mappers.message_id("uid-404"), "junk"], permanent=True
    )
    assert results[one] is None and results[two] is None
    assert isinstance(results[mappers.message_id("uid-404")], MessageNotFoundError)
    assert isinstance(results["junk"], MessageNotFoundError)
    assert list(server.messages) == ["uid-3", "uid-4", "uid-5"]


async def test_a_quit_the_server_does_not_confirm_keeps_the_messages(
    server: FakePop3Server,
) -> None:
    server.quit_refusal = b"-ERR could not remove"
    with pytest.raises(ProviderError, match="did not finish"):
        await provider(server).delete_messages(
            [mappers.message_id("uid-1")], permanent=True
        )
    assert "uid-1" in server.messages


def test_a_retried_delete_counts_a_message_gone_as_deleted(
    server: FakePop3Server,
) -> None:
    """The first try may have ended its session with QUIT before the
    connection dropped: on the retry the message is gone, as wanted."""
    session = Pop3Session(pop3_protocol_server(), connection_factory=server)
    session.login("me", "secret")
    wanted = {mappers.message_id("uid-404"): "uid-404"}
    assert pop3_module._delete(session, wanted, retried=True) == {
        mappers.message_id("uid-404"): None
    }
    first = pop3_module._delete(session, wanted, retried=False)
    assert isinstance(first[mappers.message_id("uid-404")], MessageNotFoundError)


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


# --- for the sync -----------------------------------------------------------------


async def test_the_state_changes_when_mail_arrives_or_leaves(
    server: FakePop3Server,
) -> None:
    adapter = provider(server)
    before = await adapter.folder_states()
    assert list(before) == [INBOX]
    assert await adapter.folder_states() == before
    server.add("uid-6", make_message("Mail 6"))
    arrived = await adapter.folder_states()
    del server.messages["uid-1"]
    left = await adapter.folder_states()
    assert len({before[INBOX], arrived[INBOX], left[INBOX]}) == 3


async def test_contents_and_headers(
    server: FakePop3Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pop3_module, "HEADER_BATCH", 2)
    adapter = provider(server)
    contents = await adapter.folder_contents(INBOX)
    assert contents == [mappers.message_id(f"uid-{n}") for n in range(1, 6)]
    server.calls.clear()
    headers = await adapter.message_headers([*contents, "junk"])
    assert set(headers) == set(contents)
    assert all(h and h.startswith("<") for h in headers.values())
    # Three sessions of at most two messages each.
    assert [c[0] for c in server.calls].count("quit") == 3


async def test_no_flags_to_compare(server: FakePop3Server) -> None:
    adapter = provider(server)
    assert await adapter.flag_changes(INBOX, "x", [mappers.message_id("uid-1")]) == []


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
