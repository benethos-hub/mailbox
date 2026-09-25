"""Changing messages: flags, moving, deleting, one or many at a time."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from ....data.models import MessageBatch, MessageUpdate
from ...services import Mailbox
from ..deps import Actor
from ..forms import failing
from ..templates import back, local_path

router = APIRouter()

# What the list's action menu offers, and the batch each one is.
BATCH_ACTIONS: dict[str, tuple[str, MessageUpdate | None, bool]] = {
    "read": ("update", MessageUpdate(unread=False), False),
    "unread": ("update", MessageUpdate(unread=True), False),
    "star": ("update", MessageUpdate(starred=True), False),
    "unstar": ("update", MessageUpdate(starred=False), False),
    "trash": ("delete", None, False),
    "delete": ("delete", None, True),
}


@router.post("/accounts/{account_id}/mail/{message_id}/flags")
async def set_flags(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    here = f"/ui/accounts/{account_id}/mail/{message_id}"
    changes = MessageUpdate(
        unread=form["unread"] == "1" if "unread" in form else None,
        starred=form["starred"] == "1" if "starred" in form else None,
    )
    with failing(here):
        await mailbox.update_message(caller, account_id, message_id, changes)
    return back(here)


@router.post("/accounts/{account_id}/mail/{message_id}/move")
async def move(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    here = f"/ui/accounts/{account_id}/mail/{message_id}"
    folder = str(form.get("folder") or "")
    if not folder:
        return back(here, error="Choose a folder.")
    with failing(here):
        await mailbox.update_message(
            caller, account_id, message_id, MessageUpdate(folder_ids=[folder])
        )
    # The id stays when a message moves.
    return back(here, "Moved.")


@router.post("/accounts/{account_id}/mail/{message_id}/delete")
async def delete(
    request: Request, caller: Actor, account_id: str, message_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    permanent = form.get("permanent") == "1"
    listing = local_path(str(form.get("back") or ""), f"/ui/accounts/{account_id}/mail")
    with failing(f"/ui/accounts/{account_id}/mail/{message_id}"):
        await mailbox.delete_message(caller, account_id, message_id, permanent)
    return back(listing, "Deleted for good." if permanent else "Moved to the trash.")


@router.post("/accounts/{account_id}/mail/batch")
async def batch(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    """The action menu above a list, for the messages ticked in it."""
    form = await request.form()
    listing = local_path(str(form.get("back") or ""), f"/ui/accounts/{account_id}/mail")
    ids = [str(i) for i in form.getlist("ids")]
    action = "delete" if form.get("purge") == "1" else str(form.get("action") or "")
    if not ids:
        return back(listing, error="Tick at least one message.")
    try:
        if action == "move":
            folder = str(form.get("folder") or "")
            if not folder:
                return back(listing, error="Choose a folder to move to.")
            request_batch = MessageBatch(
                ids=ids,
                action="update",
                changes=MessageUpdate(folder_ids=[folder]),
            )
        elif action in BATCH_ACTIONS:
            kind, changes, permanent = BATCH_ACTIONS[action]
            request_batch = MessageBatch(
                ids=ids,
                action=kind,
                changes=changes,
                permanent=permanent,
            )
        else:
            return back(listing, error="Choose an action.")
    except ValidationError:
        return back(listing, error="At most 100 messages at a time.")
    with failing(listing):
        result = await mailbox.batch_messages(caller, account_id, request_batch)
    failed = [r for r in result.results if not r.ok]
    done = len(result.results) - len(failed)
    if failed:
        reasons = "; ".join(
            sorted({r.error.message for r in failed if r.error is not None})
        )
        return back(listing, f"{done} done.", error=f"{len(failed)} failed: {reasons}")
    return back(listing, f"{done} done.")
