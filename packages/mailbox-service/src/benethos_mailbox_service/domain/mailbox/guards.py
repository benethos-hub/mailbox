"""The folders the grants let a caller act on, for the messages of one
account: those out of reach, a move into other folders, a move into the
trash, which needs delete_message as well (CONCEPT 7.5), and a move into
the drafts folder, which no change makes.

The checks of one call read the account's folders and the places of its
messages once, through ``Lookups``. Where the account keeps no index, a
place is a call of the provider for each message.
"""

from __future__ import annotations

from ...data.models import Folder, FolderRole, MessageUpdate
from ...errors import BadRequestError, MailboxServiceError, missing_message
from ..rights import Access
from .calls import Calls
from .folders import Folders, in_trash
from .reach import Reach, outside, reach_of


class Lookups:
    """What the checks of one call read of an account, each at most once:
    its folders and the places of the messages ``ids``."""

    def __init__(
        self, calls: Calls, folders: Folders, account_id: str, ids: list[str]
    ) -> None:
        self._calls = calls
        self._folders = folders
        self.account_id = account_id
        self._ids = ids
        self._all: list[Folder] | None = None
        self._places: dict[str, list[str]] | None = None

    async def folders(self) -> list[Folder]:
        if self._all is None:
            self._all = await self._folders.all(self.account_id)
        return self._all

    async def places(self) -> dict[str, list[str]]:
        """Each message's folders, empty for one not found."""
        if self._places is None:
            self._places = await self._calls.places(self.account_id, self._ids)
        return self._places

    async def reach(self, access: Access, operation: str) -> Reach | None:
        """What ``operation`` reaches, None for every folder."""
        if access.folder_scopes(operation, self.account_id) is None:
            return None
        return await reach_of(
            self._calls, access, operation, self.account_id, await self.folders()
        )


class Guards:
    """The checks of ``MailboxService`` on the folders of messages."""

    def __init__(self, calls: Calls, folders: Folders) -> None:
        self._calls = calls
        self._folders = folders

    def looking(self, account_id: str, ids: list[str]) -> Lookups:
        """What the checks of one call on ``ids`` share."""
        return Lookups(self._calls, self._folders, account_id, ids)

    async def outside(
        self,
        access: Access,
        operation: str,
        looked: Lookups,
        ids: list[str],
        into: list[str] | None = None,
        replaced: list[str] | None = None,
    ) -> dict[str, MailboxServiceError]:
        """The messages of ``ids`` the grants' folders keep ``operation``
        from, each with its error: one in no folder they reach answers as
        not found, a move ``into`` other folders as forbidden, and so does
        a change that ``replaced`` a message's folders and would take it
        out of one they do not reach. Empty where the grants reach every
        folder."""
        reach = await looked.reach(access, operation)
        if reach is None:
            return {}
        places = await looked.places()
        unreached = set(_unreached(reach, places, ids))
        kept = await _kept(looked, replaced)
        refused: dict[str, MailboxServiceError] = {}
        for message_id in ids:
            found = places.get(message_id, [])
            if message_id in unreached:
                refused[message_id] = missing_message(message_id)
            elif into and not any(
                reach.holds(f, *into) for f in found if f in reach.ids
            ):
                refused[message_id] = outside(operation, "into these folders")
            elif kept is not None and any(
                f not in reach.ids and f not in kept for f in found
            ):
                refused[message_id] = outside(operation, "out of these folders")
        return refused

    async def require_reached(
        self,
        access: Access,
        operation: str,
        account_id: str,
        message_id: str,
    ) -> None:
        """``outside`` for one message, raised."""
        looked = self.looking(account_id, [message_id])
        refused = await self.outside(access, operation, looked, [message_id])
        if refused:
            raise refused[message_id]

    async def trash_refused(
        self,
        access: Access,
        looked: Lookups,
        ids: list[str],
        changes: MessageUpdate,
    ) -> dict[str, MailboxServiceError]:
        """A move into the trash, or a folder below it, is a deletion: it
        needs delete_message as well, and where the grants narrow it to
        folders, on the folder of each message, as DELETE does. Raises
        without the right at all, and answers the messages of ``ids`` it
        does not reach, each with its error. Out of the trash and into
        junk need update_message alone."""
        into = [*(changes.folder_ids or []), *(changes.add_folder_ids or [])]
        if not into:
            return {}
        account_id = looked.account_id
        scopes = access.folder_scopes("delete_message", account_id)
        if scopes is None and access.allows("delete_message", account_id):
            return {}
        if not in_trash(await looked.folders()).intersection(into):
            return {}
        access.require("delete_message", account_id)
        reach = await looked.reach(access, "delete_message")
        if reach is None:
            return {}
        return {
            message_id: outside("delete_message", "into the trash")
            for message_id in _unreached(reach, await looked.places(), ids)
        }

    async def drafts_refused(
        self, looked: Lookups, ids: list[str], changes: MessageUpdate
    ) -> dict[str, MailboxServiceError]:
        """No change puts a message into the drafts folder: the draft
        operations take what lies there for a draft, and would delete or
        send it. Answers each message of ``ids`` not there already, for
        every caller, whatever its rights."""
        into = [*(changes.folder_ids or []), *(changes.add_folder_ids or [])]
        if not into:
            return {}
        drafts = next(
            (f.id for f in await looked.folders() if f.role is FolderRole.DRAFTS),
            None,
        )
        if drafts is None or drafts not in into:
            return {}
        places = await looked.places()
        return {
            message_id: BadRequestError("a message is not moved into the drafts folder")
            for message_id in ids
            if (found := places.get(message_id)) and drafts not in found
        }


async def _kept(looked: Lookups, replaced: list[str] | None) -> set[str] | None:
    """The folders a change that ``replaced`` a message's folders leaves
    it in: those named, and the folder with the role ``all``, which a
    change never takes a message out of. None for a change that replaces
    nothing."""
    if replaced is None:
        return None
    everything = {f.id for f in await looked.folders() if f.role is FolderRole.ALL}
    return {*replaced, *everything}


def _unreached(reach: Reach, places: dict[str, list[str]], ids: list[str]) -> list[str]:
    """The messages of ``ids`` in no folder ``reach`` holds, in order."""
    return [
        message_id
        for message_id in ids
        if not any(f in reach.ids for f in places.get(message_id, []))
    ]
