"""The folders a caller reaches, where its grants name folders
(PERMISSIONS.md 8.5).

A grant's ``folders`` names folders by role, name or id. A listed folder
reaches its subfolders as well. The IMAP adapter puts the folders of a
server that keeps them below the inbox (``INBOX.Sent``) at the top, as
mail clients show them, so ``inbox`` reaches no more than the inbox
there. A call passes when one grant that allows it reaches every folder
the call touches. A caller with a grant that reaches every folder has no
``Reach``: nothing is checked or filtered for it, and nothing is asked
of the provider.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...data.models import ChangeRecord, Folder
from ..rights import Access
from .calls import Calls


class Reach:
    """The folders of one account that one operation reaches, per grant."""

    def __init__(self, scopes: list[frozenset[str]], folders: list[Folder]) -> None:
        by_id = {folder.id: folder for folder in folders}
        self._grants = [
            frozenset(f.id for f in folders if _within(f, scope, by_id))
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
