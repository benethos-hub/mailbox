"""Changing messages: flags, moving, deleting, one or many at a time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from ....data.models import MessageBatch, MessageUpdate
from ...services import Mailbox
from ..deps import Actor
from ..forms import FormError, failing, model_of, text_of
from ..navigation import mail_url, message_url
from ..templates import back, local_path

router = APIRouter()


@dataclass(frozen=True, slots=True)
class BatchAction:
    """The batch one entry of the list's action menu is."""

    action: Literal["update", "delete"]
    changes: MessageUpdate | None = None
    permanent: bool = False


BATCH_ACTIONS = {
    "read": BatchAction("update", MessageUpdate(unread=False)),
    "unread": BatchAction("update", MessageUpdate(unread=True)),
    "star": BatchAction("update", MessageUpdate(starred=True)),
    "unstar": BatchAction("update", MessageUpdate(starred=False)),
    "trash": BatchAction("delete"),
    "delete": BatchAction("delete", permanent=True),
}


@router.post("/accounts/{account_id}/mail/{message_id}/flags")
async def set_flags(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    here = message_url(account_id, message_id)
    changes = MessageUpdate(
        unread=form["unread"] == "1" if "unread" in form else None,
        starred=form["starred"] == "1" if "starred" in form else None,
    )
    with failing(here):
        await mailbox.update_message(caller, account_id, message_id, changes)
    return back(request, here)


KEYWORD_RULE = "A keyword is up to 100 characters on one line, not starting with \\."


@router.post("/accounts/{account_id}/mail/{message_id}/keywords")
async def keywords(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    """Add a keyword or remove one. The others stay as the message has
    them, those of the mail protocol among them."""
    form = await request.form()
    here = message_url(account_id, message_id)
    adding = text_of(form, "add")
    removing = text_of(form, "remove", strip=False)
    with failing(here):
        if adding.startswith("$"):
            raise FormError("Keywords starting with $ belong to the mail protocol.")
        if adding:
            fields = {"add_keywords": [adding]}
        elif removing:
            fields = {"remove_keywords": [removing]}
        else:
            raise FormError("Type a keyword.")
        changes = model_of(MessageUpdate, fields, message=KEYWORD_RULE)
        await mailbox.update_message(caller, account_id, message_id, changes)
    return back(request, here)


@router.post("/accounts/{account_id}/mail/{message_id}/move")
async def move(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    here = message_url(account_id, message_id)
    folder = text_of(form, "folder", strip=False)
    if not folder:
        return back(request, here, error="Choose a folder.")
    with failing(here):
        await mailbox.update_message(
            caller, account_id, message_id, MessageUpdate(folder_ids=[folder])
        )
    # The id stays when a message moves.
    return back(request, here, "Moved.")


@router.post("/accounts/{account_id}/mail/{message_id}/delete")
async def delete(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    permanent = form.get("permanent") == "1"
    listing = local_path(text_of(form, "back", strip=False), mail_url(account_id))
    with failing(message_url(account_id, message_id)):
        await mailbox.delete_message(caller, account_id, message_id, permanent)
    return back(
        request, listing, "Deleted for good." if permanent else "Moved to the trash."
    )


@router.post("/accounts/{account_id}/mail/batch")
async def batch(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    """The action menu above a list, for the messages ticked in it."""
    form = await request.form()
    listing = local_path(text_of(form, "back", strip=False), mail_url(account_id))
    ids = [str(i) for i in form.getlist("ids")]
    action = (
        "delete" if form.get("purge") == "1" else text_of(form, "action", strip=False)
    )
    if not ids:
        return back(request, listing, error="Tick at least one message.")
    try:
        if action == "move":
            folder = text_of(form, "folder", strip=False)
            if not folder:
                return back(request, listing, error="Choose a folder to move to.")
            request_batch = MessageBatch(
                ids=ids,
                action="update",
                changes=MessageUpdate(folder_ids=[folder]),
            )
        elif action in BATCH_ACTIONS:
            chosen = BATCH_ACTIONS[action]
            request_batch = MessageBatch(
                ids=ids,
                action=chosen.action,
                changes=chosen.changes,
                permanent=chosen.permanent,
            )
        else:
            return back(request, listing, error="Choose an action.")
    except ValidationError:
        return back(request, listing, error="At most 100 messages at a time.")
    with failing(listing):
        result = await mailbox.batch_messages(caller, account_id, request_batch)
    failed = [r for r in result.results if not r.ok]
    done = len(result.results) - len(failed)
    if failed:
        reasons = ". ".join(
            sorted({r.error.message for r in failed if r.error is not None})
        )
        return back(
            request, listing, f"{done} done.", error=f"{len(failed)} failed: {reasons}"
        )
    return back(request, listing, f"{done} done.")
