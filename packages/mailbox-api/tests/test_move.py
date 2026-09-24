"""Moving a message with PATCH folder_ids: the id stays (CONCEPT 4.1, 6.3)."""

from __future__ import annotations

import pytest

from benethos_mailbox_api.data.models import MessageUpdate
from benethos_mailbox_api.data.providers.imap import mappers
from benethos_mailbox_api.data.providers.imap.client import _new_uids, _uid_set
from benethos_mailbox_api.errors import (
    BadRequestError,
    NotFoundError,
    NotSupportedError,
)

from .imap_fake import FakeMailBox
from .provider_ops import update
from .test_imap import provider, server  # noqa: F401 - the fixture

SENT = mappers.folder_id("Sent")
MESSAGE = mappers.message_id("INBOX", 7, 3)

# --- COPYUID, pure -----------------------------------------------------------


def test_uid_sets() -> None:
    assert _uid_set("3:5,9") == [3, 4, 5, 9]
    assert _uid_set("7") == [7]


@pytest.mark.parametrize(
    "reported",
    [[b"1 3 12"], [b"[COPYUID 1 2:4 11:13] Copy completed"], [b"1 4,3 13,12"]],
)
def test_new_uid_from_copyuid(reported: list[bytes]) -> None:
    assert _new_uids(reported)[3] == 12


def test_no_copyuid() -> None:
    assert _new_uids([b"Move completed"]) == {}


# --- the IMAP adapter ---------------------------------------------------------


async def test_move_with_move(server: FakeMailBox) -> None:  # noqa: F811
    summary = await update(provider(server), MESSAGE, MessageUpdate(folder_ids=[SENT]))
    assert 3 not in server.folders["INBOX"].messages
    new_uid = max(server.folders["Sent"].messages)
    assert summary.id == mappers.message_id("Sent", 1, new_uid)
    assert summary.folder_ids == [SENT]
    assert summary.subject == "Invoice 3"
    assert ("move", (3,), "Sent") in server.calls


async def test_move_with_uidplus_expunges_only_this_message(
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.announced = ["IMAP4REV1", "UIDPLUS"]
    # Another client marked a message deleted and has not expunged yet.
    raw, _ = server.folders["INBOX"].messages[4]
    server.folders["INBOX"].messages[4] = (raw, ("\\Deleted",))
    summary = await update(provider(server), MESSAGE, MessageUpdate(folder_ids=[SENT]))
    assert summary.folder_ids == [SENT]
    assert 3 not in server.folders["INBOX"].messages
    assert 4 in server.folders["INBOX"].messages
    assert ("expunge", (3,)) in server.calls


async def test_no_move_without_move_or_uidplus(server: FakeMailBox) -> None:  # noqa: F811
    server.announced = ["IMAP4REV1"]
    with pytest.raises(NotSupportedError, match="neither MOVE nor UIDPLUS"):
        await update(provider(server), MESSAGE, MessageUpdate(folder_ids=[SENT]))
    assert 3 in server.folders["INBOX"].messages


async def test_without_copyuid_found_by_message_id(server: FakeMailBox) -> None:  # noqa: F811
    server.copyuid = False
    summary = await update(provider(server), MESSAGE, MessageUpdate(folder_ids=[SENT]))
    new_uid = max(server.folders["Sent"].messages)
    assert summary.id == mappers.message_id("Sent", 1, new_uid)


async def test_flags_and_move_in_one_patch(server: FakeMailBox) -> None:  # noqa: F811
    summary = await update(
        provider(server),
        MESSAGE,
        MessageUpdate(unread=False, starred=True, folder_ids=[SENT]),
    )
    assert (summary.unread, summary.starred, summary.folder_ids) == (
        False,
        True,
        [SENT],
    )


async def test_moving_into_its_own_folder_changes_nothing(
    server: FakeMailBox,  # noqa: F811
) -> None:
    inbox = mappers.folder_id("INBOX")
    summary = await update(provider(server), MESSAGE, MessageUpdate(folder_ids=[inbox]))
    assert summary.id == MESSAGE
    assert not any(c[0] == "move" for c in server.calls)


@pytest.mark.parametrize(
    ("folder_ids", "error"),
    [
        ([SENT, mappers.folder_id("INBOX")], BadRequestError),
        ([mappers.folder_id("Nowhere")], NotFoundError),
    ],
)
async def test_bad_targets(
    server: FakeMailBox,  # noqa: F811
    folder_ids: list[str],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await update(provider(server), MESSAGE, MessageUpdate(folder_ids=folder_ids))
    assert 3 in server.folders["INBOX"].messages
