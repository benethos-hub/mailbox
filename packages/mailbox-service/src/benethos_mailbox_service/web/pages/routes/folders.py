"""Folders: create, change (rename and move in one form), delete.

A folder's id travels in the form, not in the path: on IMAP it is the
folder's name and may hold a slash.
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ....data.models import FolderCreate, FolderRole, FolderUpdate
from ....domain.mailbox import MailboxService
from ....domain.rights import Access
from ...services import Mailbox
from ..deps import Actor
from ..forms import Again, failing, model_of, text_of
from ..navigation import mail_url
from ..templates import back
from .mail import account_mail_page

router = APIRouter()


def _again(
    request: Request,
    caller: Access,
    account_id: str,
    mailbox: MailboxService,
    shown: str,
    **typed: Any,
) -> Again:
    """The mail page of the folder ``shown`` again, its folder forms as
    typed."""

    async def page(err: str) -> Response:
        return await account_mail_page(
            request, caller, account_id, mailbox, shown, typed, err
        )

    return page


@router.post("/accounts/{account_id}/folders")
async def create_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    parent = text_of(form, "parent", strip=False) or None
    name = text_of(form, "name")
    # The folder whose page the form was on.
    shown = text_of(form, "shown", strip=False) or parent
    again = _again(
        request,
        caller,
        account_id,
        mailbox,
        shown or FolderRole.INBOX.value,
        adding=True,
        new=name,
        new_parent=parent,
    )
    with failing(mail_url(account_id, shown), again=again):
        folder = await mailbox.create_folder(
            caller, account_id, _valid(FolderCreate, name=name, parent_id=parent)
        )
    return back(request, mail_url(account_id, folder.id), f"{folder.name} created.")


@router.post("/accounts/{account_id}/folders/change")
async def change_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    """The form at the folder: its name and where it sits. Only what
    differs from what the form showed goes to the domain, so a new name
    alone renames and another "Inside" alone moves."""
    form = await request.form()
    folder_id = text_of(form, "folder", strip=False)
    name = text_of(form, "name")
    parent = text_of(form, "parent", strip=False) or None
    fields: dict[str, Any] = {}
    if name != text_of(form, "was_name"):
        fields["name"] = name
    if parent != (text_of(form, "was_parent", strip=False) or None):
        fields["parent_id"] = parent
    here = mail_url(account_id, folder_id)
    if not fields:
        return back(request, here, "Nothing changed.")
    again = _again(
        request,
        caller,
        account_id,
        mailbox,
        folder_id,
        changing=True,
        name=name,
        parent=parent,
    )
    with failing(here, again=again):
        changes = _valid(FolderUpdate, **fields)
        folder = await mailbox.update_folder(caller, account_id, folder_id, changes)
    done = _DONE.get(tuple(fields), "Renamed and moved.")
    # On IMAP the id follows the name and the place.
    return back(request, mail_url(account_id, folder.id), done)


# What the form at the folder did, by the fields it changed.
_DONE: dict[tuple[str, ...], str] = {("name",): "Renamed.", ("parent_id",): "Moved."}


@router.post("/accounts/{account_id}/folders/delete")
async def delete_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = text_of(form, "folder", strip=False)
    with failing(mail_url(account_id, folder_id)):
        await mailbox.delete_folder(caller, account_id, folder_id)
    return back(request, mail_url(account_id), "Folder deleted.")


M = TypeVar("M", FolderCreate, FolderUpdate)


def _valid(model: type[M], **fields: Any) -> M:
    """The request for the domain, or a FormError naming what a name needs."""
    return model_of(
        model,
        fields,
        message="A folder name needs 1 to 200 characters, without * or %.",
    )
