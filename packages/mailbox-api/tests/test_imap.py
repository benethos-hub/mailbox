from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

from benethos_mailbox_api.data.models import FolderRole
from benethos_mailbox_api.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_api.data.providers.imap.client import (
    ImapServer,
    ImapSession,
    RawFolder,
)
from benethos_mailbox_api.errors import (
    BadRequestError,
    NotFoundError,
    ProviderAuthError,
    ProviderError,
)

from .imap_fake import FakeFolder, FakeMailBox, make_message

SETTINGS = {"host": "imap.example.com", "username": "me@example.com"}


@pytest.fixture
def server() -> FakeMailBox:
    box = FakeMailBox()
    box.folders = {
        "INBOX": FakeFolder(uidvalidity=7),
        "Sent": FakeFolder(flags=("\\HasNoChildren", "\\Sent")),
        "Archive": FakeFolder(flags=("\\Noselect",)),
        "Archive/2026": FakeFolder(),
    }
    for uid in range(1, 6):
        box.add(
            "INBOX",
            uid,
            make_message(
                f"Invoice {uid}" if uid % 2 else f"Hello {uid}",
                date=datetime(2026, 9, uid, 10, 0, tzinfo=UTC),
            ),
            flags=("\\Seen",) if uid < 3 else (),
        )
    box.add(
        "INBOX",
        9,
        make_message(
            "With files",
            html="<p>Hello</p>",
            attachments=[("report.pdf", "application/pdf", b"%PDF-1.7 data")],
        ),
        flags=("\\Flagged",),
    )
    return box


def provider(box: FakeMailBox, **overrides: Any) -> ImapProvider:
    def credentials(field: str) -> SecretStr:
        assert field in ("password", "access_token")
        return SecretStr("secret")

    return ImapProvider(
        {**SETTINGS, **overrides},
        credentials,
        session_factory=lambda s: ImapSession(s, mailbox_factory=box),
    )


# --- settings -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"username": "u"}, "settings.host"),
        ({"host": "h"}, "settings.username"),
        ({**SETTINGS, "security": "none"}, "without encryption"),
        ({**SETTINGS, "auth": "cram-md5"}, "settings.auth"),
    ],
)
def test_invalid_settings(settings: dict[str, str], message: str) -> None:
    with pytest.raises(BadRequestError, match=message):
        ImapProvider(settings, lambda f: SecretStr("x"))


async def test_default_ports(server: FakeMailBox) -> None:
    await provider(server).list_folders()
    assert ("connect", "imap.example.com", 993, "tls") in server.calls
    await provider(server, security="starttls").list_folders()
    assert ("connect", "imap.example.com", 143, "starttls") in server.calls
    await provider(server, port=1993).list_folders()
    assert ("connect", "imap.example.com", 1993, "tls") in server.calls


# --- folders ------------------------------------------------------------------


async def test_folders_with_roles_and_parents(server: FakeMailBox) -> None:
    folders = {f.name: f for f in await provider(server).list_folders()}
    assert set(folders) == {"INBOX", "Sent", "2026"}  # \Noselect is left out
    assert folders["INBOX"].role is FolderRole.INBOX
    assert folders["Sent"].role is FolderRole.SENT
    assert folders["2026"].parent_id == mappers.folder_id("Archive")
    assert mappers.folder_name(folders["2026"].id) == "Archive/2026"


# --- listing ------------------------------------------------------------------


async def test_newest_first_with_cursor(server: FakeMailBox) -> None:
    imap = provider(server)
    first = await imap.list_messages(
        None, limit=4, cursor=None, query=None, unread=None
    )
    assert [m.subject for m in first.items] == [
        "With files",
        "Invoice 5",
        "Hello 4",
        "Invoice 3",
    ]
    assert first.next_cursor
    second = await imap.list_messages(
        None, limit=4, cursor=first.next_cursor, query=None, unread=None
    )
    assert [m.subject for m in second.items] == ["Hello 2", "Invoice 1"]
    assert second.next_cursor is None


async def test_summary_fields(server: FakeMailBox) -> None:
    page = await provider(server).list_messages(
        None, limit=10, cursor=None, query=None, unread=None
    )
    files = page.items[0]
    assert files.starred is True
    assert files.unread is True
    assert files.has_attachments is True
    assert files.sender is not None
    assert files.sender.email == "alice@example.com"
    assert files.sender.name == "Alice Example"
    oldest = page.items[-1]
    assert oldest.unread is False
    assert oldest.date == datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    # Headers only, and never marking anything read.
    assert ("fetch", ("9", "5", "4", "3", "2", "1"), True) in server.calls


async def test_filters(server: FakeMailBox) -> None:
    imap = provider(server)
    unread = await imap.list_messages(
        None, limit=10, cursor=None, query=None, unread=True
    )
    assert {m.subject for m in unread.items} == {
        "Invoice 3",
        "Hello 4",
        "Invoice 5",
        "With files",
    }
    read = await imap.list_messages(
        None, limit=10, cursor=None, query=None, unread=False
    )
    assert {m.subject for m in read.items} == {"Invoice 1", "Hello 2"}
    found = await imap.list_messages(
        None, limit=10, cursor=None, query="invoice", unread=None
    )
    assert {m.subject for m in found.items} == {"Invoice 1", "Invoice 3", "Invoice 5"}


async def test_non_ascii_search_uses_utf8(server: FakeMailBox) -> None:
    await provider(server).list_messages(
        None, limit=10, cursor=None, query="Grüße", unread=None
    )
    assert any(c[0] == "search" and c[2] == "UTF-8" for c in server.calls)


