"""Every adapter through its fake, held to the same contract towards the
domain (docs/UNIFORM.md section 7): the folders, the summaries and the
messages it hands on, its pages, a missing message, and the protocols
behind the capabilities it announces. What a client sees of the rules,
`501` among them, is held by ``tests/integration/test_conformance.py``."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import FolderRole, MessageUpdate
from benethos_mailbox_service.data.providers import (
    PROTOCOLS,
    Capability,
    Deletes,
    Reads,
    Writes,
)
from benethos_mailbox_service.errors import MailboxServiceError, NotFoundError

from ...mailboxes import KINDS, Box, box, mail


@pytest.fixture(params=KINDS)
def found(request: pytest.FixtureRequest) -> Box:
    return box(request.param)


async def inbox_of(adapter: Reads) -> str:
    folders = await adapter.list_folders()
    return next(f.id for f in folders if f.role is FolderRole.INBOX)


async def test_the_folders_hang_together(found: Box) -> None:
    folders = await found.make().list_folders()
    ids = [f.id for f in folders]
    assert len(ids) == len(set(ids))
    assert [f.role for f in folders].count(FolderRole.INBOX) == 1
    assert all(f.parent_id is None or f.parent_id in ids for f in folders)


async def test_a_summary_and_its_message_agree(found: Box) -> None:
    found.put(mail("Agree"))
    adapter = found.make()
    inbox = await inbox_of(adapter)
    page = await adapter.list_messages(inbox, limit=10, cursor=None)
    [summary] = [m for m in page.items if m.subject == "Agree"]
    assert inbox in summary.folder_ids
    assert summary.date is None or summary.date.tzinfo is not None
    message = await adapter.get_message(summary.id)
    assert (message.id, message.subject) == (summary.id, "Agree")
    assert message.folder_ids == summary.folder_ids
    assert message.message_id_header == "<Agree@example.com>"
    raw = await adapter.get_raw(summary.id)
    assert b"<Agree@example.com>" in raw


async def test_pages_hand_on_each_mail_once(found: Box) -> None:
    for n in (1, 2, 3):
        found.put(mail(f"Page {n}"))
    adapter = found.make()
    inbox = await inbox_of(adapter)
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        page = await adapter.list_messages(inbox, limit=1, cursor=cursor)
        seen += [m.id for m in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == 3 == len(set(seen))


async def test_a_message_deleted_for_good_is_not_found(found: Box) -> None:
    found.put(mail("Gone"))
    adapter = found.make()
    page = await adapter.list_messages(await inbox_of(adapter), limit=10, cursor=None)
    [summary] = [m for m in page.items if m.subject == "Gone"]
    assert isinstance(adapter, Deletes)
    outcome = await adapter.delete_messages([summary.id], True)
    assert outcome == {summary.id: None}
    with pytest.raises(NotFoundError):
        await adapter.get_message(summary.id)


async def test_a_change_answers_every_id_it_was_given(found: Box) -> None:
    adapter = found.make()
    if not isinstance(adapter, Writes):
        # POP3: it deletes, and changes nothing else.
        able = await adapter.abilities()
        assert not able.has(Capability.READ_STATE)
        assert not able.has(Capability.MOVE)
        return
    found.put(mail("Change"))
    page = await adapter.list_messages(await inbox_of(adapter), limit=10, cursor=None)
    [summary] = [m for m in page.items if m.subject == "Change"]
    outcome = await adapter.update_messages(
        [summary.id, "no-such-id"], MessageUpdate(starred=True)
    )
    assert set(outcome) == {summary.id, "no-such-id"}
    changed = outcome[summary.id]
    assert not isinstance(changed, MailboxServiceError) and changed.starred
    assert isinstance(outcome["no-such-id"], MailboxServiceError)


async def test_each_capability_has_its_protocol(found: Box) -> None:
    adapter = found.make()
    able = await adapter.abilities()
    assert able.capabilities, "every kind of mailbox can do something"
    for capability in able.capabilities:
        assert isinstance(adapter, PROTOCOLS.get(capability, Reads)), capability


async def test_what_is_written_is_read(found: Box) -> None:
    able = await found.make().abilities()
    assert set(able.marks.written) <= set(able.marks.read)
    if able.marks.written:
        assert able.has(Capability.READ_STATE)
