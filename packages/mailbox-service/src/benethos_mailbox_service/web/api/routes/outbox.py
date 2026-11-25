"""The outbox of one account: the sends waiting in it or ended, one of
them, and cancelling one that waits. A send is put in by `send_message`
and `send_draft`."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from ....data.models import Page
from ..deps import Caller, Limit, Mailbox
from ..schemas import OutboxEntry

router = APIRouter(prefix="/accounts/{account_id}/outbox", tags=["mailbox"])

State = Literal[
    "queued", "sending", "copying", "sent", "failed", "unknown", "cancelled"
]


@router.get("")
async def list_outbox(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    state: State | None = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[OutboxEntry]:
    """The sends of the outbox, newest first: the caller's own, or every
    one with `list_sends`. `state` narrows the list. Ended sends are kept
    as long as the audit of sends keeps its records."""
    page = mailbox.outgoing.jobs.list_outbox(
        caller, account_id, limit=limit, cursor=cursor, state=state
    )
    return Page[OutboxEntry](
        items=[OutboxEntry.of(job) for job in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{job_id}")
async def get_outbox_job(
    account_id: str, job_id: str, caller: Caller, mailbox: Mailbox
) -> OutboxEntry:
    """One send of the outbox and how it stands."""
    return OutboxEntry.of(
        mailbox.outgoing.jobs.get_outbox_job(caller, account_id, job_id)
    )


@router.delete("/{job_id}")
async def cancel_send(
    account_id: str, job_id: str, caller: Caller, mailbox: Mailbox
) -> OutboxEntry:
    """Cancel a send that waits: its draft stays in the drafts folder.
    The caller's own sends, or every one with `update_account`. One that
    is being sent or ended answers `409`."""
    return OutboxEntry.of(mailbox.outgoing.jobs.cancel_send(caller, account_id, job_id))
