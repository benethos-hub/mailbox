"""Sending from one account, at once or through its outbox, and the
audit of its sends. A draft is sent in ``drafts``, the outbox listed and
cancelled in ``outbox``."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ....data.models import OutboxJob, Page, SendRecord, SendResult
from ..deps import Caller, IdempotencyKey, Limit, Mailbox, SendSearch
from ..errors import QUEUED, SEND_ERRORS
from ..schemas import OutboxEntry, SendRequest

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.post("/send", response_model=SendResult, responses={**SEND_ERRORS, **QUEUED})
async def send_message(
    account_id: str,
    message: SendRequest,
    caller: Caller,
    mailbox: Mailbox,
    idempotency_key: IdempotencyKey = None,
) -> SendResult | JSONResponse:
    """Send from the account's address. The service sets From, Date and
    Message-ID and keeps a read copy in the sent folder. `200` means the
    mail server accepted the message. It cannot be taken back.

    With `outbox` or `send_at` the message goes into the outbox instead:
    kept as a draft, answered with `202` and the job at once, and sent in
    the background, tried again while the provider is away. Its job says
    how it went (`get_outbox_job`), and webhooks hear of it."""
    if message.queued:
        job = await mailbox.outgoing.queue_message(
            caller, account_id, message.message(), message.send_at, idempotency_key
        )
        return queued(job)
    return await mailbox.outgoing.send_message(
        caller, account_id, message.message(), idempotency_key
    )


def queued(job: OutboxJob) -> JSONResponse:
    """A job of the outbox as the answer `202`."""
    entry = OutboxEntry.of(job)
    return JSONResponse(status_code=202, content=entry.model_dump(mode="json"))


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
    failed, with user, token and recipients, never content. A send through
    the outbox adds `queued`, and its end `cancelled` or `unknown`. The
    filter parameters narrow the list together."""
    return mailbox.outgoing.list_sends(
        caller, account_id, limit=limit, cursor=cursor, matching=matching
    )
