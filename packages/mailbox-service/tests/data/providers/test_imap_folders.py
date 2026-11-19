"""Renaming a folder over IMAP moves its subscriptions along, of the
folder and of those below it, whether the server does so itself or not."""

from __future__ import annotations

import imaplib

import pytest

from benethos_mailbox_service.data.providers.imap import mappers

from ...imap_adapter import provider
from ...imap_fake import FakeMailBox
from ...imap_fake_folders import FakeFolder


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
