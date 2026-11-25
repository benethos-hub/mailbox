"""The outbox of one account: the sends waiting in it or ended, and
cancelling one that waits. A send is put in from the mail form."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....data.models import OutboxState
from ....errors import MailboxServiceError
from ...services import Mailbox
from ..deps import Actor, Viewer, account_of
from ..navigation import mail_trail, outbox_url
from ..templates import PAGE_SIZE, back, page_links, render

router = APIRouter()

STATES: tuple[OutboxState, ...] = (
    "queued",
    "sending",
    "copying",
    "sent",
    "failed",
    "unknown",
    "cancelled",
)


@router.get("/accounts/{account_id}/outbox")
async def outbox(
    request: Request, caller: Viewer, account_id: str, mailbox: Mailbox
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    wanted = request.query_params.get("state")
    state = next((s for s in STATES if s == wanted), None)
    jobs = mailbox.outgoing.jobs
    page = jobs.list_outbox(
        caller,
        account_id,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
        state=state,
    )
    return render(
        request,
        "pages/outbox.html",
        page="mail",
        account=account,
        trail=[*mail_trail(account), ("Outbox", None)],
        jobs=page.items,
        state=state,
        states=STATES,
        pages=page_links(request, page.next_cursor),
        can_cancel_any=caller.allows("update_account", account_id),
        can_cancel_own=caller.allows("cancel_send", account_id),
        me_id=caller.user_id,
    )


@router.post("/accounts/{account_id}/outbox/{job_id}/cancel")
async def cancel(
    request: Request, caller: Actor, account_id: str, job_id: str, mailbox: Mailbox
) -> Response:
    try:
        mailbox.outgoing.jobs.cancel_send(caller, account_id, job_id)
    except MailboxServiceError as exc:
        return back(request, outbox_url(account_id), error=exc.message)
    return back(request, outbox_url(account_id), "Cancelled. Its draft stays.")
