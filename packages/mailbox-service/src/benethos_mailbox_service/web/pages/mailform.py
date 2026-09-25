"""The mail form, shared by writing and by drafts: its fields read into a
message, and the form shown, again with what was typed when it failed.

A failed form is shown again, not redirected: a redirect would lose the
text. Each time the form is shown it gets a new idempotency key, so a
second click on Send returns the first result instead of sending twice.
"""

from __future__ import annotations

import base64
import secrets
from email.utils import getaddresses
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from ...data.models import (
    Account,
    Address,
    DraftMessage,
    Message,
    MessageReference,
    OutgoingAttachment,
    Recipient,
    SendResult,
)
from ...domain.access import Access
from ...errors import MailboxServiceError
from ..errors import status_of
from ..services import get_mailbox
from .forms import FormError, first_problem
from .templates import render

ACTIONS = ("reply", "reply_all", "forward")
ADDRESS_FIELDS = ("to", "cc", "bcc")
TEXT_FIELDS = ("subject", "text", "html")


class ComposeError(FormError):
    """What the form holds is not a message yet."""


def addresses_text(values: list[Address]) -> str:
    """Addresses as the form shows them."""
    return ", ".join(f'"{a.name}" <{a.email}>' if a.name else a.email for a in values)


def recipients(field: str, value: str) -> list[Recipient]:
    """``Name <a@example.org>, b@example.org``. A semicolon separates too."""
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


def uploads(form: Any) -> list[UploadFile]:
    """The files chosen in the form."""
    return [
        u
        for u in form.getlist("attachments")
        if isinstance(u, UploadFile) and u.filename
    ]


async def read_fields(form: Any) -> dict[str, Any]:
    """The message fields of a submitted form."""
    fields: dict[str, Any] = {
        field: recipients(field.capitalize(), str(form.get(field) or ""))
        for field in ADDRESS_FIELDS
    }
    fields["subject"] = " ".join(str(form.get("subject") or "").split())
    fields["text"] = str(form.get("text") or "") or None
    fields["html"] = str(form.get("html") or "").strip() or None
    fields["attachments"] = [
        OutgoingAttachment(
            filename=upload.filename or "attachment",
            content_type=upload.content_type or "application/octet-stream",
            data=base64.b64encode(await upload.read()),
        )
        for upload in uploads(form)
    ]
    return fields


def reference_of(form: Any) -> MessageReference | None:
    """The message a new mail answers or forwards, from the form."""
    original = str(form.get("original") or "")
    action = str(form.get("action") or "")
    if not original or action not in ACTIONS:
        return None
    forward_as = "attachment" if form.get("forward_as") == "attachment" else "inline"
    return MessageReference(message_id=original, action=action, forward_as=forward_as)


def build(model: type[DraftMessage], fields: dict[str, Any]) -> Any:
    """``model`` from the fields. What is wrong raises a ``ComposeError``."""
    try:
        return model(**fields)
    except ValidationError as exc:
        raise ComposeError(first_problem(exc)) from None


def sent_text(result: SendResult) -> str:
    refused = f" Refused: {', '.join(result.refused)}." if result.refused else ""
    return f"Sent.{refused}"


def show(
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
    """The form with ``values``, and for a stored draft with its id."""
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
        # A stored draft: its attachments, and what it answers.
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


async def show_again(
    request: Request,
    caller: Access,
    account: Account,
    form: Any,
    exc: ComposeError | MailboxServiceError,
    draft_id: str | None = None,
    stored: Message | None = None,
) -> HTMLResponse:
    """The form again, as it was sent, with what went wrong. Attachments
    must be chosen again: a browser cannot be handed files."""
    values = {
        key: str(form.get(key) or "")
        for key in (*ADDRESS_FIELDS, *TEXT_FIELDS, "original", "action", "forward_as")
    }
    original = None
    if values["original"] and values["action"] in ACTIONS:
        original = await _readable(request, caller, account.id, values["original"])
    if original is None:
        original = await original_of(request, caller, account.id, stored)
    return show(
        request,
        caller,
        account,
        values,
        draft_id=draft_id,
        original=original,
        stored=stored,
        error=exc.message,
        status_code=status_of(exc) if isinstance(exc, MailboxServiceError) else 400,
    )


async def original_of(
    request: Request, caller: Access, account_id: str, stored: Message | None
) -> Message | None:
    """The message a draft answers or forwards, if it can still be read."""
    if stored is None or stored.reference is None:
        return None
    return await _readable(request, caller, account_id, stored.reference.message_id)


async def _readable(
    request: Request, caller: Access, account_id: str, message_id: str
) -> Message | None:
    try:
        return await get_mailbox(request).get_message(caller, account_id, message_id)
    except MailboxServiceError:
        return None
