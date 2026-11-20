"""The IMAP adapter against a fake server: settings, listing, reading
one message and the pure mappers. Its folders: test_imap_folders.py."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import anyio
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import (
    MessageFilter,
)
from benethos_mailbox_service.data.protocols.imap import (
    ImapSession,
    RawFolder,
    Server,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider, changes, mappers
from benethos_mailbox_service.errors import (
    BadRequestError,
    NotFoundError,
    ProviderError,
)

from ...imap_fake import FakeMailBox, make_message
from .imap_adapter import INBOX, SETTINGS, provider

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


# --- listing ------------------------------------------------------------------


async def test_newest_first_with_cursor(server: FakeMailBox) -> None:
    imap = provider(server)
    first = await imap.list_messages(INBOX, limit=4, cursor=None, search=None)
    assert [m.subject for m in first.items] == [
        "With files",
        "Invoice 5",
        "Hello 4",
        "Invoice 3",
    ]
    assert first.next_cursor
    second = await imap.list_messages(
        INBOX, limit=4, cursor=first.next_cursor, search=None
    )
    assert [m.subject for m in second.items] == ["Hello 2", "Invoice 1"]
    assert second.next_cursor is None


async def test_summary_fields(server: FakeMailBox) -> None:
    page = await provider(server).list_messages(
        INBOX, limit=10, cursor=None, search=None
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
    assert ("fetch", ("9", "5", "4", "3", "2", "1"), "header") in server.calls


async def test_date_is_the_header_and_received_the_internal_date(
    server: FakeMailBox,
) -> None:
    arrived = datetime(2026, 9, 2, 8, 30, tzinfo=UTC)
    server.arrivals[("INBOX", 1)] = arrived
    adapter = provider(server)
    page = await adapter.list_messages(INBOX, limit=10, cursor=None, search=None)
    oldest = page.items[-1]
    assert oldest.date == datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    assert oldest.received == arrived
    assert (await adapter.get_message(oldest.id)).received == arrived


async def test_filters(server: FakeMailBox) -> None:
    imap = provider(server)
    unread = await imap.list_messages(
        INBOX, limit=10, cursor=None, search=MessageFilter(unread=True)
    )
    assert {m.subject for m in unread.items} == {
        "Invoice 3",
        "Hello 4",
        "Invoice 5",
        "With files",
    }
    read = await imap.list_messages(
        INBOX, limit=10, cursor=None, search=MessageFilter(unread=False)
    )
    assert {m.subject for m in read.items} == {"Invoice 1", "Hello 2"}
    found = await imap.list_messages(
        INBOX, limit=10, cursor=None, search=MessageFilter(text="invoice")
    )
    assert {m.subject for m in found.items} == {"Invoice 1", "Invoice 3", "Invoice 5"}


async def test_non_ascii_search_uses_utf8(server: FakeMailBox) -> None:
    await provider(server).list_messages(
        INBOX, limit=10, cursor=None, search=MessageFilter(text="Grüße")
    )
    assert any(c[0] == "search" and c[2] == "UTF-8" for c in server.calls)


async def test_other_folder_and_selected_read_only(server: FakeMailBox) -> None:
    server.add("Sent", 1, make_message("Sent one"))
    page = await provider(server).list_messages(
        mappers.folder_id("Sent"), limit=10, cursor=None, search=None
    )
    assert [m.subject for m in page.items] == ["Sent one"]
    assert ("select", "Sent", True) in server.calls


async def test_cursor_of_another_folder_is_refused(server: FakeMailBox) -> None:
    cursor = mappers.cursor("Sent", 1, 10)
    with pytest.raises(BadRequestError, match="^invalid cursor$"):
        await provider(server).list_messages(
            INBOX, limit=10, cursor=cursor, search=None
        )


async def test_cursor_after_uidvalidity_change_is_refused(server: FakeMailBox) -> None:
    cursor = mappers.cursor("INBOX", 6, 10)
    with pytest.raises(BadRequestError, match="start again"):
        await provider(server).list_messages(
            INBOX, limit=10, cursor=cursor, search=None
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


async def test_a_message_too_large_is_refused(server: FakeMailBox) -> None:
    imap = ImapProvider(
        SETTINGS,
        lambda field: SecretStr("secret"),
        session_factory=lambda s: ImapSession(s, client_factory=server, max_bytes=500),
    )
    small = mappers.message_id("INBOX", 7, 1)
    assert len(await imap.get_raw(small)) <= 500
    large = mappers.message_id("INBOX", 7, 9)
    with pytest.raises(ProviderError, match="larger than 500 bytes"):
        await imap.get_message(large)
    with pytest.raises(ProviderError, match="larger than 500 bytes"):
        await imap.get_raw(large)


async def test_a_huge_header_is_cut_off(server: FakeMailBox) -> None:
    padding = {"X-Padding": "x" * 300_000}
    server.add("INBOX", 10, make_message("Padded", extra_headers=padding))
    page = await provider(server).list_messages(
        INBOX, limit=1, cursor=None, search=None
    )
    assert page.items[0].subject == "Padded"


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


# --- pure mappers ---------------------------------------------------------------


def test_ids_round_trip_and_are_opaque() -> None:
    value = mappers.message_id("Entwürfe/2026", 3, 42)
    assert value.startswith("m_")
    assert "/" not in value
    assert mappers.parse_message_id(value) == mappers.Place("Entwürfe/2026", 3, 42)
    assert mappers.folder_name(mappers.folder_id("Entwürfe")) == "Entwürfe"
    with pytest.raises(NotFoundError):
        mappers.folder_name(mappers.message_id("x", 1, 1))
    with pytest.raises(NotFoundError):
        mappers.parse_message_id(mappers.folder_id("x"))
    # A cursor is a request parameter, not a resource: bad request.
    with pytest.raises(BadRequestError, match="invalid cursor"):
        mappers.parse_cursor(mappers.folder_id("x"))


@pytest.mark.parametrize("end", ["\r\n", "\n", "\x00", "\t", "\x7f"])
def test_an_id_naming_a_folder_no_server_has_is_not_one(end: str) -> None:
    name = f'INBOX"{end}Z99 DELETE "Important'
    with pytest.raises(NotFoundError):
        mappers.folder_name(mappers.folder_id(name))
    with pytest.raises(NotFoundError):
        mappers.parse_message_id(mappers.message_id(name, 1, 1))
    with pytest.raises(BadRequestError, match="invalid cursor"):
        mappers.parse_cursor(mappers.cursor(name, 1, 1))


def test_an_id_naming_a_folder_with_spaces_and_wildcards_is_one() -> None:
    name = "Rechnungen für 2026 *%"
    assert mappers.folder_name(mappers.folder_id(name)) == name
    assert mappers.parse_message_id(mappers.message_id(name, 1, 1)).folder == name
    assert mappers.parse_cursor(mappers.cursor(name, 1, 1)).folder == name


def test_flat_folder_without_delimiter() -> None:
    folder = mappers.folder(RawFolder("Notes", None, ()))
    assert folder is not None
    assert folder.parent_id is None
    assert folder.role is None


def test_logout_without_connection_is_harmless() -> None:
    session = ImapSession(Server("h", 993, "tls"))
    session.logout()
    with pytest.raises(ProviderError, match="not connected"):
        session.folders.list_folders()


async def test_a_wait_in_idle_takes_no_thread_of_the_pool(
    server: FakeMailBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wait runs under the watchers' limiter, never the default one
    that answers requests and runs every other command."""
    limiters: list[object] = []
    run_sync = anyio.to_thread.run_sync

    async def noted(function: Any, *args: Any, **kwargs: Any) -> Any:
        limiters.append(kwargs.get("limiter"))
        return await run_sync(function, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", noted)
    server.idle_script = [[(5, b"EXISTS")]]
    watchers = anyio.CapacityLimiter(1)
    imap = provider(server, watchers=watchers)
    assert await imap.wait_for_change(5) is True
    assert limiters[-1] is watchers
    server.idle_script = [[(5, b"EXISTS")]]
    imap = provider(server)
    assert await imap.wait_for_change(5) is True
    assert limiters[-1] is changes.WATCHERS
    # Everything else takes the default limiter.
    await imap.list_folders()
    assert limiters[-1] is None


async def test_the_sender_check_reads_the_entry_of_the_own_server(
    server: FakeMailBox,
) -> None:
    entry = "mx.example.org; dmarc=pass header.from=example.com"
    headers = {"Authentication-Results": entry}
    server.add("INBOX", 10, make_message("Checked", extra_headers=headers))
    imap = provider(server, authserv_id="mx.example.org")
    page = await imap.list_messages(INBOX, limit=1, cursor=None, search=None)
    listed = page.items[0]
    assert listed.sender_check.result == "pass"
    assert listed.sender_check.domain == "example.com"
    whole = await imap.get_message(listed.id)
    assert whole.sender_check == listed.sender_check
    # Without the name of its receiving server the account cannot tell.
    plain = await provider(server).list_messages(
        INBOX, limit=1, cursor=None, search=None
    )
    assert plain.items[0].sender_check.reason == "account"
