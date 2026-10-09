"""Folders and messages: of one account, and across accounts.

The service callers use for mail. Provider calls under our ids are
``calls``. The folders are ``folders``, sending and drafts
``outgoing``, both reached through this service.
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
from ...errors import BadRequestError, MailboxServiceError, missing_message
from ..accounts import Adapters
from ..activity import ActivityLog
from ..rights import Access
from ..sync import SyncService
from .across import AcrossAccounts, in_reach
from .calls import Calls, public
from .folders import Folders
from .idempotency import Idempotency
from .outgoing import Outgoing
from .reach import Reach, outside, reach_of, require_folder
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
        self._folders = Folders(self._calls)
        # Sending, drafts and the audit of sends: mailbox.outgoing.send_message.
        self.outgoing = Outgoing(self._calls, idempotency, sends, clock, activity)

    # --- folders ----------------------------------------------------------------------

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        """The account's folders, those the grants reach where they name
        folders."""
        return await self._folders.list_folders(access, account_id)

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        """Where the grants name folders, only inside one of them."""
        return await self._folders.create_folder(access, account_id, new)

    async def update_folder(
        self, access: Access, account_id: str, folder_id: str, changes: FolderUpdate
    ) -> Folder:
        """Rename or move. Folders with a role stay where mail clients expect
        them. The messages inside keep their ids: a sync follows them."""
        return await self._folders.update_folder(access, account_id, folder_id, changes)

    async def delete_folder(
        self, access: Access, account_id: str, folder_id: str
    ) -> None:
        """Only an empty folder without subfolders: deleting a folder takes
        its messages with it on many servers, and they cannot be taken back."""
        await self._folders.delete_folder(access, account_id, folder_id)

    # --- the folders the grants reach -------------------------------------------------

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
                refused[message_id] = outside(operation, "into these folders")
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
        folder = await self._folders.by_role(account_id, folder_id)
        reach = await self._reach(access, "list_messages", account_id)
        if reach is not None and folder is not None:
            require_folder(reach, folder)
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
        changes = await self._folders.with_roles_resolved(account_id, changes)
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
            changes = await self._folders.with_roles_resolved(account_id, batch.changes)
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


def _heard(
    hearing: dict[str, Callable[[ChangeRecord], bool] | None], record: ChangeRecord
) -> bool:
    hears = hearing.get(record.account_id)
    return hears is None or hears(record)


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
