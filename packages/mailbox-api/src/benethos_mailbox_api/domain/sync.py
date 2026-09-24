"""Stable message ids, and the sync that keeps them (CONCEPT 4.1, 8.1).

A provider without ``STABLE_IDS`` names a message by its place, e.g. IMAP
folder, UIDVALIDITY and UID. Callers get our own id instead, kept in the
index. A sync pass compares the provider's folders with the index: a message
that left one folder and one with the same ``Message-ID`` that arrived in
another is the same message and keeps its id. Anything ambiguous is not
guessed: the old id is dropped and the new place gets a new one.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from typing import TypeVar

from ..data.providers import Capability
from ..data.storage import IndexChanges, IndexEntry, MessageIndexRepository
from ..errors import MailboxApiError, NotFoundError
from .accounts import AccountService

T = TypeVar("T")


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:16]}"


class SyncService:
    def __init__(
        self,
        accounts: AccountService,
        index: MessageIndexRepository,
        new_id: Callable[[], str] = new_message_id,
    ) -> None:
        self._accounts = accounts
        self._index = index
        self._new_id = new_id
        self._locks: dict[str, asyncio.Lock] = {}

    def mapped(self, account_id: str) -> bool:
        """Whether the account's ids go through the index."""
        provider = self._accounts.provider(account_id)
        return Capability.STABLE_IDS not in provider.capabilities

    # --- ids ------------------------------------------------------------------------

    async def public_ids(
        self, account_id: str, places: Iterable[tuple[str, str]]
    ) -> list[str]:
        """Our ids for provider ids, each with its folder. Unknown ones get a
        new id, with their ``Message-ID`` read right away: a message moved
        before the next sync can only be followed by it."""
        places = list(places)
        if not self.mapped(account_id):
            return [native for native, _ in places]
        natives = [native for native, _ in places]
        known = self._index.by_native(account_id, natives)
        missing = [(n, f) for n, f in dict(places).items() if n not in known]
        if missing:
            headers = await self._headers(account_id, [n for n, _ in missing])
            self._index.add(
                account_id,
                [IndexEntry(self._new_id(), n, f, headers.get(n)) for n, f in missing],
            )
            # Read back: a sync may have added the same place meanwhile.
            known = self._index.by_native(account_id, natives)
        return [known[native].id for native in natives]

    async def resolve(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[str], Awaitable[T]],
    ) -> T:
        """Run ``operation`` with the provider's id of a message. If the
        provider no longer finds it there, sync once and try its new place."""
        if not self.mapped(account_id):
            return await operation(message_id)
        native = self._native(account_id, message_id)
        try:
            return await operation(native)
        except NotFoundError:
            await self.sync_account(account_id)
            entry = self._index.get(account_id, message_id)
            if entry is None or entry.native_id == native:
                raise NotFoundError(f"message {message_id} not found") from None
            return await operation(entry.native_id)

    def relocate(
        self, account_id: str, message_id: str, native: str, folder_id: str
    ) -> None:
        """We moved a message ourselves: its id now points to the new place."""
        if not self.mapped(account_id):
            return
        entry = self._index.get(account_id, message_id)
        if entry is not None:
            self._index.relocate(
                account_id, replace(entry, native_id=native, folder_id=folder_id)
            )

    async def _headers(
        self, account_id: str, natives: list[str]
    ) -> dict[str, str | None]:
        """Best effort: without the headers the listing still works, the next
        sync reads them."""
        provider = self._accounts.provider(account_id)
        try:
            return await self._accounts.observe(
                account_id, provider.message_headers(natives)
            )
        except MailboxApiError:
            return {}

    def _native(self, account_id: str, message_id: str) -> str:
        entry = self._index.get(account_id, message_id)
        if entry is None:
            raise NotFoundError(f"message {message_id} not found")
        return entry.native_id

    # --- sync -------------------------------------------------------------------------

    async def sync_account(self, account_id: str) -> None:
        """Bring the index of one account up to date. Reads only the folders
        whose state changed. A failure changes nothing."""
        if not self.mapped(account_id):
            return
        lock = self._locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            await self._sync(account_id)

    async def _sync(self, account_id: str) -> None:
        provider = self._accounts.provider(account_id)

        def observe(operation: Awaitable[T]) -> Awaitable[T]:
            return self._accounts.observe(account_id, operation)

        states = await observe(provider.folder_states())
        before = self._index.folder_states(account_id)
        changed = [f for f, state in states.items() if before.get(f) != state]
        vanished = [f for f in before if f not in states]
        if not changed and not vanished:
            return

        present: dict[str, str] = {}  # provider id -> folder
        for folder_id in changed:
            for native in await observe(provider.folder_contents(folder_id)):
                present[native] = folder_id
        entries = self._index.in_folders(account_id, changed + vanished)
        indexed = {e.native_id for e in entries}
        arrived = [n for n in present if n not in indexed]
        left = [e for e in entries if e.native_id not in present]
        unread_headers = [
            e.native_id for e in entries if e.header is None and e.native_id in present
        ]
        wanted = arrived + unread_headers
        headers = await observe(provider.message_headers(wanted)) if wanted else {}

        changes = IndexChanges(states=states)
        for entry in entries:
            header = headers.get(entry.native_id)
            if entry.native_id in present and entry.header is None and header:
                changes.updated.append(replace(entry, header=header))

        moved = _moves(left, arrived, headers)
        for old, native in moved.items():
            changes.updated.append(
                IndexEntry(old.id, native, present[native], old.header)
            )
        taken = set(moved.values())
        changes.removed = [e.id for e in left if e not in moved]
        changes.added = [
            IndexEntry(self._new_id(), n, present[n], headers.get(n))
            for n in arrived
            if n not in taken
        ]
        self._index.apply(account_id, changes)


def _moves(
    left: list[IndexEntry], arrived: list[str], headers: dict[str, str | None]
) -> dict[IndexEntry, str]:
    """Which message that left is which one that arrived: same
    ``Message-ID``, and exactly one on each side."""
    gone: dict[str, list[IndexEntry]] = {}
    for entry in left:
        if entry.header:
            gone.setdefault(entry.header, []).append(entry)
    came: dict[str, list[str]] = {}
    for native in arrived:
        header = headers.get(native)
        if header:
            came.setdefault(header, []).append(native)
    return {
        olds[0]: came[header][0]
        for header, olds in gone.items()
        if len(olds) == 1 and len(came.get(header, [])) == 1
    }
