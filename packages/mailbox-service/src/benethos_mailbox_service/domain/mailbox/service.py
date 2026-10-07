"""Folders and messages: of one account, and across accounts.

The service callers use for mail. Provider calls under our ids are
``calls``. Sending and drafts are ``outgoing``, reached through this
service.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any

from ...common.clock import utc_now
from ...data.models import (
    AttachmentContent,
    BatchItemResult,
    BatchResult,
    ChangePage,
    ChangeRecord,
    Folder,
    FolderCreate,
    FolderRole,
    FolderUpdate,
    ItemError,
    Message,
    MessageBatch,
    MessageFilter,
    MessagePage,
    MessageSummary,
    MessageUpdate,
    Page,
)
from ...errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    MailboxServiceError,
    NotFoundError,
    missing,
    missing_message,
)
from ..accounts import Adapters, writes
from ..activity import ActivityLog
from ..rights import Access
from ..sync import SyncService
from .across import AcrossAccounts, in_reach
from .calls import Calls, public
from .idempotency import Idempotency
from .outgoing import Outgoing
from .reach import Reach, reach_of
from .sending import SendControl

# The keyword of a draft, \Draft on IMAP.
DRAFT_KEYWORD = "$draft"


class MailboxService:
    """Callers see our stable message ids (``sync``), providers their own."""

    def __init__(
        self,
        adapters: Adapters,
        sync: SyncService,
        idempotency: Idempotency,
        sends: SendControl,
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
    ) -> None:
        self._calls = Calls(adapters, sync)
        self._changes = sync.feed
        self._across = AcrossAccounts(self._calls)
        # Sending, drafts and the audit of sends: mailbox.outgoing.send_message.
        self.outgoing = Outgoing(self._calls, idempotency, sends, clock, activity)

    # --- folders ----------------------------------------------------------------------

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        """The account's folders, those the grants reach where they name
        folders."""
        access.require("list_folders", account_id)
        folders = await self._folders(account_id)
        reach = await self._reach(access, "list_folders", account_id, folders)
        return folders if reach is None else [f for f in folders if f.id in reach.ids]

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        """Where the grants name folders, only inside one of them."""
        access.require("create_folder", account_id)
        parent = await self._folder_by_role(account_id, new.parent_id)
        reach = await self._reach(access, "create_folder", account_id)
        if reach is not None:
            if parent is None:
                raise _outside("create_folder", "at the top")
            _require_folder(reach, parent)
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
            _require_folder(reach, folder_id)
        name = changes.name or folder.name
        parent = (
            await self._folder_by_role(account_id, changes.parent_id)
            if changes.moves
            else folder.parent_id
        )
        if reach is not None and changes.moves:
            if parent is None:
                raise _outside("update_folder", "at the top")
            _require_folder(reach, parent)
            if not reach.holds(folder_id, parent):
                raise _outside("update_folder", "into the folders of another grant")
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
            _require_folder(reach, folder_id)
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

    async def _folders(self, account_id: str) -> list[Folder]:
        return await self._calls.call(account_id, lambda p: p.list_folders())

    async def _reach(
        self,
        access: Access,
        operation: str,
        account_id: str,
        folders: list[Folder] | None = None,
    ) -> Reach | None:
        return await reach_of(self._calls, access, operation, account_id, folders)

    async def _outside(
        self,
        access: Access,
        operation: str,
        account_id: str,
        ids: list[str],
        into: list[str] | None = None,
    ) -> dict[str, MailboxServiceError]:
        """The messages of ``ids`` the grants' folders keep ``operation``
        from, each with its error: one in no folder they reach answers as
        not found, a move ``into`` other folders as forbidden. Empty where
        the grants reach every folder."""
        reach = await self._reach(access, operation, account_id)
        if reach is None:
            return {}
        places = await self._calls.places(account_id, ids)
        refused: dict[str, MailboxServiceError] = {}
        for message_id in ids:
            place = [f for f in places.get(message_id, []) if f in reach.ids]
            if not place:
                refused[message_id] = missing_message(message_id)
            elif into and not any(reach.holds(f, *into) for f in place):
                refused[message_id] = _outside(operation, "into these folders")
        return refused

    async def _require_reached(
        self,
        access: Access,
        operation: str,
        account_id: str,
        message_id: str,
        into: list[str] | None = None,
    ) -> None:
        refused = await self._outside(access, operation, account_id, [message_id], into)
        if refused:
            raise refused[message_id]

    async def hearing(
        self, access: Access, account_id: str
    ) -> Callable[[ChangeRecord], bool] | None:
        """What of the account's changes the caller may hear of, None for
        all: the change feed and the webhooks."""
        reach = await self._reach(access, "list_changes", account_id)
        return reach.hears if reach is not None else None

    async def _own_folder(
        self, account_id: str, folder_id: str
    ) -> tuple[Folder, list[Folder]]:
        """A folder the user made, and all the account's folders: one with
        a role is refused."""
        folders = await self._folders(account_id)
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            raise missing("folder", folder_id)
        if folder.role is not None:
            raise ConflictError(
                f"the folder {folder.name} is the account's {folder.role}: "
                "it stays as it is"
            )
        return folder, folders

    async def _folder_by_role(self, account_id: str, folder: str | None) -> str | None:
        """A folder id, or the id of the folder with that role."""
        if folder is None or not is_role(folder):
            return folder
        return _resolved(await self._folders(account_id), folder)

    async def _folders_by_role(
        self, account_id: str, changes: MessageUpdate
    ) -> MessageUpdate:
        """The changes with every role among ``folder_ids`` resolved."""
        if not changes.folder_ids or not any(is_role(f) for f in changes.folder_ids):
            return changes
        folders = await self._folders(account_id)
        resolved = [_resolved(folders, wanted) for wanted in changes.folder_ids]
        return changes.model_copy(update={"folder_ids": resolved})

    # --- messages of one account ------------------------------------------------------

    async def list_messages(
        self,
        access: Access,
        account_id: str,
        *,
        folder_id: str | None,
        search: MessageFilter | None = None,
        limit: int,
        cursor: str | None,
    ) -> Page[MessageSummary]:
        """One account's messages, newest first. ``folder_id`` may also be a
        role such as ``inbox``."""
        access.require("list_messages", account_id)
        folder = await self._folder_by_role(account_id, folder_id)
        reach = await self._reach(access, "list_messages", account_id)
        if reach is not None and folder is not None:
            _require_folder(reach, folder)
        page = await self._calls.call(
            account_id,
            lambda p: p.list_messages(
                folder, limit=limit, cursor=cursor, search=search
            ),
        )
        if reach is not None:
            page = in_reach(page, reach)
        return await self._calls.published_page(account_id, page)

    async def get_message(
        self, access: Access, account_id: str, message_id: str
    ) -> Message:
        access.require("get_message", account_id)
        message = await self._calls.message(account_id, message_id)
        reach = await self._reach(access, "get_message", account_id)
        if reach is not None and not reach.sees(message.folder_ids):
            raise missing_message(message_id)
        if message.reference is not None and DRAFT_KEYWORD not in message.keywords:
            # Only a draft of this service carries one. In a received mail
            # the header is the sender's.
            message = message.model_copy(update={"reference": None})
        return public(message, message_id, account_id)

    async def update_message(
        self,
        access: Access,
        account_id: str,
        message_id: str,
        changes: MessageUpdate,
    ) -> MessageSummary:
        access.require("update_message", account_id)
        changes = await self._folders_by_role(account_id, changes)
        await self._require_reached(
            access, "update_message", account_id, message_id, changes.folder_ids
        )
        return await self._calls.update_one(account_id, message_id, changes)

    async def delete_message(
        self, access: Access, account_id: str, message_id: str, permanent: bool
    ) -> None:
        """Into the trash, or for good: then its own right (CONCEPT 7.5).
        Into the trash from any folder the grants reach, whether they reach
        the trash or not."""
        access.require(_delete_right(permanent), account_id)
        await self._require_reached(
            access, _delete_right(permanent), account_id, message_id
        )
        await self._calls.delete_one(account_id, message_id, permanent)

    async def batch_messages(
        self, access: Access, account_id: str, batch: MessageBatch
    ) -> BatchResult:
        """One action for many messages. The rights are those of the single
        operation, checked once for the whole batch."""
        access.require("batch_messages", account_id)
        outcomes: dict[str, Any]
        if batch.action == "update":
            access.require("update_message", account_id)
            if batch.changes is None:
                raise BadRequestError("an update needs changes")
            changes = await self._folders_by_role(account_id, batch.changes)
            outcomes = dict(
                await self._outside(
                    access, "update_message", account_id, batch.ids, changes.folder_ids
                )
            )
            rest = [i for i in batch.ids if i not in outcomes]
            if rest:
                outcomes.update(await self._calls.update(account_id, rest, changes))
        else:
            operation = _delete_right(batch.permanent)
            access.require(operation, account_id)
            outcomes = dict(
                await self._outside(access, operation, account_id, batch.ids)
            )
            rest = [i for i in batch.ids if i not in outcomes]
            if rest:
                outcomes.update(
                    await self._calls.delete(account_id, rest, batch.permanent)
                )
        return BatchResult(results=[_item(i, outcomes[i]) for i in batch.ids])

    async def get_raw(self, access: Access, account_id: str, message_id: str) -> bytes:
        access.require("get_message_raw", account_id)
        await self._require_reached(access, "get_message_raw", account_id, message_id)
        return await self._calls.on_message(
            account_id, message_id, lambda p, native: p.get_raw(native)
        )

    async def get_attachment(
        self, access: Access, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        access.require("get_attachment", account_id)
        await self._require_reached(access, "get_attachment", account_id, message_id)
        return await self._calls.attachment(account_id, message_id, attachment_id)

    # --- across accounts ---------------------------------------------------------

    # --- changes ----------------------------------------------------------------------

    async def list_changes(
        self, access: Access, account_id: str, *, since: str | None, limit: int
    ) -> ChangePage:
        """What changed in one account since a point in the change feed."""
        access.require("list_changes", account_id)
        keep = await self.hearing(access, account_id) if since else None
        return self._changes.page([account_id], since, limit=limit, keep=keep)

    async def list_all_changes(
        self,
        access: Access,
        *,
        account_ids: list[str] | None,
        since: str | None,
        limit: int,
    ) -> ChangePage:
        """What changed in several accounts since a point in the change feed.
        Accounts the caller may not read are left out without a word."""
        existing = self._calls.ids()
        visible = access.filter(
            "list_all_changes", (a for a in account_ids or existing if a in existing)
        )
        keep: Callable[[ChangeRecord], bool] | None = None
        if since:
            hearing = {a: await self.hearing(access, a) for a in visible}
            if any(h is not None for h in hearing.values()):
                keep = partial(_heard, hearing)
        return self._changes.page(visible, since, limit=limit, keep=keep)

    async def list_all_messages(
        self,
        access: Access,
        *,
        account_ids: list[str] | None,
        folder_role: FolderRole | None,
        search: MessageFilter | None = None,
        limit: int,
        cursor: str | None,
    ) -> MessagePage:
        """Messages of several accounts, merged newest first: ``across``."""
        return await self._across.list_all_messages(
            access,
            account_ids=account_ids,
            folder_role=folder_role,
            search=search,
            limit=limit,
            cursor=cursor,
        )


def is_role(folder: str) -> bool:
    return folder in FolderRole.__members__.values()


def find_folder(folders: list[Folder], wanted: str) -> Folder | None:
    """The folder with this id, or with this role."""
    return next(
        (f for f in folders if f.id == wanted or (f.role and f.role.value == wanted)),
        None,
    )


def _heard(
    hearing: dict[str, Callable[[ChangeRecord], bool] | None], record: ChangeRecord
) -> bool:
    hears = hearing.get(record.account_id)
    return hears is None or hears(record)


def _require_folder(reach: Reach, folder_id: str) -> None:
    """A folder out of reach answers as one that does not exist."""
    if folder_id not in reach.ids:
        raise missing("folder", folder_id)


def _outside(operation: str, where: str) -> ForbiddenError:
    return ForbiddenError(
        f"missing right: {operation} {where}, outside the folders of the grants"
    )


def _delete_right(permanent: bool) -> str:
    return "delete_message_permanent" if permanent else "delete_message"


def _item(message_id: str, outcome: Any) -> BatchItemResult:
    if isinstance(outcome, MailboxServiceError):
        return BatchItemResult(
            id=message_id,
            ok=False,
            error=ItemError(code=outcome.code, message=outcome.message),
        )
    summary = outcome if isinstance(outcome, MessageSummary) else None
    return BatchItemResult(id=message_id, ok=True, message=summary)


def _resolved(folders: list[Folder], folder: str) -> str:
    """A folder id as it is, or the id of the folder with that role."""
    if not is_role(folder):
        return folder
    match = find_folder(folders, folder)
    if match is None:
        raise NotFoundError(f"the account has no {folder} folder")
    return match.id
