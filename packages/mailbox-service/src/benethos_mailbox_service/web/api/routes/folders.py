"""The folders of one account."""

from __future__ import annotations

from fastapi import APIRouter

from ....data.models import Folder, FolderCreate, FolderUpdate
from ..deps import Caller, Mailbox

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/folders")
async def list_folders(
    account_id: str, caller: Caller, mailbox: Mailbox
) -> list[Folder]:
    return await mailbox.list_folders(caller, account_id)


@router.post("/folders", status_code=201)
async def create_folder(
    account_id: str, new: FolderCreate, caller: Caller, mailbox: Mailbox
) -> Folder:
    """Create a folder, subscribed so that mail clients show it."""
    return await mailbox.create_folder(caller, account_id, new)


@router.patch("/folders/{folder_id}")
async def update_folder(
    account_id: str,
    folder_id: str,
    changes: FolderUpdate,
    caller: Caller,
    mailbox: Mailbox,
) -> Folder:
    """Rename or move a folder. On IMAP its id follows its name and changes,
    but the messages inside keep theirs. Folders with a role answer `409`."""
    return await mailbox.update_folder(caller, account_id, folder_id, changes)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    account_id: str, folder_id: str, caller: Caller, mailbox: Mailbox
) -> None:
    """Delete an empty folder without subfolders. Anything else answers
    `409`, as do folders with a role."""
    await mailbox.delete_folder(caller, account_id, folder_id)
