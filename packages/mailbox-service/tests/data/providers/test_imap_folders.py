"""Folders over IMAP: listed with their roles, parents and
subscriptions, the folder all, and renaming, which moves the
subscriptions of the folder and of those below it along, whether the
server does so itself or not."""

from __future__ import annotations

import imaplib
from datetime import UTC, datetime

import pytest

from benethos_mailbox_service.common import opaque
from benethos_mailbox_service.data.models import (
    FolderRole,
    MessageFilter,
    MessageUpdate,
)
from benethos_mailbox_service.data.providers import rules
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import BadRequestError

from ...imap_adapter import INBOX, provider
from ...imap_fake import FakeFolder, FakeMailBox, make_message


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
