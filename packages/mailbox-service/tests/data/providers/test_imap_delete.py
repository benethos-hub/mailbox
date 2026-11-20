"""Deleting over IMAP: into the trash, or for good where the server has
UIDPLUS, and what a lost connection had already done."""

from __future__ import annotations

from typing import Any

import pytest

from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import (
    ConflictError,
    NotSupportedError,
    ProviderUnavailableError,
)

from ...imap_adapter import provider
from ...imap_fake import FakeFolder, FakeMailBox, make_message
from ...provider_helpers import delete

MESSAGE = mappers.message_id("INBOX", 7, 3)


@pytest.fixture
def with_trash(server: FakeMailBox) -> FakeMailBox:
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    return server


# --- the IMAP adapter -----------------------------------------------------------


async def test_into_the_trash(with_trash: FakeMailBox) -> None:
    trashed = await delete(provider(with_trash), MESSAGE, permanent=False)
    assert trashed is not None
    assert trashed.folder_ids == [mappers.folder_id("Trash")]
    assert trashed.subject == "Invoice 3"
    assert 3 not in with_trash.folders["INBOX"].messages
    assert len(with_trash.folders["Trash"].messages) == 1


async def test_from_the_trash_only_for_good(with_trash: FakeMailBox) -> None:
    imap = provider(with_trash)
    trashed = await delete(imap, MESSAGE, permanent=False)
    assert trashed is not None
    with pytest.raises(ConflictError, match="in the trash already"):
        await delete(imap, trashed.id, permanent=False)
    assert await delete(imap, trashed.id, permanent=True) is None
    assert with_trash.folders["Trash"].messages == {}


async def test_a_retried_deletion_that_went_through_is_done(
    server: FakeMailBox,
) -> None:
    server.lose_the_reply("uid_expunge")
    assert await delete(provider(server), MESSAGE, permanent=True) is None
    assert 3 not in server.folders["INBOX"].messages


async def test_no_trash_no_deletion(server: FakeMailBox) -> None:
    with pytest.raises(NotSupportedError, match="no trash folder"):
        await delete(provider(server), MESSAGE, permanent=False)
    assert 3 in server.folders["INBOX"].messages


async def test_for_good_only_this_message(server: FakeMailBox) -> None:
    # Another client marked a message deleted and has not expunged yet.
    raw, _ = server.folders["INBOX"].messages[4]
    server.folders["INBOX"].messages[4] = (raw, ("\\Deleted",))
    assert await delete(provider(server), MESSAGE, permanent=True) is None
    assert 3 not in server.folders["INBOX"].messages
    assert 4 in server.folders["INBOX"].messages
    assert ("expunge", (3,)) in server.calls


async def test_a_lost_connection_names_what_was_done(
    server: FakeMailBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second folder's step finds the server gone: the first folder's
    message is deleted, and the answer says so beside the failure."""
    server.add("Sent", 1, make_message("Sent mail"))
    imap = provider(server)
    sent = mappers.message_id("Sent", server.folders["Sent"].uidvalidity, 1)
    real, calls = imap._run, []

    async def run(operation: Any) -> Any:
        calls.append(operation)
        if len(calls) > 1:
            raise ProviderUnavailableError("the mail server is not reachable")
        return await real(operation)

    monkeypatch.setattr(imap, "_run", run)
    done = await imap.delete_messages([MESSAGE, sent], permanent=True)
    assert done[MESSAGE] is None and 3 not in server.folders["INBOX"].messages
    assert isinstance(done[sent], ProviderUnavailableError)
    # Nothing done yet: the failure is the call's, as before.
    calls.append("first")
    with pytest.raises(ProviderUnavailableError):
        await imap.delete_messages([sent], permanent=True)


async def test_for_good_needs_uidplus(server: FakeMailBox) -> None:
    server.announced = ["IMAP4REV1", "MOVE"]
    with pytest.raises(NotSupportedError, match="UIDPLUS"):
        await delete(provider(server), MESSAGE, permanent=True)
    assert 3 in server.folders["INBOX"].messages
