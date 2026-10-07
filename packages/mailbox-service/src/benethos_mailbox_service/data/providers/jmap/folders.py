"""Folders (mailboxes) made, renamed, moved and deleted."""

from __future__ import annotations

from ....errors import BadRequestError, ConflictError, ProviderError, missing
from ...models import Folder
from ...protocols import jmap
from . import mappers
from .account import JmapAccount


async def create_folder(
    account: JmapAccount, name: str, parent_id: str | None
) -> Folder:
    folders = await account.folders()
    _check_place(folders, None, name, parent_id)
    done = await account.one(
        "Mailbox/set",
        {
            "create": {
                "new": {"name": name, "parentId": parent_id, "isSubscribed": True}
            }
        },
    )
    failed = (done.get("notCreated") or {}).get("new")
    if failed is not None:
        raise jmap.set_error(failed, "folder")
    # Asked for apart: not every server resolves a reference to a /set.
    made = str(((done.get("created") or {}).get("new") or {}).get("id"))
    got = await account.one(
        "Mailbox/get", {"ids": [made], "properties": mappers.MAILBOX_PROPERTIES}
    )
    found = got.get("list") or []
    if not found:
        raise ProviderError("the folder was stored but cannot be found again")
    return mappers.folder(found[0])


async def update_folder(
    account: JmapAccount, folder_id: str, name: str, parent_id: str | None
) -> Folder:
    folders = await account.folders()
    current = next((f for f in folders if f.id == folder_id), None)
    if current is None:
        raise missing("folder", folder_id)
    if current.name == name and current.parent_id == parent_id:
        return current
    _check_place(folders, folder_id, name, parent_id)
    owner = await account.id()
    answers = await account.call(
        (
            "Mailbox/set",
            {
                "accountId": owner,
                "update": {folder_id: {"name": name, "parentId": parent_id}},
            },
            "set",
        ),
        (
            "Mailbox/get",
            {
                "accountId": owner,
                "ids": [folder_id],
                "properties": mappers.MAILBOX_PROPERTIES,
            },
            "get",
        ),
    )
    failed = (jmap.result(answers, "set").get("notUpdated") or {}).get(folder_id)
    if failed is not None:
        raise jmap.set_error(failed, "folder")
    found = jmap.result(answers, "get").get("list") or []
    if not found:
        raise ProviderError("the folder was stored but cannot be found again")
    return mappers.folder(found[0])


async def delete_folder(account: JmapAccount, folder_id: str) -> None:
    if not mappers.is_id(folder_id):
        raise missing("folder", folder_id)
    done = await account.one(
        "Mailbox/set", {"destroy": [folder_id], "onDestroyRemoveEmails": False}
    )
    failed = (done.get("notDestroyed") or {}).get(folder_id)
    if failed is not None:
        raise jmap.set_error(failed, "folder")


def _check_place(
    folders: list[Folder], folder_id: str | None, name: str, parent_id: str | None
) -> None:
    """Refuse a folder ``name`` below ``parent_id`` where it cannot be: the
    parent is missing, is the folder itself or below it, or a folder of
    that name is there already."""
    by_id = {f.id: f for f in folders}
    if parent_id is not None:
        if parent_id not in by_id:
            raise missing("folder", parent_id)
        above: str | None = parent_id
        while above is not None:
            if above == folder_id:
                raise BadRequestError("a folder cannot move into itself")
            above = by_id[above].parent_id if above in by_id else None
    if any(
        f.parent_id == parent_id and f.name == name and f.id != folder_id
        for f in folders
    ):
        raise ConflictError(f"a folder {name} exists there already")
