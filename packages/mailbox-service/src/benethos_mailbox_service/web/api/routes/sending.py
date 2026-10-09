"""Sending from one account, and the audit of its sends. A draft is sent
in ``drafts``."""

from __future__ import annotations

from fastapi import APIRouter

from ....data.models import OutgoingMessage, Page, SendRecord, SendResult
from ..deps import Caller, IdempotencyKey, Limit, Mailbox, SendSearch
from ..errors import SEND_ERRORS

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.post("/send", responses=SEND_ERRORS)
async def send_message(
    account_id: str,
    message: OutgoingMessage,
    caller: Caller,
    mailbox: Mailbox,
    idempotency_key: IdempotencyKey = None,
) -> SendResult:
    """Send from the account's address. The service sets From, Date and
    Message-ID and keeps a read copy in the sent folder. `200` means the
    mail server accepted the message. It cannot be taken back."""
    return await mailbox.outgoing.send_message(
        caller, account_id, message, idempotency_key
    )


@router.get("/sends")
async def list_sends(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    matching: SendSearch,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[SendRecord]:
    """The audit of sends from this account, newest first: every attempt
    through `send_message` or `send_draft`, sent, denied by a grant or
    failed, with user, token and recipients, never content. The filter
    parameters narrow the list together."""
    return mailbox.outgoing.list_sends(
        caller, account_id, limit=limit, cursor=cursor, matching=matching
    )
