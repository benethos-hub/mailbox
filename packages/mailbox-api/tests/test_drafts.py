"""Drafts (CONCEPT 6.4): stored in the drafts folder, reached only there."""

from __future__ import annotations

from datetime import UTC, datetime
from email import message_from_bytes

import pytest

from benethos_mailbox_api.data.mail import compose
from benethos_mailbox_api.data.models import DraftMessage, Folder, FolderRole, Recipient
from benethos_mailbox_api.data.providers import MemoryProvider
from benethos_mailbox_api.data.providers.imap import mappers
from benethos_mailbox_api.errors import ConflictError, NotFoundError

from .imap_fake import FakeFolder, FakeMailBox, make_message
from .test_imap import provider

SENDER = Recipient(email="me@example.com", name="Me")
WHEN = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def draft_bytes(subject: str = "Plan", reference: str | None = None) -> bytes:
    return compose.message(
        DraftMessage(
            to=[Recipient(email="bob@example.com")],
            bcc=[Recipient(email="carol@example.com")],
            subject=subject,
            text="Draft text",
        ),
        SENDER,
        WHEN,
        compose.new_message_id(SENDER.email),
        draft=True,
        reference=reference,
    )


@pytest.fixture
def box() -> FakeMailBox:
    box = FakeMailBox()
    box.folders = {
        "INBOX": FakeFolder(uidvalidity=7),
        "Drafts": FakeFolder(uidvalidity=3, flags=("\\Drafts",)),
    }
    box.add("INBOX", 1, make_message("Not a draft"))
    return box


# --- the message format -----------------------------------------------------------


def test_a_draft_keeps_bcc_and_reference_until_it_is_sent() -> None:
    raw = draft_bytes(reference="reply msg_1")
    stored = message_from_bytes(raw)
    assert stored["Bcc"] == "carol@example.com"
    assert stored[compose.REFERENCE_HEADER] == "reply msg_1"

    later = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
    out, recipients, reference = compose.outgoing(raw, later)
    sent = message_from_bytes(out)
    assert recipients == ["bob@example.com", "carol@example.com"]
    assert reference == "reply msg_1"
    assert sent["Bcc"] is None and sent[compose.REFERENCE_HEADER] is None
    assert sent["Date"] == "Fri, 25 Sep 2026 08:00:00 +0000"
    assert sent["Message-ID"] == stored["Message-ID"]


def test_a_message_to_send_keeps_no_bcc_header() -> None:
    raw = compose.message(
        DraftMessage(bcc=[Recipient(email="carol@example.com")], text="x"),
        SENDER,
        WHEN,
        "<1@example.com>",
    )
    assert message_from_bytes(raw)["Bcc"] is None


# --- the IMAP adapter ---------------------------------------------------------------


async def test_a_draft_is_stored_in_the_drafts_folder(box: FakeMailBox) -> None:
    saved = await provider(box).save_draft(draft_bytes(), None)
    assert saved.folder_ids == [mappers.folder_id("Drafts")]
    assert saved.subject == "Plan"
    assert "$draft" in saved.keywords
    assert ("append", "Drafts", ("\\Draft", "\\Seen")) in box.calls


async def test_replacing_a_draft_removes_the_old_one(box: FakeMailBox) -> None:
    imap = provider(box)
    first = await imap.save_draft(draft_bytes("One"), None)
    second = await imap.save_draft(draft_bytes("Two"), first.id)
    page = await imap.list_drafts(limit=10, cursor=None)
    assert [m.subject for m in page.items] == ["Two"]
    assert second.id != first.id
    with pytest.raises(NotFoundError):
        await imap.get_draft(first.id)


async def test_a_draft_reads_back_as_stored(box: FakeMailBox) -> None:
    imap = provider(box)
    saved = await imap.save_draft(draft_bytes(), None)
    raw = await imap.get_draft(saved.id)
    assert message_from_bytes(raw)["Bcc"] == "carol@example.com"


async def test_draft_operations_reach_no_other_mail(box: FakeMailBox) -> None:
    imap = provider(box)
    inbox_mail = mappers.message_id("INBOX", 7, 1)
    with pytest.raises(NotFoundError):
        await imap.get_draft(inbox_mail)
    with pytest.raises(NotFoundError):
        await imap.delete_draft(inbox_mail)
    with pytest.raises(NotFoundError):
        await imap.save_draft(draft_bytes(), inbox_mail)
    with pytest.raises(NotFoundError):
        await imap.delete_draft("not an id")
    assert 1 in box.folders["INBOX"].messages
    assert not [c for c in box.calls if c[0] == "append"]


async def test_a_deleted_draft_is_gone(box: FakeMailBox) -> None:
    imap = provider(box)
    saved = await imap.save_draft(draft_bytes(), None)
    await imap.delete_draft(saved.id)
    assert not box.folders["Drafts"].messages
    with pytest.raises(NotFoundError):
        await imap.delete_draft(saved.id)


async def test_without_a_drafts_folder(box: FakeMailBox) -> None:
    del box.folders["Drafts"]
    with pytest.raises(ConflictError):
        await provider(box).save_draft(draft_bytes(), None)


# --- the memory adapter -------------------------------------------------------------


async def test_memory_drafts() -> None:
    memory = MemoryProvider()
    saved = await memory.save_draft(draft_bytes("One"), None)
    replaced = await memory.save_draft(draft_bytes("Two"), saved.id)
    page = await memory.list_drafts(limit=10, cursor=None)
    assert [m.subject for m in page.items] == ["Two"]
    assert message_from_bytes(await memory.get_draft(replaced.id))["Subject"] == "Two"
    await memory.delete_draft(replaced.id)
    assert not (await memory.list_drafts(limit=10, cursor=None)).items


async def test_memory_drafts_reach_no_other_mail() -> None:
    memory = MemoryProvider(
        folders=[Folder(id="inbox", name="Inbox", role=FolderRole.INBOX)]
    )
    with pytest.raises(ConflictError):
        await memory.list_drafts(limit=10, cursor=None)
    memory.folders.append(Folder(id="drafts", name="Drafts", role=FolderRole.DRAFTS))
    with pytest.raises(NotFoundError):
        await memory.delete_draft("m0")
