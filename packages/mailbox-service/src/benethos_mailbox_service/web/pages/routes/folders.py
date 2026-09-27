"""Folders: create, rename, move, delete.

A folder's id travels in the form, not in the path: on IMAP it is the
folder's name and may hold a slash.
"""

from __future__ import annotations

from typing import Any, TypeVar
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from ....data.models import FolderCreate, FolderRole, FolderUpdate
from ....domain.access import Access
from ....domain.mailbox import MailboxService
from ...services import Mailbox
from ..deps import Actor
from ..forms import Again, FormError, failing
from ..templates import back
from .mail import account_mail_page

router = APIRouter()


def _folder_page(account_id: str, folder_id: str | None = None) -> str:
    here = f"/ui/accounts/{account_id}/mail"
    return f"{here}?{urlencode({'folder': folder_id})}" if folder_id else here


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
    parent = str(form.get("parent") or "") or None
    name = str(form.get("name") or "").strip()
    # The folder whose page the form was on, inside it or not.
    shown = str(form.get("shown") or "") or parent
    again = _again(
        request,
        caller,
        account_id,
        mailbox,
        shown or FolderRole.INBOX.value,
        new=name,
        inside=parent is not None,
    )
    with failing(_folder_page(account_id, shown), again=again):
        folder = await mailbox.create_folder(
            caller, account_id, _valid(FolderCreate, name=name, parent_id=parent)
        )
    return back(request, _folder_page(account_id, folder.id), f"{folder.name} created.")


@router.post("/accounts/{account_id}/folders/rename")
async def rename_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = str(form.get("folder") or "")
    name = str(form.get("name") or "").strip()
    again = _again(request, caller, account_id, mailbox, folder_id, name=name)
    with failing(_folder_page(account_id, folder_id), again=again):
        changes = _valid(FolderUpdate, name=name)
        folder = await mailbox.update_folder(caller, account_id, folder_id, changes)
    # On IMAP the id follows the name.
    return back(request, _folder_page(account_id, folder.id), "Renamed.")


@router.post("/accounts/{account_id}/folders/move")
async def move_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = str(form.get("folder") or "")
    parent = str(form.get("parent") or "") or None
    again = _again(
        request, caller, account_id, mailbox, folder_id, moving=True, parent=parent
    )
    with failing(_folder_page(account_id, folder_id), again=again):
        changes = FolderUpdate(parent_id=parent)
        folder = await mailbox.update_folder(caller, account_id, folder_id, changes)
    return back(request, _folder_page(account_id, folder.id), "Moved.")


@router.post("/accounts/{account_id}/folders/delete")
async def delete_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = str(form.get("folder") or "")
    with failing(_folder_page(account_id, folder_id)):
        await mailbox.delete_folder(caller, account_id, folder_id)
    return back(request, _folder_page(account_id), "Folder deleted.")


M = TypeVar("M", FolderCreate, FolderUpdate)


def _valid(model: type[M], **fields: Any) -> M:
    """The request for the domain, or a FormError naming what a name needs."""
    try:
        return model(**fields)
    except ValidationError:
        raise FormError(
            "A folder name needs 1 to 200 characters, without * or %."
        ) from None