async def test_other_folder_and_selected_read_only(server: FakeMailBox) -> None:
    server.add("Sent", 1, make_message("Sent one"))
    page = await provider(server).list_messages(
        mappers.folder_id("Sent"), limit=10, cursor=None, query=None, unread=None
    )
    assert [m.subject for m in page.items] == ["Sent one"]
    assert ("select", "Sent", True) in server.calls


async def test_cursor_of_another_folder_is_refused(server: FakeMailBox) -> None:
    cursor = mappers.cursor("Sent", 1, 10)
    with pytest.raises(BadRequestError, match="another folder"):
        await provider(server).list_messages(
            None, limit=10, cursor=cursor, query=None, unread=None
        )


async def test_cursor_after_uidvalidity_change_is_refused(server: FakeMailBox) -> None:
    cursor = mappers.cursor("INBOX", 6, 10)
    with pytest.raises(BadRequestError, match="start again"):
        await provider(server).list_messages(
            None, limit=10, cursor=cursor, query=None, unread=None
        )


# --- one message ----------------------------------------------------------------


async def test_get_message(server: FakeMailBox) -> None:
    imap = provider(server)
    message = await imap.get_message(mappers.message_id("INBOX", 7, 9))
    assert message.subject == "With files"
    assert message.text_body is not None and "Hello" in message.text_body
    assert message.html_body == "<p>Hello</p>\n"
    assert message.message_id_header is not None
    assert [(a.id, a.filename, a.content_type) for a in message.attachments] == [
        ("att_0", "report.pdf", "application/pdf")
    ]


async def test_get_attachment_and_raw(server: FakeMailBox) -> None:
    imap = provider(server)
    message_id = mappers.message_id("INBOX", 7, 9)
    attachment = await imap.get_attachment(message_id, "att_0")
    assert attachment.data == b"%PDF-1.7 data"
    assert attachment.filename == "report.pdf"
    raw = await imap.get_raw(message_id)
    assert b"Subject: With files" in raw
    with pytest.raises(NotFoundError):
        await imap.get_attachment(message_id, "att_5")
    with pytest.raises(NotFoundError):
        await imap.get_attachment(message_id, "nonsense")


@pytest.mark.parametrize(
    "message_id",
    [
        mappers.message_id("INBOX", 6, 9),  # old UIDVALIDITY
        mappers.message_id("INBOX", 7, 99),  # gone
        "m_not-base64!",
        "nonsense",
        mappers.folder_id("INBOX"),
    ],
)
async def test_unknown_messages(server: FakeMailBox, message_id: str) -> None:
    imap = provider(server)
    with pytest.raises(NotFoundError):
        await imap.get_message(message_id)
    with pytest.raises(NotFoundError):
        await imap.get_raw(message_id)


# --- login and connection -------------------------------------------------------


async def test_one_login_for_many_calls(server: FakeMailBox) -> None:
    imap = provider(server)
    await imap.list_folders()
    await imap.list_messages(None, limit=1, cursor=None, query=None, unread=None)
    assert server.logins == 1
    await imap.close()
    assert ("logout",) in server.calls


async def test_wrong_password(server: FakeMailBox) -> None:
    server.password = "other"
    with pytest.raises(ProviderAuthError):
        await provider(server).list_folders()


async def test_xoauth2(server: FakeMailBox) -> None:
    await provider(server, auth="xoauth2").list_folders()
    assert ("xoauth2", "me@example.com") in server.calls


async def test_a_broken_connection_is_reopened(server: FakeMailBox) -> None:
    imap = provider(server)
    await imap.list_folders()
    server.fail_next = OSError("connection reset")
    with pytest.raises(ProviderError, match="not reachable"):
        await imap.list_messages(None, limit=1, cursor=None, query=None, unread=None)
    await imap.list_messages(None, limit=1, cursor=None, query=None, unread=None)
    assert server.logins == 2


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (TimeoutError(), "did not answer"),
        (__import__("ssl").SSLError("bad cert"), "TLS"),
        (__import__("imaplib").IMAP4.error("BAD"), "answered with an error"),
    ],
)
async def test_errors_are_translated(
    server: FakeMailBox, error: Exception, message: str
) -> None:
    imap = provider(server)
    server.fail_next = error
    with pytest.raises(ProviderError, match=message):
        await imap.list_messages(None, limit=1, cursor=None, query=None, unread=None)


# --- pure mappers ---------------------------------------------------------------


def test_ids_round_trip_and_are_opaque() -> None:
    value = mappers.message_id("Entwürfe/2026", 3, 42)
    assert value.startswith("m_")
    assert "/" not in value
    assert mappers.parse_message_id(value) == ("Entwürfe/2026", 3, 42)
    assert mappers.folder_name(mappers.folder_id("Entwürfe")) == "Entwürfe"
    with pytest.raises(NotFoundError):
        mappers.folder_name(mappers.message_id("x", 1, 1))
    with pytest.raises(NotFoundError):
        mappers.parse_message_id(mappers.folder_id("x"))
    with pytest.raises(NotFoundError):
        mappers.parse_cursor(mappers.folder_id("x"))


def test_flat_folder_without_delimiter() -> None:
    folder = mappers.to_folder(RawFolder("Notes", None, ()))
    assert folder is not None
    assert folder.parent_id is None
    assert folder.role is None


def test_logout_without_connection_is_harmless() -> None:
    session = ImapSession(ImapServer("h", 993, "tls"))
    session.logout()
    with pytest.raises(ProviderError, match="not connected"):
        session.list_folders()
