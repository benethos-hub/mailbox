"""Drafts: the list, and one draft in the mail form to save, send or
delete.

A draft is replaced as a whole. Its attachments stay, less those ticked
to drop, and a reply or forward keeps its link to the original with
``quote: false``: the text holds the quote already. A draft sent
unchanged is not replaced at all.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....data.models import DraftMessage, Message
from ....errors import MailboxApiError
from ...services import Mailbox
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
from ..rights import mail_rights
from ..templates import PAGE_SIZE, back, page_links, render

router = APIRouter()


@router.get("/accounts/{account_id}/drafts")
async def drafts(
    request: Request, caller: Viewer, account_id: str, mailbox: Mailbox
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    page = await mailbox.list_drafts(
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
        can_write=mail_rights(caller, account_id)["write"],
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
    request: Request, caller: Viewer, account_id: str, draft_id: str, mailbox: Mailbox
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    stored = await mailbox.get_message(caller, account_id, draft_id)
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


def _kept(stored: Message, form: Any) -> list[str]:
    """The ids of the draft's attachments that stay."""
    dropped = set(form.getlist("drop"))
    return [a.id for a in stored.attachments if a.id not in dropped]


@router.post("/accounts/{account_id}/drafts/{draft_id}")
async def draft_submit(
    request: Request, caller: Actor, account_id: str, draft_id: str, mailbox: Mailbox
) -> Response:
    """Save the draft, save and send it, or delete it."""
    form = await request.form()
    account = account_of(request, caller, account_id)
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
            await mailbox.update_draft(
                caller,
                account_id,
                draft_id,
                build(DraftMessage, fields),
                keep_attachments=_kept(stored, form),
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
