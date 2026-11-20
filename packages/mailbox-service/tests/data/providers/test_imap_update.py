"""Changes of a message over IMAP: flags and keywords stored on the
server, the others kept, nothing written for an empty change, and an
unknown message."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import (
    MessageUpdate,
)
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import (
    NotFoundError,
)

from ...imap_fake import FakeMailBox
from .imap_adapter import provider
from .provider_helpers import update

# --- the IMAP adapter -----------------------------------------------------


async def test_update_on_the_server(server: FakeMailBox) -> None:
    imap = provider(server)
    message_id = mappers.message_id("INBOX", 7, 3)
    summary = await update(
        imap,
        message_id,
        MessageUpdate(unread=False, starred=True, keywords=["$forwarded"]),
    )
    assert summary.id == message_id
    assert (summary.unread, summary.starred) == (False, True)
    assert summary.keywords == ["$forwarded"]
    assert set(server.folders["INBOX"].messages[3][1]) == {
        "\\Seen",
        "\\Flagged",
        "$Forwarded",
    }
    # Written in a folder selected read-write, then read back without \Seen.
    assert ("select", "INBOX", False) in server.calls
    assert server.calls[-1][2] == "header"


async def test_keywords_added_on_the_server_keep_the_others(
    server: FakeMailBox,
) -> None:
    imap = provider(server)
    message_id = mappers.message_id("INBOX", 7, 3)
    await update(imap, message_id, MessageUpdate(keywords=["$forwarded", "work"]))
    summary = await update(
        imap,
        message_id,
        MessageUpdate(add_keywords=["Urgent"], remove_keywords=["$forwarded"]),
    )
    assert summary.keywords == ["Urgent", "work"]
    assert set(server.folders["INBOX"].messages[3][1]) == {"Urgent", "work"}


async def test_an_empty_update_writes_nothing(server: FakeMailBox) -> None:
    imap = provider(server)
    summary = await update(imap, mappers.message_id("INBOX", 7, 3), MessageUpdate())
    assert summary.unread is True
    assert not any(c[0] == "store" for c in server.calls)


@pytest.mark.parametrize(
    "message_id",
    [mappers.message_id("INBOX", 7, 99), mappers.message_id("INBOX", 6, 3)],
)
async def test_update_of_an_unknown_message(
    server: FakeMailBox,
    message_id: str,
) -> None:
    with pytest.raises(NotFoundError):
        await update(provider(server), message_id, MessageUpdate(starred=True))
