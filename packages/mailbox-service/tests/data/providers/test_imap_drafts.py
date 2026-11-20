"""Drafts over IMAP: stored in the drafts folder, replaced where the
server has UIDPLUS, read back as stored, deleted, and reaching no other
mail."""

from __future__ import annotations

from datetime import UTC, datetime
from email import message_from_bytes

import pytest

from benethos_mailbox_service.data.mail import compose
from benethos_mailbox_service.data.models import (
    DraftMessage,
    Recipient,
)
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import (
    NotFoundError,
    NotSupportedError,
)

from ...imap_fake import FakeFolder, FakeMailBox, make_message
from .imap_adapter import provider

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


async def test_replacing_a_draft_that_is_gone_stores_nothing(box: FakeMailBox) -> None:
    imap = provider(box)
    first = await imap.save_draft(draft_bytes("One"), None)
    await imap.delete_draft(first.id)
    appends = [c for c in box.calls if c[0] == "append"]
    with pytest.raises(NotFoundError, match="not found"):
        await imap.save_draft(draft_bytes("Two"), first.id)
    assert [c for c in box.calls if c[0] == "append"] == appends
    assert (await imap.list_drafts(limit=10, cursor=None)).items == []


async def test_without_uidplus_a_draft_is_not_replaced(box: FakeMailBox) -> None:
    """The old one could not go: refused before the new one is stored."""
    imap = provider(box)
    first = await imap.save_draft(draft_bytes("One"), None)
    box.announced = ["IMAP4REV1", "MOVE"]
    appends = [c for c in box.calls if c[0] == "append"]
    with pytest.raises(NotSupportedError, match="UIDPLUS"):
        await imap.save_draft(draft_bytes("Two"), first.id)
    assert [c for c in box.calls if c[0] == "append"] == appends
    page = await imap.list_drafts(limit=10, cursor=None)
    assert [m.subject for m in page.items] == ["One"]


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
    with pytest.raises(NotSupportedError):
        await provider(box).save_draft(draft_bytes(), None)
