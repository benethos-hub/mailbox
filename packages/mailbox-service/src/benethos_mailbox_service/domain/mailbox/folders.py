"""The folders of one account: listed, created, renamed, moved and
deleted under the caller's rights and the folders its grants reach, and
a role such as ``inbox`` read as the folder that has it.

Reached through ``MailboxService``, which uses the roles for messages
too.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress

from ...data.models import (
    Folder,
    FolderCreate,
    FolderRole,
    FolderUpdate,
    MessageUpdate,
)
from ...errors import (
    ConflictError,
    MailboxServiceError,
    NotSupportedError,
    missing,
)
from ..accounts import NEEDS, writes
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
        reach = await reach_of(self._calls, access, "list_folders", account_id, folders)
        return folders if reach is None else [f for f in folders if f.id in reach.ids]

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        """Where the grants name folders, only inside one of them."""
        access.require("create_folder", account_id)
        await self._calls.require(account_id, NEEDS["create_folder"])
        parent = await self.by_role(account_id, new.parent_id)
        reach = await reach_of(self._calls, access, "create_folder", account_id)
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
        await self._calls.require(account_id, NEEDS["update_folder"])
        folder, folders, reach = await self._own_folder(
            access, "update_folder", account_id, folder_id
        )
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
            # Where it fails, the next sync, or the next lookup, follows them.
            with suppress(MailboxServiceError):
                await self._calls.resync(account_id)
        return updated

    async def delete_folder(
        self, access: Access, account_id: str, folder_id: str
    ) -> None:
        """Only an empty folder without subfolders: deleting a folder takes
        its messages with it on many servers, and they cannot be taken back."""
        access.require("delete_folder", account_id)
        await self._calls.require(account_id, NEEDS["delete_folder"])
        folder, folders, _ = await self._own_folder(
            access, "delete_folder", account_id, folder_id
        )
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
        return None if folder is None else await self.resolved(account_id, folder)

    async def resolved(self, account_id: str, folder: str) -> str:
        """A folder id, or the id of the folder with that role: ``501``
        where the account has none."""
        if not is_role(folder):
            return folder
        return _resolved(await self.all(account_id), folder)

    async def listed(
        self, access: Access, account_id: str, folder: str
    ) -> tuple[str, Reach | None]:
        """The folder whose messages are listed, a role resolved, and what
        the grants reach. One the account lacks or out of reach is
        missing, but the folder ``all``, which lists what they reach of
        every folder. The account's folders are asked for once."""
        folders = await self.all(account_id)
        folder = _resolved(folders, folder)
        if not any(f.id == folder for f in folders):
            raise missing("folder", folder)
        reach = await reach_of(
            self._calls, access, "list_messages", account_id, folders
        )
        if reach is not None and not _is_all(folders, folder):
            require_folder(reach, folder)
        return folder, reach

    async def with_roles_resolved(
        self, account_id: str, changes: MessageUpdate
    ) -> MessageUpdate:
        """The changes with every role among the folders they name
        resolved."""
        if not any(is_role(f) for f in changes.named_folders()):
            return changes
        folders = await self.all(account_id)
        fields = ("folder_ids", "add_folder_ids", "remove_folder_ids")
        return changes.model_copy(
            update={
                field: [_resolved(folders, wanted) for wanted in named]
                for field in fields
                if (named := getattr(changes, field))
            }
        )

    async def _own_folder(
        self, access: Access, operation: str, account_id: str, folder_id: str
    ) -> tuple[Folder, list[Folder], Reach | None]:
        """A folder the user made, all the account's folders and the
        caller's reach for ``operation``. A folder outside the reach is
        missing before one with a role is refused, so that its name stays
        unknown."""
        folders = await self.all(account_id)
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            raise missing("folder", folder_id)
        reach = await reach_of(self._calls, access, operation, account_id, folders)
        if reach is not None:
            require_folder(reach, folder_id)
        if folder.role is not None:
            raise ConflictError(
                f"the folder {folder.name} is the account's {folder.role}: "
                "it stays as it is"
            )
        return folder, folders, reach


def holder(folders: list[Folder], folder_id: str) -> Callable[[Iterable[str]], bool]:
    """Whether a message in these folders is in ``folder_id``. The folder
    with the role ``all`` holds every message but those in the trash and
    junk, which carry no id of it."""
    found = find_folder(folders, folder_id)
    if found is None or found.role is not FolderRole.ALL:
        return lambda folder_ids: folder_id in folder_ids
    outside = {f.id for f in folders if f.role in (FolderRole.TRASH, FolderRole.JUNK)}
    return lambda folder_ids: not outside.intersection(folder_ids)


def is_role(folder: str) -> bool:
    return folder in FolderRole.__members__.values()


def find_folder(folders: list[Folder], wanted: str) -> Folder | None:
    """The folder with this id, or with this role."""
    return next(
        (f for f in folders if f.id == wanted or (f.role and f.role.value == wanted)),
        None,
    )


def _is_all(folders: list[Folder], folder_id: str) -> bool:
    """Whether the folder is the one with the role ``all``."""
    found = find_folder(folders, folder_id)
    return found is not None and found.role is FolderRole.ALL


def _resolved(folders: list[Folder], folder: str) -> str:
    """A folder id as it is, or the id of the folder with that role."""
    if not is_role(folder):
        return folder
    match = find_folder(folders, folder)
    if match is None:
        raise NotSupportedError(f"the account has no {folder} folder")
    return match.id
