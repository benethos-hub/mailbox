"""Writing mail: a new message, a reply or forward, drafts, sending.

A form that fails is shown again with what was typed, not redirected: a
redirect would lose the text. Each form carries an idempotency key made
when it was shown, so a second click on Send returns the first result
instead of sending twice.
"""

from __future__ import annotations

import base64
import secrets
from email.utils import getaddresses
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from ....data.models import (
    Account,
    Address,
    DraftMessage,
    Message,
    MessageReference,
    OutgoingAttachment,
    OutgoingMessage,
    Recipient,
    SendResult,
)
from ....domain.access import Access
from ....errors import MailboxApiError
from ...api.errors import status_of
from ...services import get_mailbox
from ..deps import Actor, Viewer, account_of
from ..templates import back, page_links, render

router = APIRouter()

ACTIONS = ("reply", "reply_all", "forward")
ADDRESS_FIELDS = ("to", "cc", "bcc")
TEXT_FIELDS = ("subject", "text", "html")


class ComposeError(ValueError):
    """What the form holds is not a message yet."""


def _account(request: Request, caller: Access, account_id: str) -> Account:
    return account_of(request, caller, account_id)


def _addresses(values: list[Address]) -> str:
    return ", ".join(f'"{a.name}" <{a.email}>' if a.name else a.email for a in values)


def _recipients(field: str, value: str) -> list[Recipient]:
    """``Name <a@example.org>, b@example.org``; a semicolon separates too."""
    value = value.replace(";", ",").strip()
    if not value:
        return []
    found = []
    for name, email in getaddresses([value]):
        try:
            found.append(Recipient(email=email, name=name or None))
        except ValidationError:
            shown = email or value
            raise ComposeError(f"{field}: {shown} is not an address") from None
    return found


async def _read(form: Any) -> dict[str, Any]:
    """The message fields of a submitted form."""
    fields: dict[str, Any] = {
        field: _recipients(field.capitalize(), str(form.get(field) or ""))
        for field in ADDRESS_FIELDS
    }
    fields["subject"] = " ".join(str(form.get("subject") or "").split())
    fields["text"] = str(form.get("text") or "") or None
    fields["html"] = str(form.get("html") or "").strip() or None
    attachments = []
    for upload in form.getlist("attachments"):
        if isinstance(upload, UploadFile) and upload.filename:
            data = await upload.read()
            attachments.append(
                OutgoingAttachment(
                    filename=upload.filename,
                    content_type=upload.content_type or "application/octet-stream",
                    data=base64.b64encode(data),
                )
            )
    fields["attachments"] = attachments
    return fields


def _reference(form: Any) -> MessageReference | None:
    original = str(form.get("original") or "")
    action = str(form.get("action") or "")
    if not original or action not in ACTIONS:
        return None
    forward_as = "attachment" if form.get("forward_as") == "attachment" else "inline"
    return MessageReference(
        message_id=original,
        action=action,
        forward_as=forward_as,
    )


def _message(model: type[DraftMessage], fields: dict[str, Any]) -> Any:
    try:
        return model(**fields)
    except ValidationError as exc:
        problem = exc.errors()[0]
        where = ".".join(str(p) for p in problem["loc"])
        reason = str(problem["msg"]).removeprefix("Value error, ")
        raise ComposeError(f"{where}: {reason}" if where else reason) from None


def _form_values(form: Any) -> dict[str, str]:
    """What the form showed, to show it again."""
    return {
        key: str(form.get(key) or "")
        for key in (*ADDRESS_FIELDS, *TEXT_FIELDS, "original", "action", "forward_as")
    }


def _sent(result: SendResult) -> str:
    refused = f" Refused: {', '.join(result.refused)}." if result.refused else ""
    return f"Sent.{refused}"


