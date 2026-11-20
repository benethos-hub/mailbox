"""Folders over IMAP: listed with their roles, parents and
subscriptions, the folder all, and renaming, which moves the
subscriptions of the folder and of those below it along, whether the
server does so itself or not. Then creating, renaming and deleting, in
the personal namespace of the server."""

from __future__ import annotations

import imaplib
from datetime import UTC, datetime
from typing import Any

import pytest

from benethos_mailbox_service.common import opaque
from benethos_mailbox_service.data.models import (
    FolderRole,
    MessageFilter,
    MessageUpdate,
)
from benethos_mailbox_service.data.protocols.imap import ImapSession, Server
from benethos_mailbox_service.data.providers import rules
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)

from ...imap_fake import FakeFolder, FakeMailBox, make_message
from .imap_adapter import INBOX, provider


async def test_folders_with_roles_and_parents(server: FakeMailBox) -> None:
    folders = {f.name: f for f in await provider(server).list_folders()}
    # \Noselect is left out. Without \All the adapter shows its own.
    assert set(folders) == {"INBOX", "Sent", "2026", "All Mail"}
    assert folders["All Mail"].id == rules.ALL
    assert folders["INBOX"].role is FolderRole.INBOX
    assert folders["Sent"].role is FolderRole.SENT
    # Below a folder that is not listed: at the top, as nothing above it
    # is listed, but still Archive/2026 on the server.
    assert folders["2026"].parent_id is None
    assert mappers.folder_name(folders["2026"].id) == "Archive/2026"


async def test_all_mail_is_every_folder_but_the_trash_newest_first(
    server: FakeMailBox,
) -> None:
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    september = [
        datetime(2026, 9, day, hour, tzinfo=UTC)
        for day, hour in ((8, 10), (3, 12), (6, 10))
    ]
    server.add("Trash", 1, make_message("Gone", date=september[0]))
    server.add("Sent", 1, make_message("Sent one", date=september[1]))
    server.add("Archive/2026", 1, make_message("Filed", date=september[2]))
    imap = provider(server)
    whole = await imap.list_messages(rules.ALL, limit=10, cursor=None)
    assert whole.next_cursor is None
    assert [m.subject for m in whole.items] == [
        "Filed",
        "Invoice 5",
        "Hello 4",
        "Sent one",
        "Invoice 3",
        "Hello 2",
        "Invoice 1",
        "With files",
    ]
    # Page by page: "With files" came last but is dated oldest. Every
    # mail comes once, each page newest first.
    subjects: list[str | None] = []
    cursor = None
    for _ in range(10):
        page = await imap.list_messages(rules.ALL, limit=2, cursor=cursor)
        subjects += [m.subject for m in page.items]
        when = [m.received for m in page.items]
        assert when == sorted(
            when, key=lambda w: w.timestamp() if w else 0, reverse=True
        )
        cursor = page.next_cursor
        if cursor is None:
            break
    assert sorted(subjects, key=str) == sorted(
        (m.subject for m in whole.items), key=str
    )
    found = await imap.list_messages(
        rules.ALL, limit=10, cursor=None, search=MessageFilter(subject="Invoice")
    )
    assert [m.subject for m in found.items] == ["Invoice 5", "Invoice 3", "Invoice 1"]
    first = await imap.list_messages(rules.ALL, limit=2, cursor=None)
    with pytest.raises(BadRequestError, match="invalid cursor"):
        await imap.list_messages(INBOX, limit=2, cursor=first.next_cursor)
    [moved] = (
        await imap.update_messages(
            [found.items[0].id], MessageUpdate(folder_ids=[rules.ALL])
        )
    ).values()
    assert isinstance(moved, BadRequestError)


@pytest.mark.parametrize(
    ("places", "subjects"),
    [
        ({"INBOX": [7, 3]}, ["Hello 2", "Invoice 1"]),
        ({}, []),
    ],
)
async def test_a_cursor_of_all_as_it_was_written_reads(
    server: FakeMailBox, places: dict[str, list[int]], subjects: list[str]
) -> None:
    """Per folder with hits left its UIDVALIDITY and the UID below which
    its next page looks: a cursor handed out before still reads."""
    scope = rules.cursor_scope(rules.ALL, MessageFilter())
    cursor = opaque.encode("a_", [scope, places])
    page = await provider(server).list_messages(rules.ALL, limit=10, cursor=cursor)
    assert [m.subject for m in page.items] == subjects


