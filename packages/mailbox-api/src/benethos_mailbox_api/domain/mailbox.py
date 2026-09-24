"""Folders and messages: of one account, and across accounts."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from ..data import mime
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
    MessagePage,
    MessageSummary,
    MessageUpdate,
    OutgoingMessage,
    Page,
    Recipient,
    SendResult,
)
from ..data.providers import MailProvider
from ..errors import BadRequestError, ConflictError, MailboxApiError, NotFoundError
from .access import Access
from .accounts import AccountService
from .idempotency import Idempotency
from .sync import SyncService

T = TypeVar("T")

_CURSOR_PREFIX = "x_"


@dataclass
class _Position:
    """Where one account stands in a list across accounts."""

    folder_id: str | None
    cursor: str | None  # the account's own cursor of the page to read next
    offset: int  # items of that page already delivered
    done: bool = False


@dataclass
class _Chunk:
    cursor: str | None
    offset: int
    items: list[MessageSummary]
    next_cursor: str | None


class MailboxService:
    """Callers see our stable message ids (``sync``), providers their own."""

    def __init__(
        self, accounts: AccountService, sync: SyncService, idempotency: Idempotency
    ) -> None:
        self._accounts = accounts
        self._sync = sync
        self._idempotency = idempotency

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        access.require("list_folders", account_id)
        return await self._call(account_id, lambda p: p.list_folders())

    async def create_folder(
        self, access: Access, account_id: str, new: FolderCreate
    ) -> Folder:
        access.require("create_folder", account_id)
        return await self._call(
            account_id, lambda p: p.create_folder(new.name, new.parent_id)
        )

    async def update_folder(
        self, access: Access, account_id: str, folder_id: str, changes: FolderUpdate
    ) -> Folder:
        """Rename or move. Folders with a role stay where mail clients expect
        them. The messages inside keep their ids: a sync follows them."""
        access.require("update_folder", account_id)
        folder = await self._own_folder(account_id, folder_id)
        name = changes.name or folder.name
        parent = changes.parent_id if changes.moves else folder.parent_id
        updated = await self._call(
            account_id, lambda p: p.update_folder(folder_id, name, parent)
        )
        if updated.id != folder_id:
            try:
                await self._sync.sync_account(account_id)
            except MailboxApiError:
                pass  # the next sync, or the next lookup, follows them
        return updated

    async def delete_folder(
        self, access: Access, account_id: str, folder_id: str
    ) -> None:
        """Only an empty folder without subfolders: deleting a folder takes
        its messages with it on many servers, and they cannot be taken back."""
        access.require("delete_folder", account_id)
        folder = await self._own_folder(account_id, folder_id)
        folders = await self._call(account_id, lambda p: p.list_folders())
        if any(f.parent_id == folder_id for f in folders):
            raise ConflictError(f"the folder {folder.name} has subfolders")
        contents = await self._call(account_id, lambda p: p.folder_contents(folder_id))
        if contents:
            raise ConflictError(
                f"the folder {folder.name} holds {len(contents)} messages: "
                "move or delete them first"
            )
        await self._call(account_id, lambda p: p.delete_folder(folder_id))

    async def _own_folder(self, account_id: str, folder_id: str) -> Folder:
        """A folder the user made: one with a role is refused."""
        folders = await self._call(account_id, lambda p: p.list_folders())
        folder = next((f for f in folders if f.id == folder_id), None)
        if folder is None:
            raise NotFoundError(f"folder {folder_id} not found")
        if folder.role is not None:
            raise ConflictError(
                f"the folder {folder.name} is the account's {folder.role}: "
                "it stays as it is"
            )
        return folder

    async def list_messages(
        self,
        access: Access,
        account_id: str,
        *,
        folder_id: str | None,
        query: str | None,
        unread: bool | None,
        limit: int,
        cursor: str | None,
    ) -> Page[MessageSummary]:
        access.require("list_messages", account_id)
        page = await self._call(
            account_id,
            lambda p: p.list_messages(
                folder_id, limit=limit, cursor=cursor, query=query, unread=unread
            ),
        )
        return Page[MessageSummary](
            items=await self._published(account_id, page.items),
            next_cursor=page.next_cursor,
        )

    async def list_all_messages(
        self,
        access: Access,
        *,
        account_ids: list[str] | None,
        folder_role: FolderRole | None,
        query: str | None,
        unread: bool | None,
        limit: int,
        cursor: str | None,
    ) -> MessagePage:
        """Messages of several accounts, merged newest first.

        Accounts the caller may not read are left out without a word, like in
        ``list_accounts``. An account that fails leaves the page incomplete,
        it does not fail the request.
        """
        existing = set(self._accounts.all_ids())
        wanted = account_ids or self._accounts.all_ids()
        visible = [
            a
            for a in dict.fromkeys(wanted)
            if a in existing and access.allows("list_all_messages", a)
        ]
        failures: list[AccountFailure] = []
        if cursor:
            positions = {
                a: p for a, p in _decode_cursor(cursor).items() if a in visible
            }
        else:
            positions = await self._start(visible, folder_role, failures)

        active = [a for a, p in positions.items() if not p.done]
        windows = await asyncio.gather(
            *(self._window(a, positions[a], query, unread, limit) for a in active),
            return_exceptions=True,
        )
        chunks: dict[str, list[_Chunk]] = {}
        for account_id, window in zip(active, windows, strict=True):
            if isinstance(window, MailboxApiError):
                failures.append(_failure(account_id, window))
            elif isinstance(window, BaseException):
                raise window
            else:
                chunks[account_id] = window

        merged = [
            (item, account_id)
            for account_id, window in chunks.items()
            for chunk in window
            for item in chunk.items
        ]
        merged.sort(key=lambda pair: _newest_first(pair[0]))
        taken = merged[:limit]
        published: dict[str, list[MessageSummary]] = {}
        for account_id, window in chunks.items():
            mine = [item for item, owner in taken if owner == account_id]
            positions[account_id] = _advance(positions[account_id], window, len(mine))
            # Only what is handed out gets our ids.
            published[account_id] = await self._published(account_id, mine)

        more = any(not p.done for p in positions.values())
        return MessagePage(
            items=[published[owner].pop(0) for _, owner in taken],
            next_cursor=_encode_cursor(positions) if more else None,
            incomplete=failures,
        )

    async def get_message(
        self, access: Access, account_id: str, message_id: str
    ) -> Message:
        access.require("get_message", account_id)
        message = await self._on_message(
            account_id, message_id, lambda p, native: p.get_message(native)
        )
        return message.model_copy(update={"id": message_id, "account_id": account_id})

    async def update_message(
        self,
        access: Access,
        account_id: str,
        message_id: str,
        changes: MessageUpdate,
    ) -> MessageSummary:
        access.require("update_message", account_id)
        outcome = (await self._update(account_id, [message_id], changes))[message_id]
        if isinstance(outcome, MailboxApiError):
            raise outcome
        return outcome

    async def delete_message(
        self, access: Access, account_id: str, message_id: str, permanent: bool
    ) -> None:
        """Into the trash, or for good: then its own right (CONCEPT 7.5)."""
        access.require(_delete_right(permanent), account_id)
        outcome = (await self._delete(account_id, [message_id], permanent))[message_id]
        if isinstance(outcome, MailboxApiError):
            raise outcome

    async def send_message(
        self,
        access: Access,
        account_id: str,
        message: OutgoingMessage,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Send from the account's address, with a fresh Date and
        Message-ID. Its own right: sending cannot be taken back. With an
        ``idempotency_key`` a retry returns the first result."""
        access.require("send_message", account_id)
        return await self._idempotency.run(
            account_id,
            idempotency_key,
            "send_message",
            message,
            lambda: self._send(account_id, message),
            SendResult,
        )

    async def _send(self, account_id: str, message: OutgoingMessage) -> SendResult:
        account = self._accounts.record(account_id)
        message_id = mime.new_message_id(account.email)
        raw = mime.compose(
            message,
            Recipient(email=account.email, name=account.display_name),
            # Local time with its offset, as mail clients write it.
            datetime.now(UTC).astimezone(),
            message_id,
        )
        sent = await self._call(
            account_id,
            lambda p: p.send(raw, account.email, message.recipients()),
        )
        copy_id = None
        if sent.sent_copy is not None:
            copy = sent.sent_copy
            folder = copy.folder_ids[0] if copy.folder_ids else ""
            [copy_id] = await self._sync.public_ids(account_id, [(copy.id, folder)])
        return SendResult(
            message_id_header=message_id, sent_copy_id=copy_id, refused=sent.refused
        )

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
            outcomes = await self._update(account_id, batch.ids, batch.changes)
        else:
            access.require(_delete_right(batch.permanent), account_id)
            outcomes = await self._delete(account_id, batch.ids, batch.permanent)
        return BatchResult(results=[_item(i, outcomes[i]) for i in batch.ids])

    # --- changing, one or many ------------------------------------------------------

    async def _update(
        self, account_id: str, ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxApiError]:
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: p.update_messages(n, changes)
        )
        results: dict[str, MessageSummary | MailboxApiError] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxApiError):
                results[message_id] = outcome
                continue
            self._follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = outcome.model_copy(
                update={"id": message_id, "account_id": account_id}
            )
        return results

    async def _delete(
        self, account_id: str, ids: list[str], permanent: bool
    ) -> dict[str, None | MailboxApiError]:
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: p.delete_messages(n, permanent)
        )
        results: dict[str, None | MailboxApiError] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxApiError):
                results[message_id] = outcome
                continue
            if permanent:
                self._sync.forget(account_id, message_id)
            elif outcome is not None:
                self._follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = None
        return results

    async def _on_messages(
        self,
        account_id: str,
        ids: list[str],
        run: Callable[[MailProvider, list[str]], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Run a provider operation on the messages behind ``ids``. Those
        the provider does not find where the index says get one sync and a
        second try. Returns the outcome per id and the provider id used."""
        natives = {i: n for i, n in self._sync.natives(account_id, ids).items() if n}
        outcomes: dict[str, Any] = {
            i: NotFoundError(f"message {i} not found") for i in ids if i not in natives
        }
        outcomes.update(await self._run_on(account_id, natives, run))
        missing = [i for i in natives if isinstance(outcomes[i], NotFoundError)]
        if missing and self._sync.mapped(account_id):
            await self._sync.sync_account(account_id)
            moved = {
                i: n
                for i, n in self._sync.natives(account_id, missing).items()
                if n and n != natives[i]
            }
            outcomes.update(await self._run_on(account_id, moved, run))
            natives.update(moved)
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, NotFoundError):
                outcomes[message_id] = NotFoundError(f"message {message_id} not found")
        return outcomes, natives

    async def _run_on(
        self,
        account_id: str,
        natives: dict[str, str],
        run: Callable[[MailProvider, list[str]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not natives:
            return {}
        by_native = await self._call(
            account_id, lambda p: run(p, list(natives.values()))
        )
        missing = NotFoundError("message not found")
        return {i: by_native.get(n, missing) for i, n in natives.items()}

    def _follow(
        self, account_id: str, message_id: str, native: str, now: MessageSummary
    ) -> None:
        """A message the provider moved: its id points to the new place."""
        if now.id != native:
            folder = now.folder_ids[0] if now.folder_ids else ""
            self._sync.relocate(account_id, message_id, now.id, folder)

    async def get_raw(self, access: Access, account_id: str, message_id: str) -> bytes:
        access.require("get_message_raw", account_id)
        return await self._on_message(
            account_id, message_id, lambda p, native: p.get_raw(native)
        )

    async def get_attachment(
        self, access: Access, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        access.require("get_attachment", account_id)
        return await self._on_message(
            account_id,
            message_id,
            lambda p, native: p.get_attachment(native, attachment_id),
        )

    # --- ids -------------------------------------------------------------------------

    async def _published(
        self, account_id: str, items: list[MessageSummary]
    ) -> list[MessageSummary]:
        """The provider's summaries with our ids and the account."""
        ids = await self._sync.public_ids(
            account_id,
            [(i.id, i.folder_ids[0] if i.folder_ids else "") for i in items],
        )
        return [
            item.model_copy(update={"id": public, "account_id": account_id})
            for item, public in zip(items, ids, strict=True)
        ]

    async def _on_message(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[MailProvider, str], Awaitable[T]],
    ) -> T:
        return await self._sync.resolve(
            account_id,
            message_id,
            lambda native: self._call(account_id, lambda p: operation(p, native)),
        )

    # --- across accounts ---------------------------------------------------------

    async def _start(
        self,
        account_ids: list[str],
        role: FolderRole | None,
        failures: list[AccountFailure],
    ) -> dict[str, _Position]:
        if role is None:
            return {a: _Position(None, None, 0) for a in account_ids}
        folders = await asyncio.gather(
            *(self._call(a, lambda p: p.list_folders()) for a in account_ids),
            return_exceptions=True,
        )
        positions = {}
        for account_id, found in zip(account_ids, folders, strict=True):
            if isinstance(found, MailboxApiError):
                failures.append(_failure(account_id, found))
            elif isinstance(found, BaseException):
                raise found
            else:
                match = next((f for f in found if f.role is role), None)
                if match is not None:
                    positions[account_id] = _Position(match.id, None, 0)
        return positions

    async def _window(
        self,
        account_id: str,
        position: _Position,
        query: str | None,
        unread: bool | None,
        limit: int,
    ) -> list[_Chunk]:
        """At least ``limit`` of the account's next messages, or all it has
        left, so that merging by date cannot skip a newer one."""

        async def page(cursor: str | None) -> Page[MessageSummary]:
            return await self._call(
                account_id,
                lambda p: p.list_messages(
                    position.folder_id,
                    limit=limit,
                    cursor=cursor,
                    query=query,
                    unread=unread,
                ),
            )

        first = await page(position.cursor)
        chunks = [
            _Chunk(
                position.cursor,
                position.offset,
                first.items[position.offset :],
                first.next_cursor,
            )
        ]
        if len(chunks[0].items) < limit and first.next_cursor:
            second = await page(first.next_cursor)
            chunks.append(
                _Chunk(first.next_cursor, 0, second.items, second.next_cursor)
            )
        return chunks

    async def _call(
        self, account_id: str, operation: Callable[[MailProvider], Awaitable[T]]
    ) -> T:
        """Run one provider operation and keep the account's status in step
        with how it went."""
        return await self._accounts.observe(
            account_id, operation(self._accounts.provider(account_id))
        )


def _newest_first(item: MessageSummary) -> tuple[bool, float]:
    return (item.date is None, -item.date.timestamp() if item.date else 0.0)


def _advance(position: _Position, window: list[_Chunk], consumed: int) -> _Position:
    for chunk in window:
        if consumed < len(chunk.items):
            return _Position(position.folder_id, chunk.cursor, chunk.offset + consumed)
        consumed -= len(chunk.items)
    last = window[-1].next_cursor
    if last is None:
        return _Position(position.folder_id, None, 0, done=True)
    return _Position(position.folder_id, last, 0)


def _failure(account_id: str, error: MailboxApiError) -> AccountFailure:
    return AccountFailure(account_id=account_id, code=error.code, message=error.message)


def _encode_cursor(positions: dict[str, _Position]) -> str:
    state = {a: [p.folder_id, p.cursor, p.offset, p.done] for a, p in positions.items()}
    raw = json.dumps(state, separators=(",", ":")).encode()
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> dict[str, _Position]:
    if not value.startswith(_CURSOR_PREFIX):
        raise BadRequestError("invalid cursor")
    text = value[len(_CURSOR_PREFIX) :]
    try:
        state = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        return {
            account_id: _Position(folder_id, cursor, int(offset), bool(done))
            for account_id, (folder_id, cursor, offset, done) in state.items()
        }
    except (binascii.Error, ValueError, TypeError, AttributeError):
        raise BadRequestError("invalid cursor") from None


def _delete_right(permanent: bool) -> str:
    return "delete_message_permanent" if permanent else "delete_message"


def _item(message_id: str, outcome: Any) -> BatchItemResult:
    if isinstance(outcome, MailboxApiError):
        return BatchItemResult(
            id=message_id,
            ok=False,
            error=ItemError(code=outcome.code, message=outcome.message),
        )
    summary = outcome if isinstance(outcome, MessageSummary) else None
    return BatchItemResult(id=message_id, ok=True, message=summary)
