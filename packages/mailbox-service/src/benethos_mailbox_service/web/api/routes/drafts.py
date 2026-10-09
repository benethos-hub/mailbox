"""The drafts of one account: listed, written, replaced, sent and
deleted."""

from __future__ import annotations

from fastapi import APIRouter

from ....data.models import DraftMessage, MessageSummary, Page, SendResult
from ..deps import Caller, IdempotencyKey, Limit, Mailbox
from ..errors import SEND_ERRORS
from ..schemas import DraftReplacement

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/drafts")
async def list_drafts(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[MessageSummary]:
    """The drafts, newest first. A draft id is a message id and reads with
    `get_message`."""
    return await mailbox.outgoing.list_drafts(
        caller, account_id, limit=limit, cursor=cursor
    )


@router.post("/drafts", status_code=201)
async def create_draft(
    account_id: str, draft: DraftMessage, caller: Caller, mailbox: Mailbox
) -> MessageSummary:
    """Store a draft in the drafts folder, composed as `send_message` would,
    recipients optional. With a `reference` the quote is added now, and it
    needs `get_message` too."""
    return await mailbox.outgoing.create_draft(caller, account_id, draft)


@router.put("/drafts/{draft_id}")
async def update_draft(
    account_id: str,
    draft_id: str,
    draft: DraftReplacement,
    caller: Caller,
    mailbox: Mailbox,
) -> MessageSummary:
    """Replace a draft as a whole. The answer names its id from now on:
    an IMAP draft keeps its id, a Microsoft, JMAP or Gmail draft gets a
    new one, since the provider stores a new message. Stored attachments
    are gone unless `keep_attachments` names them. A draft sent as it is
    stored, every attachment kept, is not stored again. An id that names
    no draft answers `404`."""
    return await mailbox.outgoing.update_draft(
        caller,
        account_id,
        draft_id,
        DraftMessage.model_validate(draft, from_attributes=True),
        keep_attachments=draft.keep_attachments,
    )


@router.post("/drafts/{draft_id}/send", responses=SEND_ERRORS)
async def send_draft(
    account_id: str,
    draft_id: str,
    caller: Caller,
    mailbox: Mailbox,
    idempotency_key: IdempotencyKey = None,
) -> SendResult:
    """Send a draft as it is stored, dated now. Then it is deleted and a
    read copy kept in the sent folder. A reply or forward marks its
    original. Right: `send_draft` (`send`). It cannot be taken back."""
    return await mailbox.outgoing.send_draft(
        caller, account_id, draft_id, idempotency_key
    )


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(
    account_id: str, draft_id: str, caller: Caller, mailbox: Mailbox
) -> None:
    """Delete a draft for good. An id that names no draft answers `404`."""
    await mailbox.outgoing.delete_draft(caller, account_id, draft_id)
