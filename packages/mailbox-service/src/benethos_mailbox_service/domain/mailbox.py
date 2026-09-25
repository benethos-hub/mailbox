"""Folders and messages: of one account, and across accounts.

The service callers use for mail. Provider calls under our ids are
``calls``. Sending and drafts are ``outgoing``, reached through this
service.
"""

from __future__ import annotations

import logging
from typing import Any

from ..data.models import (
    AccountFailure,
    AttachmentContent,
    BatchItemResult,
    BatchResult,
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
from ..errors import ConflictError, MailboxServiceError, NotFoundError
from . import merge
from .access import Access
from .adapters import Adapters
from .calls import Calls, public
from .idempotency import Idempotency
from .outgoing import Outgoing
from .sending import SendControl
from .sync import SyncService

# The keyword of a draft, \Draft on IMAP.
DRAFT_KEYWORD = "$draft"

log = logging.getLogger(__name__)


class MailboxService:
    """Callers see our stable message ids (``sync``), providers their own."""

    def __init__(
        self,
        adapters: Adapters,
        sync: SyncService,
        idempotency: Idempotency,
        sends: SendControl,
    ) -> None:
        self._calls = Calls(adapters, sync)
        self._outgoing = Outgoing(self._calls, idempotency, sends)
        # Sending and drafts live in ``Outgoing``. Callers reach them here.
        self.send_message = self._outgoing.send_message
        self.list_sends = self._outgoing.list_sends
        self.list_drafts = self._outgoing.list_drafts
        self.create_draft = self._outgoing.create_draft
        self.update_draft = self._outgoing.update_draft
        self.send_draft = self._outgoing.send_draft
        self.delete_draft = self._outgoing.delete_draft
        self.list_all_sends = self._outgoing.list_all_sends

    # --- folders ----------------------------------------------------------------------

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        access.require("list_folders", account_id)
        return await self._folders(account_id)

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        access.require("create_folder", account_id)
        parent = await self._folder_by_role(account_id, new.parent_id)
        return await self._calls.call(
            account_id, lambda p: p.create_folder(new.name, parent)
        )

    async def update_folder(
        self, access: Access, account_id: str, folder_id: str, changes: FolderUpdate
    ) -> Folder:
        """Rename or move. Folders with a role stay where mail clients expect
        them. The messages inside keep their ids: a sync follows them."""
        access.require("update_folder", account_id)
        folder, _ = await self._own_folder(account_id, folder_id)
        name = changes.name or folder.name
        parent = changes.parent_id if changes.moves else folder.parent_id
        updated = await self._calls.call(
            account_id, lambda p: p.update_folder(folder_id, name, parent)
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
        await self._calls.call(account_id, lambda p: p.delete_folder(folder_id))

    async def _folders(self, account_id: str) -> list[Folder]:
        return await self._calls.call(account_id, lambda p: p.list_folders())

    async def _own_folder(
        self, account_id: str, folder_id: str
    ) -> tuple[Folder, list[Folder]]:
        """A folder the user made, and all the account's folders: one with
        a role is refused."""
        folders = await self._folders(account_id)
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            raise NotFoundError(f"folder {folder_id} not found")
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
        match = find_folder(await self._folders(account_id), folder)
        if match is None:
            raise NotFoundError(f"the account has no {folder} folder")
        return match.id

    async def _folders_by_role(
        self, account_id: str, changes: MessageUpdate
    ) -> MessageUpdate:
        """The changes with every role among ``folder_ids`` resolved."""
        if not changes.folder_ids or not any(is_role(f) for f in changes.folder_ids):
            return changes
        folders = await self._folders(account_id)
        resolved = []
        for wanted in changes.folder_ids:
            match = find_folder(folders, wanted) if is_role(wanted) else None
            if is_role(wanted) and match is None:
                raise NotFoundError(f"the account has no {wanted} folder")
            resolved.append(match.id if match is not None else wanted)
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
        page = await self._calls.call(
            account_id,
            lambda p: p.list_messages(
                folder, limit=limit, cursor=cursor, search=search
            ),
        )
        return await self._calls.published_page(account_id, page)

    async def get_message(
        self, access: Access, account_id: str, message_id: str
    ) -> Message:
        access.require("get_message", account_id)
        message = await self._calls.message(account_id, message_id)
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
        return await self._calls.update_one(account_id, message_id, changes)

    async def delete_message(
        self, access: Access, account_id: str, message_id: str, permanent: bool
    ) -> None:
        """Into the trash, or for good: then its own right (CONCEPT 7.5)."""
        access.require(_delete_right(permanent), account_id)
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
            assert batch.changes is not None
            changes = await self._folders_by_role(account_id, batch.changes)
            outcomes = await self._calls.update(account_id, batch.ids, changes)
        else:
            access.require(_delete_right(batch.permanent), account_id)
            outcomes = await self._calls.delete(account_id, batch.ids, batch.permanent)
        return BatchResult(results=[_item(i, outcomes[i]) for i in batch.ids])

    async def get_raw(self, access: Access, account_id: str, message_id: str) -> bytes:
        access.require("get_message_raw", account_id)
        return await self._calls.on_message(
            account_id, message_id, lambda p, native: p.get_raw(native)
        )

    async def get_attachment(
        self, access: Access, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        access.require("get_attachment", account_id)
        return await self._calls.attachment(account_id, message_id, attachment_id)

    # --- across accounts ---------------------------------------------------------

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
        """Messages of several accounts, merged newest first.

        Accounts the caller may not read are left out without a word, like in
        ``list_accounts``. An account that fails leaves the page incomplete,
        it does not fail the request.
        """
        existing = self._calls.ids()
        wanted = account_ids or existing
        visible = [
            a
            for a in dict.fromkeys(wanted)
            if a in existing and access.allows("list_all_messages", a)
        ]
        failures: list[AccountFailure] = []
        if cursor:
            positions = {
                a: p for a, p in merge.decode_cursor(cursor).items() if a in visible
            }
        else:
            positions = await self._start(visible, folder_role, failures)

        chunks = await merge.per_account(
            [a for a, p in positions.items() if not p.done],
            lambda a: self._window(a, positions[a], search, limit),
            failures,
        )
        # An account that failed is named in ``failures`` and keeps its place
        # while others deliver, to join again later. Once every account
        # still open has failed, the list ends: a cursor that promises more
        # from accounts that do not answer would promise it forever.
        if not chunks:
            positions = {
                a: merge.Position(p.folder_id, None, 0, done=True)
                for a, p in positions.items()
            }

        merged = [
            (item, account_id)
            for account_id, window in chunks.items()
            for chunk in window
            for item in chunk.items
        ]
        merged.sort(key=lambda pair: merge.newest_first(pair[0]))
        taken = merged[:limit]
        published: dict[str, list[MessageSummary]] = {}
        for account_id, window in chunks.items():
            mine = [item for item, owner in taken if owner == account_id]
            positions[account_id] = merge.advance(
                positions[account_id], window, len(mine)
            )
            # Only what is handed out gets our ids.
            published[account_id] = await self._calls.published(account_id, mine)

        more = any(not p.done for p in positions.values())
        return MessagePage(
            items=[published[owner].pop(0) for _, owner in taken],
            next_cursor=merge.encode_cursor(positions) if more else None,
            incomplete=failures,
        )

    async def _start(
        self,
        account_ids: list[str],
        role: FolderRole | None,
        failures: list[AccountFailure],
    ) -> dict[str, merge.Position]:
        if role is None:
            return {a: merge.Position(None, None, 0) for a in account_ids}
        folders = await merge.per_account(account_ids, self._folders, failures)
        positions = {}
        for account_id, found in folders.items():
            match = next((f for f in found if f.role is role), None)
            if match is not None:
                positions[account_id] = merge.Position(match.id, None, 0)
        return positions

    async def _window(
        self,
        account_id: str,
        position: merge.Position,
        search: MessageFilter | None,
        limit: int,
    ) -> list[merge.Chunk]:
        """At least ``limit`` of the account's next messages, or all it has
        left, so that merging by date cannot skip a newer one."""

        async def page(cursor: str | None) -> Page[MessageSummary]:
            return await self._calls.call(
                account_id,
                lambda p: p.list_messages(
                    position.folder_id,
                    limit=limit,
                    cursor=cursor,
                    search=search,
                ),
            )

        first = await page(position.cursor)
        chunks = [
            merge.Chunk(
                position.cursor,
                position.offset,
                first.items[position.offset :],
                first.next_cursor,
            )
        ]
        if len(chunks[0].items) < limit and first.next_cursor:
            second = await page(first.next_cursor)
            chunks.append(
                merge.Chunk(first.next_cursor, 0, second.items, second.next_cursor)
            )
        return chunks


def is_role(folder: str) -> bool:
    return folder in FolderRole.__members__.values()


def find_folder(folders: list[Folder], wanted: str) -> Folder | None:
    """The folder with this id, or with this role."""
    return next(
        (f for f in folders if f.id == wanted or (f.role and f.role.value == wanted)),
        None,
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
