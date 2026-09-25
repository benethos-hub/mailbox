"""Stable message ids, and the sync that keeps them (CONCEPT 4.1, 8.1).

A provider without ``STABLE_IDS`` names a message by its place, e.g. IMAP
folder, UIDVALIDITY and UID. Callers get our own id instead, kept in the
index. A sync pass compares the provider's folders with the index: a message
that left one folder and one with the same ``Message-ID`` that arrived in
another is the same message and keeps its id. Anything ambiguous is not
guessed: the old id is dropped and the new place gets a new one.

What a pass finds goes into the change feed: new messages as created,
moved ones as updated, vanished ones as deleted. The first pass of an
account records nothing, since the messages already there are not new.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from typing import TypeVar

from ..common.ids import new_id
from ..data.models import ChangeType
from ..data.providers import Capability, MailProvider
from ..data.storage import IndexChanges, IndexEntry, MessageIndexRepository
from ..errors import MailboxServiceError, MessageNotFoundError
from .adapters import Adapters
from .changes import ChangeFeed
from .locks import KeyedLocks

T = TypeVar("T")


def new_message_id() -> str:
    return new_id("msg")


class SyncService:
    def __init__(
        self,
        adapters: Adapters,
        index: MessageIndexRepository,
        new_id: Callable[[], str] = new_message_id,
        feed: ChangeFeed | None = None,
    ) -> None:
        self._adapters = adapters
        self._index = index
        self._new_id = new_id
        self._feed = feed if feed is not None else ChangeFeed()
        self._locks: KeyedLocks[str] = KeyedLocks()

    def mapped(self, account_id: str) -> bool:
        """Whether the account's ids go through the index."""
        return Capability.STABLE_IDS not in self._adapters.capabilities(account_id)

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
            added = [
                IndexEntry(self._new_id(), n, f, headers.get(n)) for n, f in missing
            ]
            # Before the first sync, every message is still unknown.
            synced = bool(self._index.folder_states(account_id))
            self._index.add(account_id, added)
            # Read back: a sync may have added the same place meanwhile.
            known = self._index.by_native(account_id, natives)
            if synced:
                ours = {e.id for e in added}
                self.changed(
                    account_id,
                    "message.created",
                    [e.id for e in known.values() if e.id in ours],
                )
        return [known[native].id for native in natives]

    async def resolve(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[str], Awaitable[T]],
    ) -> T:
        """Run ``operation`` with the provider's id of a message. If the
        provider no longer finds the message there, sync once and try its
        new place. Anything else it does not find is not ours to follow."""
        if not self.mapped(account_id):
            return await operation(message_id)
        native = self._native(account_id, message_id)
        try:
            return await operation(native)
        except MessageNotFoundError:
            await self.sync_account(account_id)
            entry = self._index.get(account_id, message_id)
            if entry is None or entry.native_id == native:
                raise MessageNotFoundError(f"message {message_id} not found") from None
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

    def forget(self, account_id: str, message_id: str) -> None:
        """A message is gone for good: its id answers 404 from now on."""
        if self.mapped(account_id):
            self._index.drop(account_id, message_id)

    def changed(
        self, account_id: str, type: ChangeType, message_ids: Iterable[str]
    ) -> None:
        """Record changes to messages in the change feed."""
        self._feed.record(account_id, type, message_ids)

    async def _contents(self, account_id: str, folder_id: str) -> list[str]:
        return await self._adapters.call(
            account_id, lambda p: p.folder_contents(folder_id)
        )

    async def _headers(
        self, account_id: str, natives: list[str]
    ) -> dict[str, str | None]:
        """Best effort: without the headers the listing still works, the next
        sync reads them."""
        try:
            return await self._adapters.call(
                account_id, lambda p: p.message_headers(natives)
            )
        except MailboxServiceError:
            return {}

    def natives(self, account_id: str, message_ids: list[str]) -> dict[str, str | None]:
        """The provider's id of each message, None for ids the index does
        not know."""
        if not self.mapped(account_id):
            return {i: i for i in message_ids}
        entries = (self._index.get(account_id, i) for i in message_ids)
        return {
            i: entry.native_id if entry else None
            for i, entry in zip(message_ids, entries, strict=True)
        }

    def _native(self, account_id: str, message_id: str) -> str:
        entry = self._index.get(account_id, message_id)
        if entry is None:
            raise MessageNotFoundError(f"message {message_id} not found")
        return entry.native_id

    # --- sync -------------------------------------------------------------------------

    async def sync_account(self, account_id: str) -> None:
        """Bring the index of one account up to date. Reads only the folders
        whose state changed. A failure changes nothing."""
        if not self.mapped(account_id):
            return
        lock = self._locks.get(account_id)
        async with lock:
            await self._sync(account_id)

    async def _sync(self, account_id: str) -> None:
        async def call(operation: Callable[[MailProvider], Awaitable[T]]) -> T:
            return await self._adapters.call(account_id, operation)

        states = await call(lambda p: p.folder_states())
        before = self._index.folder_states(account_id)
        changed = [f for f, state in states.items() if before.get(f) != state]
        vanished = [f for f in before if f not in states]
        if not changed and not vanished:
            return

        present: dict[str, str] = {}  # provider id -> folder
        for folder_id in changed:
            for native in await self._contents(account_id, folder_id):
                present[native] = folder_id
        entries = self._index.in_folders(account_id, changed + vanished)
        indexed = {e.native_id for e in entries}
        arrived = [n for n in present if n not in indexed]
        left = [e for e in entries if e.native_id not in present]
        unread_headers = [
            e.native_id for e in entries if e.header is None and e.native_id in present
        ]
        wanted = arrived + unread_headers
        headers = await call(lambda p: p.message_headers(wanted)) if wanted else {}

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
        if before:
            self.changed(account_id, "message.created", [e.id for e in changes.added])
            self.changed(account_id, "message.updated", [e.id for e in moved])
            self.changed(account_id, "message.deleted", changes.removed)


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