def _page(
    request: Request,
    caller: Access,
    account: Account,
    values: dict[str, str],
    *,
    draft_id: str | None = None,
    original: Message | None = None,
    stored: Message | None = None,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    account_id = account.id
    return render(
        request,
        "pages/compose.html",
        page="mail",
        status_code=status_code,
        account=account,
        values=values,
        draft_id=draft_id,
        original=original,
        # A stored draft: its attachments, and whether it answers a message.
        stored=stored,
        error=error,
        # A new key each time the form is shown: a retry of this form, and
        # only that, is the same send.
        idempotency_key=secrets.token_urlsafe(24),
        can_send=caller.allows(
            "send_draft" if draft_id else "send_message", account_id
        ),
        can_save=caller.allows(
            "update_draft" if draft_id else "create_draft", account_id
        ),
        can_delete=draft_id is not None and caller.allows("delete_draft", account_id),
    )


# --- a new message, a reply, a forward --------------------------------------------


@router.get("/accounts/{account_id}/compose")
async def compose(request: Request, caller: Viewer, account_id: str) -> HTMLResponse:
    account = _account(request, caller, account_id)
    values = {key: "" for key in (*ADDRESS_FIELDS, *TEXT_FIELDS)}
    original = None
    wanted = request.query_params.get("original")
    action = request.query_params.get("action", "")
    if wanted and action in ACTIONS:
        original = await get_mailbox(request).get_message(caller, account_id, wanted)
        values.update(original=wanted, action=action, forward_as="inline")
    return _page(request, caller, account, values, original=original)


@router.post("/accounts/{account_id}/compose")
async def compose_submit(request: Request, caller: Actor, account_id: str) -> Response:
    form = await request.form()
    account = _account(request, caller, account_id)
    mailbox = get_mailbox(request)
    sending = form.get("do") == "send"
    try:
        fields = {**await _read(form), "reference": _reference(form)}
        if sending:
            result = await mailbox.send_message(
                caller,
                account_id,
                _message(OutgoingMessage, fields),
                str(form.get("idempotency_key") or "") or None,
            )
            return back(f"/ui/accounts/{account_id}/mail", _sent(result))
        saved = await mailbox.create_draft(
            caller, account_id, _message(DraftMessage, fields)
        )
    except (ComposeError, MailboxApiError) as exc:
        return await _again(request, caller, account, form, exc)
    return back(f"/ui/accounts/{account_id}/drafts/{saved.id}", "Draft saved.")


async def _again(
    request: Request,
    caller: Access,
    account: Account,
    form: Any,
    exc: ComposeError | MailboxApiError,
    draft_id: str | None = None,
    stored: Message | None = None,
) -> HTMLResponse:
    """The form again, as it was sent, with what went wrong. Attachments
    must be chosen again: a browser cannot be handed files."""
    values = _form_values(form)
    original = None
    if values["original"] and values["action"] in ACTIONS:
        try:
            original = await get_mailbox(request).get_message(
                caller, account.id, values["original"]
            )
        except MailboxApiError:
            original = None
    if original is None:
        original = await _original_of(request, caller, account.id, stored)
    message = exc.message if isinstance(exc, MailboxApiError) else str(exc)
    return _page(
        request,
        caller,
        account,
        values,
        draft_id=draft_id,
        original=original,
        stored=stored,
        error=message,
        status_code=status_of(exc) if isinstance(exc, MailboxApiError) else 400,
    )


# --- drafts -----------------------------------------------------------------------


@router.get("/accounts/{account_id}/drafts")
async def drafts(request: Request, caller: Viewer, account_id: str) -> HTMLResponse:
    account = _account(request, caller, account_id)
    page = await get_mailbox(request).list_drafts(
        caller, account_id, limit=50, cursor=request.query_params.get("cursor")
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
        "to": _addresses(stored.to),
        "cc": _addresses(stored.cc),
        "bcc": _addresses(stored.bcc),
        "subject": stored.subject or "",
        "text": stored.text_body or "",
        "html": stored.html_body or "",
    }


@router.get("/accounts/{account_id}/drafts/{draft_id}")
async def draft(
    request: Request, caller: Viewer, account_id: str, draft_id: str
) -> HTMLResponse:
    account = _account(request, caller, account_id)
    stored = await get_mailbox(request).get_message(caller, account_id, draft_id)
    return _page(
        request,
        caller,
        account,
        _stored_values(stored),
        draft_id=draft_id,
        stored=stored,
        original=await _original_of(request, caller, account_id, stored),
    )


async def _original_of(
    request: Request, caller: Access, account_id: str, stored: Message | None
) -> Message | None:
    """The message a draft answers or forwards, if it can still be read."""
    if stored is None or stored.reference is None:
        return None
    try:
        return await get_mailbox(request).get_message(
            caller, account_id, stored.reference.message_id
        )
    except MailboxApiError:
        return None


def _unchanged(form: Any, stored: Message) -> bool:
    """Whether the form holds the draft as it is stored: then it is sent as
    it is, and a reply keeps its link to the original."""
    values = _stored_values(stored)
    same = all(
        " ".join(str(form.get(key) or "").split()) == " ".join(values[key].split())
        for key in values
    )
    uploads = [
        u
        for u in form.getlist("attachments")
        if isinstance(u, UploadFile) and u.filename
    ]
    return same and not uploads and not form.getlist("drop")


async def _kept_attachments(
    request: Request, caller: Access, account_id: str, stored: Message, form: Any
) -> list[OutgoingAttachment]:
    """The draft's attachments that stay: a replaced draft is whole, so
    they go in again, less those ticked to drop."""
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
    account = _account(request, caller, account_id)
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
            fields = await _read(form)
            # The text holds the quote already: keep the link, add nothing.
            if stored.reference is not None:
                fields["reference"] = stored.reference.model_copy(
                    update={"quote": False}
                )
            fields["attachments"] = [
                *await _kept_attachments(request, caller, account_id, stored, form),
                *fields["attachments"],
            ]
            await mailbox.update_draft(
                caller, account_id, draft_id, _message(DraftMessage, fields)
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
        return await _again(
            request, caller, account, form, exc, draft_id=draft_id, stored=stored
        )
    return back(f"/ui/accounts/{account_id}/mail", _sent(result))
