"""Writing mail: a new message, a reply, a forward. It is sent at once or
saved as a draft. The form is ``mailform``."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....data.models import DraftMessage, OutgoingMessage
from ....errors import MailboxServiceError
from ...services import Mailbox
from ..deps import Actor, Viewer, account_of
from ..mailform import (
    ACTIONS,
    ADDRESS_FIELDS,
    TEXT_FIELDS,
    ComposeError,
    build,
    read_fields,
    reference_of,
    sent_text,
    show,
    show_again,
)
from ..templates import back

router = APIRouter()


@router.get("/accounts/{account_id}/compose")
async def compose(
    request: Request, caller: Viewer, account_id: str, mailbox: Mailbox
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    values = {key: "" for key in (*ADDRESS_FIELDS, *TEXT_FIELDS)}
    original = None
    wanted = request.query_params.get("original")
    action = request.query_params.get("action", "")
    if wanted and action in ACTIONS:
        original = await mailbox.get_message(caller, account_id, wanted)
        values.update(original=wanted, action=action, forward_as="inline")
    return show(request, caller, account, values, original=original)


@router.post("/accounts/{account_id}/compose")
async def compose_submit(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    account = account_of(request, caller, account_id)
    try:
        fields = {**await read_fields(form), "reference": reference_of(form)}
        if form.get("do") == "send":
            result = await mailbox.send_message(
                caller,
                account_id,
                build(OutgoingMessage, fields),
                str(form.get("idempotency_key") or "") or None,
            )
            return back(f"/ui/accounts/{account_id}/mail", sent_text(result))
        saved = await mailbox.create_draft(
            caller, account_id, build(DraftMessage, fields)
        )
    except (ComposeError, MailboxServiceError) as exc:
        return await show_again(request, caller, account, form, exc)
    return back(f"/ui/accounts/{account_id}/drafts/{saved.id}", "Draft saved.")