@pytest.mark.parametrize(
    "value",
    [
        ["other scope", {}],
        ["SCOPE", {"INBOX": [7]}],
        ["SCOPE", {"INBOX": [7, -1]}],
        ["SCOPE", {"INBOX": [True, 3]}],
        ["SCOPE", []],
        "SCOPE",
    ],
)
async def test_a_cursor_of_all_made_up_is_refused(
    server: FakeMailBox, value: object
) -> None:
    scope = rules.cursor_scope(rules.ALL, MessageFilter())
    if isinstance(value, list) and value[0] == "SCOPE":
        value = [scope, value[1]]
    with pytest.raises(BadRequestError, match="invalid cursor"):
        await provider(server).list_messages(
            rules.ALL, limit=10, cursor=opaque.encode("a_", value)
        )


async def test_a_server_with_all_shows_its_own(server: FakeMailBox) -> None:
    server.folders["All"] = FakeFolder(flags=("\\All",))
    folders = await provider(server).list_folders()
    [everything] = [f for f in folders if f.role is FolderRole.ALL]
    assert everything.id != rules.ALL


async def test_a_folder_below_an_unlisted_one_is_renamed_in_place(
    server: FakeMailBox,
) -> None:
    imap = provider(server)
    year = mappers.folder_id("Archive/2026")
    renamed = await imap.update_folder(year, "2025", None)
    assert "Archive/2025" in server.folders and renamed.parent_id is None
    # Moved when it is asked to go below another folder.
    inbox = mappers.folder_id("INBOX")
    moved = await imap.update_folder(renamed.id, "2025", inbox)
    assert "INBOX/2025" in server.folders and moved.parent_id == inbox


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


async def test_a_rename_answers_where_the_server_moves_the_subscription(
    server: FakeMailBox,
) -> None:
    """Stalwart moves it with the RENAME and refuses the second SUBSCRIBE:
    the folder is renamed all the same."""
    server.moves_subscriptions = True
    server.subscribed = {"Archive/2026"}
    renamed = await provider(server).update_folder(
        mappers.folder_id("Archive/2026"), "2025", None
    )
    assert renamed.id == mappers.folder_id("Archive/2025")
    assert server.subscribed == {"Archive/2025"}


async def test_a_rename_moves_the_subscription_where_the_server_does_not(
    server: FakeMailBox,
) -> None:
    server.subscribed = {"Archive/2026"}
    await provider(server).update_folder(
        mappers.folder_id("Archive/2026"), "2025", None
    )
    assert server.subscribed == {"Archive/2025"}


@pytest.mark.parametrize("moves", [False, True])
async def test_a_rename_moves_the_subscriptions_below_the_folder(
    server: FakeMailBox, moves: bool
) -> None:
    """RENAME takes the folders below along. Their subscriptions follow,
    so a mail client that shows only subscribed folders still shows them."""
    server.moves_subscriptions = moves
    for name in ("Projects", "Projects/A", "Projects/A/2026", "Projects2"):
        server.folders[name] = FakeFolder()
    server.subscribed = {"Projects", "Projects/A", "Projects/A/2026", "Projects2"}
    await provider(server).update_folder(mappers.folder_id("Projects"), "Work", None)
    assert server.subscribed == {"Work", "Work/A", "Work/A/2026", "Projects2"}


