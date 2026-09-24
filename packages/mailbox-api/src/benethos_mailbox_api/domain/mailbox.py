"""Folders and messages: of one account, and across accounts."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from ..data.models import (
    AccountFailure,
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessagePage,
    MessageSummary,
    Page,
)
from ..data.providers import MailProvider
from ..errors import BadRequestError, MailboxApiError
from .access import Access
from .accounts import AccountService
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

    def __init__(self, accounts: AccountService, sync: SyncService) -> None:
        self._accounts = accounts
        self._sync = sync

    async def list_folders(self, access: Access, account_id: str) -> list[Folder]:
        access.require("list_folders", account_id)
        return await self._call(account_id, lambda p: p.list_folders())

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
