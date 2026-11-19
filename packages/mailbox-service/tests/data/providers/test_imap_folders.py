"""Renaming a folder over IMAP moves its subscription along, whether the
server does so itself or not."""

from __future__ import annotations

from benethos_mailbox_service.data.providers.imap import mappers

from ...imap_adapter import provider
from ...imap_fake import FakeMailBox


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