async def test_a_rename_without_lsub_moves_the_folder_s_own_subscription(
    server: FakeMailBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folders below keep their old subscriptions then, as before."""
    every = server.list_sub_folders

    def refused(directory: str = "", pattern: str = "*") -> object:
        if pattern != "*":
            raise imaplib.IMAP4.error("lsub failed")
        return every()

    monkeypatch.setattr(server, "list_sub_folders", refused)
    server.subscribed = {"Archive/2026"}
    await provider(server).update_folder(
        mappers.folder_id("Archive/2026"), "2025", None
    )
    assert server.subscribed == {"Archive/2025"}


# --- creating, renaming and deleting --------------------------------------------


@pytest.fixture
def below_inbox() -> FakeMailBox:
    """A server that keeps every folder below the inbox, with "." between."""
    box = FakeMailBox()
    box.delimiter = "."
    box.namespace_prefix = "INBOX."
    box.announced = [*box.announced, "NAMESPACE"]
    box.folders = {"INBOX": FakeFolder(), "INBOX.Sent": FakeFolder(flags=("\\Sent",))}
    return box


async def test_a_new_folder_goes_into_the_personal_namespace(
    below_inbox: FakeMailBox,
) -> None:
    folder = await provider(below_inbox).create_folder("Projekte", None)
    assert "INBOX.Projekte" in below_inbox.folders
    assert folder.id == mappers.folder_id("INBOX.Projekte")
    assert (folder.name, folder.subscribed) == ("Projekte", True)


async def test_a_retried_step_counts_its_own_work_as_done(
    below_inbox: FakeMailBox,
) -> None:
    imap = provider(below_inbox)
    below_inbox.lose_the_reply("create_folder")
    made = await imap.create_folder("Projekte", None)
    assert made.name == "Projekte"
    below_inbox.lose_the_reply("rename_folder")
    renamed = await imap.update_folder(made.id, "Archiv", None)
    assert renamed.name == "Archiv"
    below_inbox.lose_the_reply("delete_folder")
    await imap.delete_folder(renamed.id)
    assert "INBOX.Archiv" not in below_inbox.folders
    # Without a retry, the same finding is a conflict.
    await imap.create_folder("Kunden", None)
    with pytest.raises(ConflictError):
        await imap.create_folder("Kunden", None)


async def test_the_folders_below_the_namespace_are_at_the_top(
    below_inbox: FakeMailBox,
) -> None:
    """As mail clients show them: INBOX.Sent is no subfolder of the inbox.
    A folder below one of them stays its subfolder."""
    imap = provider(below_inbox)
    kunden = await imap.create_folder("Kunden", None)
    await imap.create_folder("2026", kunden.id)
    folders = {f.name: f for f in await imap.list_folders()}
    assert folders["INBOX"].parent_id is None
    assert folders["Sent"].parent_id is None
    assert folders["Kunden"].parent_id is None
    assert folders["2026"].parent_id == kunden.id


async def test_without_a_namespace_a_folder_below_the_inbox_stays_there() -> None:
    box = FakeMailBox()
    box.delimiter = "."
    box.folders = {"INBOX": FakeFolder(), "INBOX.Bills": FakeFolder()}
    folders = {f.name: f for f in await provider(box).list_folders()}
    assert folders["Bills"].parent_id == mappers.folder_id("INBOX")


async def test_the_namespace_is_asked_once_per_connection(
    below_inbox: FakeMailBox,
) -> None:
    imap = provider(below_inbox)
    asked = []
    original = below_inbox.namespace

    def counted() -> Any:
        asked.append(1)
        return original()

    below_inbox.namespace = counted  # type: ignore[method-assign]
    await imap.list_folders()
    await imap.list_folders()
    assert len(asked) == 1


async def test_a_subfolder(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    parent = await imap.create_folder("Kunden", None)
    child = await imap.create_folder("Müller GmbH", parent.id)
    assert "INBOX.Kunden.Müller GmbH" in below_inbox.folders
    assert child.parent_id == parent.id


@pytest.mark.parametrize(
    ("name", "parent", "error"),
    [
        ("a.b", None, BadRequestError),
        ("Sent", mappers.folder_id("INBOX"), ConflictError),
        ("New", mappers.folder_id("INBOX.Nowhere"), NotFoundError),
    ],
)
async def test_folders_that_cannot_be_made(
    below_inbox: FakeMailBox, name: str, parent: str | None, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await provider(below_inbox).create_folder(name, parent)


async def test_rename_moves_the_subscription(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    folder = await imap.create_folder("Alt", None)
    renamed = await imap.update_folder(folder.id, "Neu", None)
    assert renamed.id == mappers.folder_id("INBOX.Neu")
    assert renamed.subscribed is True
    assert "INBOX.Alt" not in below_inbox.subscribed


async def test_a_folder_cannot_move_into_itself(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    outer = await imap.create_folder("Outer", None)
    inner = await imap.create_folder("Inner", outer.id)
    with pytest.raises(BadRequestError, match="into itself"):
        await imap.update_folder(outer.id, "Outer", inner.id)


async def test_delete_drops_the_subscription(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    folder = await imap.create_folder("Weg", None)
    await imap.delete_folder(folder.id)
    assert "INBOX.Weg" not in below_inbox.folders
    assert "INBOX.Weg" not in below_inbox.subscribed


async def test_without_namespace_at_the_top(server: FakeMailBox) -> None:
    await provider(server).create_folder("Projekte", None)
    assert "Projekte" in server.folders


def test_a_folder_that_is_gone_is_not_found() -> None:
    box = FakeMailBox()
    session = ImapSession(Server("imap.example.com", 993, "tls"), client_factory=box)
    session.login("me@example.com", "secret")
    with pytest.raises(NotFoundError):
        session.select("Renamed by someone else")
