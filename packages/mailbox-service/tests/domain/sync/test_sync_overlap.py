"""A sync pass and a change of ours at the same time: the pass never
writes a view into the index that the change made old."""

from __future__ import annotations

import logging

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    DraftMessage,
    MessageBatch,
    MessageUpdate,
)
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import NotFoundError

from ...conftest import ADMIN
from ...imap_fake import FakeFolder, FakeMailBox, make_message
from ..sync_helpers import ids_by_subject, recorded

FOLDERS = [mappers.folder_id("INBOX"), mappers.folder_id("Archive")]


@pytest.mark.parametrize("target", ["Archive", "INBOX"])
async def test_a_move_of_ours_during_a_pass_keeps_the_index_true(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    moved = (await ids_by_subject(services, account))["Mail 1"]
    if target == "INBOX":
        # The mail starts in the other folder, known to the index there.
        await services.mailbox.update_message(
            ADMIN, account, moved, MessageUpdate(folder_ids=[FOLDERS[1]])
        )
        await services.sync.sync_account(account)
    # Another client changes both folders, so the next pass reads both.
    imap_server.other_client_moves("INBOX", 4, "Archive", 40)
    adapter = services.adapters.get(account)
    real = adapter.folder_contents
    reads: list[str] = []

    async def contents(folder_id: str) -> list[str]:
        reads.append(folder_id)
        if len(reads) == 2:
            # Between the two folders the pass reads, the caller moves a mail.
            answer = await services.mailbox.update_message(
                ADMIN,
                account,
                moved,
                MessageUpdate(folder_ids=[mappers.folder_id(target)]),
            )
            assert answer.id == moved
        return await real(folder_id)

    monkeypatch.setattr(adapter, "folder_contents", contents)
    await services.sync.sync_account(account)
    monkeypatch.setattr(adapter, "folder_contents", real)

    on_server = {n for f in FOLDERS for n in await real(f)}
    entries = services.index.in_folders(account, FOLDERS)
    ghosts = [e for e in entries if e.native_id not in on_server]
    assert not ghosts, "the index names a place where no message is"
    assert moved in {e.id for e in entries}, "the id of the moved message is gone"
    told = [(kind, f) for kind, i, f in recorded(services, account) if i == moved]
    assert ("message.deleted", FOLDERS[0]) not in told
    assert ("message.deleted", FOLDERS[1]) not in told
    message = await services.mailbox.get_message(ADMIN, account, moved)
    assert message.folder_ids == [mappers.folder_id(target)]


async def test_a_pass_while_a_change_runs_applies_nothing(
    imap_services: Services,
    imap_account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server has moved the mail, the index does not follow yet."""
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    moved = (await ids_by_subject(services, account))["Mail 1"]
    before = services.index.in_folders(account, FOLDERS)
    states = services.index.folder_states(account)
    adapter = services.adapters.get(account)
    real = adapter.update_messages

    async def update(natives: list[str], changes: MessageUpdate) -> object:
        done = await real(natives, changes)
        await services.sync.sync_account(account)
        # Every attempt of the pass was overtaken: nothing applied, and the
        # folder states not kept for the next pass.
        assert services.index.in_folders(account, FOLDERS) == before
        assert services.index.folder_states(account) == states
        return done

    monkeypatch.setattr(adapter, "update_messages", update)
    answer = await services.mailbox.update_message(
        ADMIN, account, moved, MessageUpdate(folder_ids=[FOLDERS[1]])
    )
    assert answer.id == moved
    message = await services.mailbox.get_message(ADMIN, account, moved)
    assert message.folder_ids == [FOLDERS[1]]


async def test_a_pass_overtaken_every_time_leaves_it_to_the_next(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    ids = await ids_by_subject(services, account)
    kept, other = ids["Mail 2"], ids["Mail 4"]
    imap_server.other_client_moves("INBOX", 4, "Archive", 40)
    before = services.index.in_folders(account, FOLDERS)
    states = services.index.folder_states(account)
    [entry] = [e for e in before if e.id == kept]
    adapter = services.adapters.get(account)
    real = adapter.folder_contents

    async def contents(folder_id: str) -> list[str]:
        # A change of ours ends during every read: here one that puts a
        # message where it already is.
        services.sync.relocate(account, kept, entry.native_id, entry.folder_id)
        return await real(folder_id)

    monkeypatch.setattr(adapter, "folder_contents", contents)
    await services.sync.sync_account(account)
    assert services.index.in_folders(account, FOLDERS) == before
    assert services.index.folder_states(account) == states
    monkeypatch.setattr(adapter, "folder_contents", real)
    await services.sync.sync_account(account)
    now = {e.native_id: e.id for e in services.index.in_folders(account, FOLDERS)}
    assert set(now) == {n for f in FOLDERS for n in await real(f)}
    # The mail the other client moved kept its id.
    assert other in now.values()


async def test_a_delete_of_ours_during_a_pass_stays_gone(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    gone = (await ids_by_subject(services, account))["Mail 1"]
    imap_server.other_client_moves("INBOX", 4, "Archive", 40)
    adapter = services.adapters.get(account)
    real = adapter.folder_contents
    reads: list[str] = []

    async def contents(folder_id: str) -> list[str]:
        reads.append(folder_id)
        if len(reads) == 2:
            await services.mailbox.delete_message(ADMIN, account, gone, True)
        return await real(folder_id)

    monkeypatch.setattr(adapter, "folder_contents", contents)
    await services.sync.sync_account(account)
    monkeypatch.setattr(adapter, "folder_contents", real)
    with pytest.raises(NotFoundError):
        await services.mailbox.get_message(ADMIN, account, gone)
    # Nothing new: the move of the other client keeps its id, and the
    # place of the deleted mail gets none.
    assert not [k for k, _, _ in recorded(services, account) if k == "message.created"]
    on_server = {n for f in FOLDERS for n in await real(f)}
    assert all(
        e.native_id in on_server for e in services.index.in_folders(account, FOLDERS)
    )


async def test_a_batch_with_a_stale_id_keeps_the_ids_it_moved(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    """The stale id asks for a pass. The moves the server made already are
    in the index before it reads, so two copies of one Message-ID keep
    their ids."""
    services, account = imap_services, imap_account_id
    for uid in (5, 6):
        imap_server.add("INBOX", uid, make_message("Dup"))
    await services.sync.sync_account(account)
    page = await services.mailbox.list_messages(
        ADMIN, account, folder_id=None, limit=50, cursor=None
    )
    dups = [m.id for m in page.items if m.subject == "Dup"]
    stale = (await ids_by_subject(services, account))["Mail 4"]
    imap_server.other_client_moves("INBOX", 4, "Archive", 40)
    batch = MessageBatch(
        ids=[*dups, stale],
        action="update",
        changes=MessageUpdate(folder_ids=[FOLDERS[1]]),
    )
    outcomes = await services.mailbox.batch_messages(ADMIN, account, batch)
    assert all(o.ok for o in outcomes.results), outcomes
    for message_id in [*dups, stale]:
        message = await services.mailbox.get_message(ADMIN, account, message_id)
        assert message.folder_ids == [FOLDERS[1]]
    deleted = [
        i for kind, i, _ in recorded(services, account) if kind == "message.deleted"
    ]
    assert not set(deleted) & set(dups)


async def test_a_pass_given_up_is_no_pass(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every attempt overtaken: the account's state names no new pass, and
    the log says "again" only where an attempt follows."""
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    kept = (await ids_by_subject(services, account))["Mail 2"]
    imap_server.other_client_moves("INBOX", 4, "Archive", 40)
    [entry] = [e for e in services.index.in_folders(account, FOLDERS) if e.id == kept]
    before = services.sync.state(account)
    adapter = services.adapters.get(account)
    real = adapter.folder_contents

    async def contents(folder_id: str) -> list[str]:
        services.sync.relocate(account, kept, entry.native_id, entry.folder_id)
        return await real(folder_id)

    monkeypatch.setattr(adapter, "folder_contents", contents)
    caplog.set_level(logging.DEBUG, logger="benethos_mailbox_service.activity")
    await services.sync.sync_account(account)
    assert services.sync.state(account) == before
    names = [r.name.rsplit(".", 1)[1] for r in caplog.records]
    assert names.count("pass_overtaken") == 2
    assert names.count("pass_given_up") == 1
    assert "synced" not in names


async def test_a_draft_replaced_while_a_pass_runs_keeps_its_id(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server holds the new draft, the index does not follow yet, and
    a pass reads: it must not take the draft's id."""
    services, account = imap_services, imap_account_id
    imap_server.folders["Drafts"] = FakeFolder(uidvalidity=3, flags=("\\Drafts",))
    await services.adapters.learn(account)
    outgoing = services.mailbox.outgoing
    first = await outgoing.create_draft(
        ADMIN, account, DraftMessage(subject="One", text="x")
    )
    await services.sync.sync_account(account)
    adapter = services.adapters.get(account)
    real = adapter.save_draft

    async def save(raw: bytes, replaces: str | None = None) -> object:
        saved = await real(raw, replaces)
        await services.sync.sync_account(account)
        return saved

    monkeypatch.setattr(adapter, "save_draft", save)
    second = await outgoing.update_draft(
        ADMIN, account, first.id, DraftMessage(subject="Two", text="y")
    )
    monkeypatch.setattr(adapter, "save_draft", real)
    assert second.id == first.id
    message = await services.mailbox.get_message(ADMIN, account, first.id)
    assert message.subject == "Two"
    told = [kind for kind, i, _ in recorded(services, account) if i == first.id]
    assert "message.deleted" not in told
