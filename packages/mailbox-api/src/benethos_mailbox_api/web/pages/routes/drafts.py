"""Drafts: the list, and one draft in the mail form to save, send or
delete.

A draft is replaced as a whole. Its attachments go in again, less those
ticked to drop, and a reply or forward keeps its link to the original
with ``quote: false``: the text holds the quote already. A draft sent
unchanged is not replaced at all.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....data.models import DraftMessage, Message, OutgoingAttachment
from ....domain.access import Access
from ....errors import MailboxApiError
from ...services import get_mailbox
from ..deps import Actor, Viewer, account_of
from ..mailform import (
    ComposeError,
    addresses_text,
    build,
    original_of,
    read_fields,
    sent_text,
    show,
    show_again,
    uploads,
)
from ..templates import back, page_links, render

router = APIRouter()

PAGE_SIZE = 50


@router.get("/accounts/{account_id}/drafts")
async def drafts(request: Request, caller: Viewer, account_id: str) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    page = await get_mailbox(request).list_drafts(
        caller, account_id, limit=PAGE_SIZE, cursor=request.query_params.get("cursor")
    )
    return render(
        request,
        "pages/drafts.html",
        page="mail",
        account=account,
        messages=page.items,
        pages=page_links(request, page.next_cursor),
        fields={},
        open_as="drafts",
        can_write=caller.allows("create_draft", account_id)
        or caller.allows("send_message", account_id),
    )


def _stored_values(stored: Message) -> dict[str, str]:
    return {
        "to": addresses_text(stored.to),
        "cc": addresses_text(stored.cc),
        "bcc": addresses_text(stored.bcc),
        "subject": stored.subject or "",
        "text": stored.text_body or "",
        "html": stored.html_body or "",
    }


@router.get("/accounts/{account_id}/drafts/{draft_id}")
async def draft(
    request: Request, caller: Viewer, account_id: str, draft_id: str
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    stored = await get_mailbox(request).get_message(caller, account_id, draft_id)
    return show(
        request,
        caller,
        account,
        _stored_values(stored),
        draft_id=draft_id,
        stored=stored,
        original=await original_of(request, caller, account_id, stored),
    )


def _unchanged(form: Any, stored: Message) -> bool:
    """Whether the form holds the draft as it is stored."""
    values = _stored_values(stored)
    same = all(
        " ".join(str(form.get(key) or "").split()) == " ".join(values[key].split())
        for key in values
    )
    return same and not uploads(form) and not form.getlist("drop")


async def _kept_attachments(
    request: Request, caller: Access, account_id: str, stored: Message, form: Any
) -> list[OutgoingAttachment]:
    """The draft's attachments that stay."""
    dropped = set(form.getlist("drop"))
    kept = []
    for attachment in stored.attachments:
        if attachment.id in dropped:
            continue
        content = await get_mailbox(request).get_attachment(
            caller, account_id, stored.id, attachment.id
        )
        kept.append(
            OutgoingAttachment(
                filename=attachment.filename or attachment.id,
                content_type=attachment.content_type,
                data=base64.b64encode(content.data),
            )
        )
    return kept


@router.post("/accounts/{account_id}/drafts/{draft_id}")
async def draft_submit(
    request: Request, caller: Actor, account_id: str, draft_id: str
) -> Response:
    """Save the draft, save and send it, or delete it."""
    form = await request.form()
    account = account_of(request, caller, account_id)
    mailbox = get_mailbox(request)
    here = f"/ui/accounts/{account_id}/drafts/{draft_id}"
    doing = str(form.get("do") or "save")
    stored: Message | None = None
    try:
        if doing == "delete":
            await mailbox.delete_draft(caller, account_id, draft_id)
            return back(f"/ui/accounts/{account_id}/drafts", "Draft deleted.")
        stored = await mailbox.get_message(caller, account_id, draft_id)
        if not _unchanged(form, stored):
            fields = await read_fields(form)
            if stored.reference is not None:
                fields["reference"] = stored.reference.model_copy(
                    update={"quote": False}
                )
            fields["attachments"] = [
                *await _kept_attachments(request, caller, account_id, stored, form),
                *fields["attachments"],
            ]
            await mailbox.update_draft(
                caller, account_id, draft_id, build(DraftMessage, fields)
            )
        if doing != "send":
            return back(here, "Draft saved.")
        result = await mailbox.send_draft(
            caller,
            account_id,
            draft_id,
            str(form.get("idempotency_key") or "") or None,
        )
    except (ComposeError, MailboxApiError) as exc:
        return await show_again(
            request, caller, account, form, exc, draft_id=draft_id, stored=stored
        )
    return back(f"/ui/accounts/{account_id}/mail", sent_text(result))
