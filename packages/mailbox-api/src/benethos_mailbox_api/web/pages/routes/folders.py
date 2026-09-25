"""Folders: create, rename, move, delete.

A folder's id travels in the form, not in the path: on IMAP it is the
folder's name and may hold a slash.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from ....data.models import FolderCreate, FolderUpdate
from ....domain.access import Access
from ....errors import MailboxApiError
from ...services import Mailbox, get_mailbox
from ..deps import Actor
from ..templates import back

router = APIRouter()


def _folder_page(account_id: str, folder_id: str | None = None) -> str:
    here = f"/ui/accounts/{account_id}/mail"
    return f"{here}?{urlencode({'folder': folder_id})}" if folder_id else here


@router.post("/accounts/{account_id}/folders")
async def create_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    parent = str(form.get("parent") or "") or None
    try:
        new = FolderCreate(name=str(form.get("name") or "").strip(), parent_id=parent)
    except ValidationError:
        return back(_folder_page(account_id, parent), error=_bad_name())
    try:
        folder = await mailbox.create_folder(caller, account_id, new)
    except MailboxApiError as exc:
        return back(_folder_page(account_id, parent), error=exc.message)
    return back(_folder_page(account_id, folder.id), f"{folder.name} created.")


@router.post("/accounts/{account_id}/folders/rename")
async def rename_folder(request: Request, caller: Actor, account_id: str) -> Response:
    form = await request.form()
    folder_id = str(form.get("folder") or "")
    try:
        changes = FolderUpdate(name=str(form.get("name") or "").strip())
    except ValidationError:
        return back(_folder_page(account_id, folder_id), error=_bad_name())
    return await _update(request, caller, account_id, folder_id, changes, "Renamed.")


@router.post("/accounts/{account_id}/folders/move")
async def move_folder(request: Request, caller: Actor, account_id: str) -> Response:
    form = await request.form()
    folder_id = str(form.get("folder") or "")
    changes = FolderUpdate(parent_id=str(form.get("parent") or "") or None)
    return await _update(request, caller, account_id, folder_id, changes, "Moved.")


async def _update(
    request: Request,
    caller: Access,
    account_id: str,
    folder_id: str,
    changes: FolderUpdate,
    done: str,
) -> Response:
    try:
        folder = await get_mailbox(request).update_folder(
            caller, account_id, folder_id, changes
        )
    except MailboxApiError as exc:
        return back(_folder_page(account_id, folder_id), error=exc.message)
    # On IMAP the id follows the name.
    return back(_folder_page(account_id, folder.id), done)


@router.post("/accounts/{account_id}/folders/delete")
async def delete_folder(
    request: Request, caller: Actor, account_id: str, mailbox: Mailbox
) -> Response:
    form = await request.form()
    folder_id = str(form.get("folder") or "")
    try:
        await mailbox.delete_folder(caller, account_id, folder_id)
    except MailboxApiError as exc:
        return back(_folder_page(account_id, folder_id), error=exc.message)
    return back(_folder_page(account_id), "Folder deleted.")


def _bad_name() -> str:
    return "A folder name needs 1 to 200 characters, without * or %."
