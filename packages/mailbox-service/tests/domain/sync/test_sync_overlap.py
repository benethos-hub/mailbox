"""A sync pass and a change of ours at the same time: the pass never
writes a view into the index that the change made old."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import MessageUpdate
from benethos_mailbox_service.data.providers.imap import mappers

from ...conftest import ADMIN
from ...imap_fake import FakeMailBox
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
