"""The IMAP adapter against a fake server: settings, folders, listing,
reading one message and the pure mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import anyio
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import FolderRole, MessageFilter
from benethos_mailbox_service.data.protocols.imap import (
    ImapSession,
    RawFolder,
    Server,
)
from benethos_mailbox_service.data.providers.guard import Pace
from benethos_mailbox_service.data.providers.imap import ImapProvider, mappers, watch
from benethos_mailbox_service.errors import (
    BadRequestError,
    NotFoundError,
    ProviderError,
)

from ...imap_fake import FakeFolder, FakeMailBox, make_message

SETTINGS = {"host": "imap.example.com", "username": "me@example.com"}


def filled_server() -> FakeMailBox:
    """Five messages and one with files in INBOX, beside Sent and an
    archive with a folder below it."""
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


@pytest.fixture
def server() -> FakeMailBox:
    return filled_server()


class FakeTime:
    """A clock that only moves when something sleeps or a test advances it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def provider(
    box: FakeMailBox,
    time: FakeTime | None = None,
    pace: Pace | None = None,
    watchers: anyio.CapacityLimiter | None = None,
    **overrides: Any,
) -> ImapProvider:
    def credentials(field: str) -> SecretStr:
        assert field in ("password", "access_token")
        return SecretStr("secret")

    time = time or FakeTime()
    return ImapProvider(
        {**SETTINGS, **overrides},
        credentials,
        session_factory=lambda s: ImapSession(
            s, client_factory=box, client_id=("benethos-mailbox-service", "1.0")
        ),
        clock=time.clock,
        sleep=time.sleep,
        jitter=lambda low, high: high,
        pace=pace,
        watchers=watchers,
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


async def test_folders_say_whether_they_are_subscribed(server: FakeMailBox) -> None:
    server.subscribed = {"Sent"}
    imap = provider(server)
    folders = {f.name: f for f in await imap.list_folders()}
    assert folders["Sent"].subscribed is True
    # Reported as the server has it, even for the inbox.
    assert folders["INBOX"].subscribed is False
    assert folders["2026"].subscribed is False
    # The sync asks for folder states and needs no subscriptions.
    server.calls.clear()
    await imap.folder_states()
    assert ("lsub",) not in server.calls


# --- listing ------------------------------------------------------------------


async def test_newest_first_with_cursor(server: FakeMailBox) -> None:
    imap = provider(server)
    first = await imap.list_messages(None, limit=4, cursor=None, search=None)
    assert [m.subject for m in first.items] == [
        "With files",
        "Invoice 5",
        "Hello 4",
        "Invoice 3",
    ]
    assert first.next_cursor
    second = await imap.list_messages(
        None, limit=4, cursor=first.next_cursor, search=None
    )
    assert [m.subject for m in second.items] == ["Hello 2", "Invoice 1"]
    assert second.next_cursor is None


async def test_summary_fields(server: FakeMailBox) -> None:
    page = await provider(server).list_messages(
        None, limit=10, cursor=None, search=None
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


async def test_filters(server: FakeMailBox) -> None:
    imap = provider(server)
    unread = await imap.list_messages(
        None, limit=10, cursor=None, search=MessageFilter(unread=True)
    )
    assert {m.subject for m in unread.items} == {
        "Invoice 3",
        "Hello 4",
        "Invoice 5",
        "With files",
    }
    read = await imap.list_messages(
        None, limit=10, cursor=None, search=MessageFilter(unread=False)
    )
    assert {m.subject for m in read.items} == {"Invoice 1", "Hello 2"}
    found = await imap.list_messages(
        None, limit=10, cursor=None, search=MessageFilter(text="invoice")
    )
    assert {m.subject for m in found.items} == {"Invoice 1", "Invoice 3", "Invoice 5"}


async def test_non_ascii_search_uses_utf8(server: FakeMailBox) -> None:
    await provider(server).list_messages(
        None, limit=10, cursor=None, search=MessageFilter(text="Grüße")
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
        await provider(server).list_messages(None, limit=10, cursor=cursor, search=None)


async def test_cursor_after_uidvalidity_change_is_refused(server: FakeMailBox) -> None:
    cursor = mappers.cursor("INBOX", 6, 10)
    with pytest.raises(BadRequestError, match="start again"):
        await provider(server).list_messages(None, limit=10, cursor=cursor, search=None)


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
    page = await provider(server).list_messages(None, limit=1, cursor=None, search=None)
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
    assert limiters[-1] is watch.WATCHERS
    # Everything else takes the default limiter.
    await imap.list_folders()
    assert limiters[-1] is None
