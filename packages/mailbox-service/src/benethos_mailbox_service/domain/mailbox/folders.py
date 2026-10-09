"""The folders of one account: listed, created, renamed, moved and
deleted under the caller's rights and the folders its grants reach, and
a role such as ``inbox`` read as the folder that has it.

Reached through ``MailboxService``, which uses the roles for messages
too.
"""

from __future__ import annotations

from ...data.models import (
    Folder,
    FolderCreate,
    FolderRole,
    FolderUpdate,
    MessageUpdate,
)
from ...errors import ConflictError, MailboxServiceError, NotFoundError, missing
from ..accounts import writes
from ..rights import Access
from .calls import Calls
from .reach import Reach, outside, reach_of, require_folder


class Folders:
    """Folder calls under the caller's rights. The provider's own calls
    go through ``calls``."""

    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        """The account's folders, those the grants reach where they name
        folders."""
        access.require("list_folders", account_id)
        folders = await self.all(account_id)
        reach = await self._reach(access, "list_folders", account_id, folders)
        return folders if reach is None else [f for f in folders if f.id in reach.ids]

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        """Where the grants name folders, only inside one of them."""
        access.require("create_folder", account_id)
        parent = await self.by_role(account_id, new.parent_id)
        reach = await self._reach(access, "create_folder", account_id)
        if reach is not None:
            if parent is None:
                raise outside("create_folder", "at the top")
            require_folder(reach, parent)
        return await self._calls.call(
            account_id, lambda p: writes(p).create_folder(new.name, parent)
        )

    async def update_folder(
        self, access: Access, account_id: str, folder_id: str, changes: FolderUpdate
    ) -> Folder:
        """Rename or move. Folders with a role stay where mail clients expect
        them. The messages inside keep their ids: a sync follows them."""
        access.require("update_folder", account_id)
        folder, folders = await self._own_folder(account_id, folder_id)
        reach = await self._reach(access, "update_folder", account_id, folders)
        if reach is not None:
            require_folder(reach, folder_id)
        name = changes.name or folder.name
        parent = (
            await self.by_role(account_id, changes.parent_id)
            if changes.moves
            else folder.parent_id
        )
        if reach is not None and changes.moves:
            if parent is None:
                raise outside("update_folder", "at the top")
            require_folder(reach, parent)
            if not reach.holds(folder_id, parent):
                raise outside("update_folder", "into the folders of another grant")
        updated = await self._calls.call(
            account_id, lambda p: writes(p).update_folder(folder_id, name, parent)
        )
        if updated.id != folder_id:
            try:
                await self._calls.resync(account_id)
            except MailboxServiceError:
                pass  # the next sync, or the next lookup, follows them
        return updated

    async def delete_folder(
        self, access: Access, account_id: str, folder_id: str
    ) -> None:
        """Only an empty folder without subfolders: deleting a folder takes
        its messages with it on many servers, and they cannot be taken back."""
        access.require("delete_folder", account_id)
        folder, folders = await self._own_folder(account_id, folder_id)
        reach = await self._reach(access, "delete_folder", account_id, folders)
        if reach is not None:
            require_folder(reach, folder_id)
        if any(f.parent_id == folder_id for f in folders):
            raise ConflictError(f"the folder {folder.name} has subfolders")
        contents = await self._calls.call(
            account_id, lambda p: p.folder_contents(folder_id)
        )
        if contents:
            raise ConflictError(
                f"the folder {folder.name} holds {len(contents)} messages: "
                "move or delete them first"
            )
        await self._calls.call(account_id, lambda p: writes(p).delete_folder(folder_id))

    async def all(self, account_id: str) -> list[Folder]:
        """Every folder of the account, whatever the caller reaches."""
        return await self._calls.call(account_id, lambda p: p.list_folders())

    async def by_role(self, account_id: str, folder: str | None) -> str | None:
        """A folder id, or the id of the folder with that role."""
        if folder is None or not is_role(folder):
            return folder
        return _resolved(await self.all(account_id), folder)

    async def with_roles_resolved(
        self, account_id: str, changes: MessageUpdate
    ) -> MessageUpdate:
        """The changes with every role among ``folder_ids`` resolved."""
        if not changes.folder_ids or not any(is_role(f) for f in changes.folder_ids):
            return changes
        folders = await self.all(account_id)
        resolved = [_resolved(folders, wanted) for wanted in changes.folder_ids]
        return changes.model_copy(update={"folder_ids": resolved})

    async def _reach(
        self,
        access: Access,
        operation: str,
        account_id: str,
        folders: list[Folder] | None = None,
    ) -> Reach | None:
        return await reach_of(self._calls, access, operation, account_id, folders)

    async def _own_folder(
        self, account_id: str, folder_id: str
    ) -> tuple[Folder, list[Folder]]:
        """A folder the user made, and all the account's folders: one with
        a role is refused."""
        folders = await self.all(account_id)
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            raise missing("folder", folder_id)
        if folder.role is not None:
            raise ConflictError(
                f"the folder {folder.name} is the account's {folder.role}: "
                "it stays as it is"
            )
        return folder, folders


def is_role(folder: str) -> bool:
    return folder in FolderRole.__members__.values()


def find_folder(folders: list[Folder], wanted: str) -> Folder | None:
    """The folder with this id, or with this role."""
    return next(
        (f for f in folders if f.id == wanted or (f.role and f.role.value == wanted)),
        None,
    )


def _resolved(folders: list[Folder], folder: str) -> str:
    """A folder id as it is, or the id of the folder with that role."""
    if not is_role(folder):
        return folder
    match = find_folder(folders, folder)
    if match is None:
        raise NotFoundError(f"the account has no {folder} folder")
    return match.id
