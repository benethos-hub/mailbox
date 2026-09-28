"""Folders: create, rename, move, delete.

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
    # The folder whose page the form was on, inside it or not.
    shown = text_of(form, "shown", strip=False) or parent
    again = _again(
        request,
        caller,
        account_id,
        mailbox,
        shown or FolderRole.INBOX.value,
        new=name,
        inside=parent is not None,
    )
    with failing(mail_url(account_id, shown), again=again):
        folder = await mailbox.create_folder(
            caller, account_id, _valid(FolderCreate, name=name, parent_id=parent)
        )
    return back(request, mail_url(account_id, folder.id), f"{folder.name} created.")


@router.post("/accounts/{account_id}/folders/rename")
async def rename_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = text_of(form, "folder", strip=False)
    name = text_of(form, "name")
    again = _again(request, caller, account_id, mailbox, folder_id, name=name)
    with failing(mail_url(account_id, folder_id), again=again):
        changes = _valid(FolderUpdate, name=name)
        folder = await mailbox.update_folder(caller, account_id, folder_id, changes)
    # On IMAP the id follows the name.
    return back(request, mail_url(account_id, folder.id), "Renamed.")


@router.post("/accounts/{account_id}/folders/move")
async def move_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = text_of(form, "folder", strip=False)
    parent = text_of(form, "parent", strip=False) or None
    again = _again(
        request, caller, account_id, mailbox, folder_id, moving=True, parent=parent
    )
    with failing(mail_url(account_id, folder_id), again=again):
        changes = FolderUpdate(parent_id=parent)
        folder = await mailbox.update_folder(caller, account_id, folder_id, changes)
    return back(request, mail_url(account_id, folder.id), "Moved.")


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
