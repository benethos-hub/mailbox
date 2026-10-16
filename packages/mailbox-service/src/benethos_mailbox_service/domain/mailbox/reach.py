"""The folders a caller reaches, where its grants name folders
(PERMISSIONS.md 8.5).

A grant's ``folders`` names folders by role, name or id. A listed folder
reaches its subfolders as well. The IMAP adapter puts the folders of a
server that keeps them below the inbox (``INBOX.Sent``) at the top, as
mail clients show them, so ``inbox`` reaches no more than the inbox
there. The folder with the role ``all`` reaches every folder but the
trash and junk, as it lists them. A call passes when one grant that
allows it reaches every folder
the call touches. A caller with a grant that reaches every folder has no
``Reach``: nothing is checked or filtered for it, and nothing is asked
of the provider.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...data.models import ChangeRecord, Folder, FolderRole
from ...errors import ForbiddenError, missing
from ..rights import Access
from .calls import Calls


class Reach:
    """The folders of one account that one operation reaches, per grant."""

    def __init__(self, scopes: list[frozenset[str]], folders: list[Folder]) -> None:
        by_id = {folder.id: folder for folder in folders}
        self._grants = [
            _beside_all(
                frozenset(f.id for f in folders if _within(f, scope, by_id)), folders
            )
            for scope in scopes
        ]
        # Every folder some grant reaches.
        self.ids: frozenset[str] = frozenset().union(*self._grants)

    def sees(self, folder_ids: Iterable[str]) -> bool:
        """Whether a message in these folders is in reach: in one of them."""
        return any(folder_id in self.ids for folder_id in folder_ids)

    def holds(self, *folder_ids: str) -> bool:
        """Whether one grant reaches all of these: a move between them."""
        return any(all(f in grant for f in folder_ids) for grant in self._grants)

    def hears(self, record: ChangeRecord) -> bool:
        """Whether a change of the change log is in reach. A deletion of
        unknown place names an id and nothing else, and goes to everyone
        who may read the account. A change of the account is not about a
        folder."""
        if not record.type.startswith("message."):
            return True
        if record.folder_id is None:
            return record.type == "message.deleted"
        return record.folder_id in self.ids


def of_the_account(record: ChangeRecord) -> bool | None:
    """What is heard of an account whose folders cannot be read now: a
    change that is not about a message, and of one about a message None,
    not known yet."""
    return None if record.type.startswith("message.") else True


async def reach_of(
    calls: Calls,
    access: Access,
    operation: str,
    account_id: str,
    folders: list[Folder] | None = None,
) -> Reach | None:
    """What ``operation`` reaches on the account, None for every folder.
    ``folders``: the account's folders, if the caller has them already."""
    scopes = access.folder_scopes(operation, account_id)
    if scopes is None:
        return None
    if folders is None:
        folders = await calls.call(account_id, lambda p: p.list_folders())
    return Reach(scopes, folders)


def require_folder(reach: Reach, folder_id: str) -> None:
    """A folder out of reach answers as one that does not exist."""
    if folder_id not in reach.ids:
        raise missing("folder", folder_id)


def outside(operation: str, where: str) -> ForbiddenError:
    return ForbiddenError(
        f"missing right: {operation} {where}, outside the folders of the grants"
    )


def _beside_all(reached: frozenset[str], folders: list[Folder]) -> frozenset[str]:
    """Where a grant reaches the folder ``all``, every folder but the trash
    and junk as well: the messages it lists lie there."""
    if not any(f.role is FolderRole.ALL and f.id in reached for f in folders):
        return reached
    outside = (FolderRole.TRASH, FolderRole.JUNK)
    return reached | {f.id for f in folders if f.role not in outside}


def _within(folder: Folder, names: frozenset[str], by_id: dict[str, Folder]) -> bool:
    """Whether the folder or one above it is named: by id, name or role."""
    seen: set[str] = set()
    current: Folder | None = folder
    while current is not None and current.id not in seen:
        if (
            current.id in names
            or current.name in names
            or (current.role is not None and current.role.value in names)
        ):
            return True
        seen.add(current.id)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return False
