"""The change feed records what the sync finds and what the API changes,
through the real IMAP adapter against a fake server."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.data.models import DraftMessage, MessageUpdate
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.data.storage import InMemoryChangeLogRepository
from benethos_mailbox_service.domain.changes import ChangeFeed
from benethos_mailbox_service.main import Services

from .conftest import ADMIN
from .imap_fake import FakeFolder, FakeMailBox, make_message
from .test_sync import account_id, ids_by_subject, server, services

__all__ = ["account_id", "server", "services"]  # fixtures

ARCHIVE = mappers.folder_id("Archive")


def recorded(services: Services, account_id: str) -> list[tuple[str, str]]:
    return [
        (e.change.type, e.change.id)
        for e in services.changes.after([account_id], 0, limit=1000)
    ]


# --- the sync ---------------------------------------------------------------------


async def test_the_first_sync_records_nothing(
    services: Services, account_id: str
) -> None:
    await services.sync.sync_account(account_id)
    assert recorded(services, account_id) == []


async def test_listing_before_the_first_sync_records_nothing(
    services: Services, account_id: str
) -> None:
    await ids_by_subject(services, account_id)
    assert recorded(services, account_id) == []


async def test_a_new_mail_found_by_the_sync(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    server.add("INBOX", 5, make_message("New"))
    await services.sync.sync_account(account_id)
    new = (await ids_by_subject(services, account_id))["New"]
    assert recorded(services, account_id) == [("message.created", new)]


async def test_a_new_mail_listed_before_the_sync_is_recorded_once(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    server.add("INBOX", 5, make_message("New"))
    new = (await ids_by_subject(services, account_id))["New"]
    await services.sync.sync_account(account_id)
    await ids_by_subject(services, account_id)
    assert recorded(services, account_id) == [("message.created", new)]


async def test_a_move_and_a_deletion_by_another_client(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    server.other_client_moves("INBOX", 1, "Archive", 5)
    del server.folders["INBOX"].messages[2]
    await services.sync.sync_account(account_id)
    assert recorded(services, account_id) == [
        ("message.updated", ids["Mail 1"]),
        ("message.deleted", ids["Mail 2"]),
    ]


async def test_a_sync_without_changes_records_nothing(
    services: Services, account_id: str
) -> None:
    await services.sync.sync_account(account_id)
    await services.sync.sync_account(account_id)
    assert recorded(services, account_id) == []


# --- through the API ----------------------------------------------------------------


async def test_flags_set_through_the_api(services: Services, account_id: str) -> None:
    ids = await ids_by_subject(services, account_id)
    await services.mailbox.update_message(
        ADMIN, account_id, ids["Mail 1"], MessageUpdate(unread=False)
    )
    assert recorded(services, account_id) == [("message.updated", ids["Mail 1"])]


async def test_our_own_move_is_recorded_once(
    services: Services, account_id: str
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    await services.mailbox.update_message(
        ADMIN, account_id, ids["Mail 2"], MessageUpdate(folder_ids=[ARCHIVE])
    )
    # The sync afterwards finds the index up to date already.
    await services.sync.sync_account(account_id)
    assert recorded(services, account_id) == [("message.updated", ids["Mail 2"])]


async def test_trash_and_delete_for_good(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    ids = await ids_by_subject(services, account_id)
    await services.mailbox.delete_message(ADMIN, account_id, ids["Mail 3"], False)
    await services.mailbox.delete_message(ADMIN, account_id, ids["Mail 3"], True)
    assert recorded(services, account_id) == [
        ("message.updated", ids["Mail 3"]),
        ("message.deleted", ids["Mail 3"]),
    ]


async def test_a_draft_written_replaced_and_deleted(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    server.folders["Drafts"] = FakeFolder(uidvalidity=3, flags=("\\Drafts",))
    await services.sync.sync_account(account_id)
    draft = await services.mailbox.create_draft(
        ADMIN, account_id, DraftMessage(subject="One", text="x")
    )
    await services.mailbox.update_draft(
        ADMIN, account_id, draft.id, DraftMessage(subject="Two", text="x")
    )
    await services.mailbox.delete_draft(ADMIN, account_id, draft.id)
    # The sync afterwards finds nothing the feed does not know yet.
    await services.sync.sync_account(account_id)
    assert recorded(services, account_id) == [
        ("message.created", draft.id),
        ("message.updated", draft.id),
        ("message.deleted", draft.id),
    ]


async def test_a_failed_change_records_nothing(
    services: Services, account_id: str
) -> None:
    with pytest.raises(Exception, match="not found"):
        await services.mailbox.update_message(
            ADMIN, account_id, "msg_" + "0" * 64, MessageUpdate(unread=False)
        )
    assert recorded(services, account_id) == []


async def test_deleting_the_account_forgets_its_changes(
    services: Services, account_id: str
) -> None:
    ids = await ids_by_subject(services, account_id)
    await services.mailbox.update_message(
        ADMIN, account_id, ids["Mail 1"], MessageUpdate(unread=False)
    )
    await services.accounts.delete(ADMIN, account_id)
    assert recorded(services, account_id) == []


# --- keeping ------------------------------------------------------------------------


def test_old_changes_are_purged_as_new_ones_come_in() -> None:
    now = datetime(2026, 9, 25, tzinfo=UTC)
    log = InMemoryChangeLogRepository()
    feed = ChangeFeed(log, days=7, clock=lambda: now)
    feed.record("acc_1", "message.created", ["msg_1"])
    now += timedelta(days=8)
    feed.record("acc_1", "message.created", ["msg_2"])
    assert [e.change.id for e in feed.after(["acc_1"], 0, limit=10)] == ["msg_2"]
    assert log.horizon() == 1


def test_purging_waits_an_hour_between_two_runs() -> None:
    t0 = datetime(2026, 9, 25, tzinfo=UTC)
    now = t0
    feed = ChangeFeed(days=1, clock=lambda: now)
    feed.record("acc_1", "message.created", ["msg_1"])
    now = t0 + timedelta(hours=23, minutes=30)
    feed.purge()  # too early for msg_1
    now = t0 + timedelta(days=1, minutes=10)
    feed.record("acc_1", "message.created", ["msg_2"])
    # Old enough, but the last purge was 40 minutes ago.
    assert [e.change.id for e in feed.after(["acc_1"], 0, limit=10)][0] == "msg_1"
    now = t0 + timedelta(days=1, minutes=31)
    feed.record("acc_1", "message.created", ["msg_3"])
    assert [e.change.id for e in feed.after(["acc_1"], 0, limit=10)] == [
        "msg_2",
        "msg_3",
    ]


def test_a_change_is_recorded_once_per_message() -> None:
    feed = ChangeFeed()
    feed.record("acc_1", "message.updated", ["msg_1", "msg_1", "msg_2"])
    assert [e.change.id for e in feed.after(["acc_1"], 0, limit=10)] == [
        "msg_1",
        "msg_2",
    ]
