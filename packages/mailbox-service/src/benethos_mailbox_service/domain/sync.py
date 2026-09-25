"""Stable message ids, and the sync that keeps them (CONCEPT 4.1, 8.1).

A provider without ``STABLE_IDS`` names a message by its place, e.g. IMAP
folder, UIDVALIDITY and UID. Callers get our own id instead, kept in the
index. A sync pass compares the provider's folders with the index: a message
that left one folder and one with the same ``Message-ID`` that arrived in
another is the same message and keeps its id. Anything ambiguous is not
guessed: the old id is dropped and the new place gets a new one.

A provider with stable ids needs no index. Where it reports changes per
folder (``DELTA``, Graph delta queries), a pass asks each folder what
changed since its last token and records that instead.

What a pass finds goes into the change feed: new messages as created,
moved ones and, where the provider can tell, ones whose flags changed as
updated, vanished ones as deleted. The first pass of an
account records nothing, since the messages already there are not new.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from datetime import datetime
from typing import TypeVar

from ..common.clock import utc_now
from ..common.ids import new_id
from ..data.models import EventType
from ..data.providers import Capability, FolderChanges, MailProvider
from ..data.storage import IndexChanges, IndexEntry, MessageIndexRepository
from ..errors import ChangesExpiredError, MailboxServiceError, MessageNotFoundError
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
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._adapters = adapters
        self._index = index
        self._new_id = new_id
        self._feed = feed if feed is not None else ChangeFeed()
        self._clock = clock
        self._locks: KeyedLocks[str] = KeyedLocks()

    @property
    def feed(self) -> ChangeFeed:
        """The change feed this service records into."""
        return self._feed

    def mapped(self, account_id: str) -> bool:
        """Whether the account's ids go through the index."""
        return Capability.STABLE_IDS not in self._adapters.capabilities(account_id)

    def watched(self, account_id: str) -> bool:
        """Whether a sync pass does anything for the account: keep its index,
        or ask its folders what changed."""
        return self.mapped(account_id) or (
            Capability.DELTA in self._adapters.capabilities(account_id)
        )

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
        self, account_id: str, type: EventType, message_ids: Iterable[str]
    ) -> None:
        """Record changes to messages in the change feed."""
        self._feed.record(account_id, type, message_ids)

    async def _contents(self, account_id: str, folder_id: str) -> list[str]:
        return await self._adapters.call(
            account_id, lambda p: p.folder_contents(folder_id)
        )

    async def _flag_changes(
        self, account_id: str, folder_id: str, since: str, natives: list[str]
    ) -> list[str]:
        return await self._adapters.call(
            account_id, lambda p: p.flag_changes(folder_id, since, natives)
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
        if not self.watched(account_id):
            return
        lock = self._locks.get(account_id)
        async with lock:
            if self.mapped(account_id):
                await self._sync(account_id)
            else:
                await self._sync_delta(account_id)

    async def _sync_delta(self, account_id: str) -> None:
        """Ask every folder what changed since its last token. A folder asked
        for the first time only hands out its token. The stored state of a
        folder is its token and when the pass that got it began."""
        now = self._clock()
        folders = await self._adapters.call(account_id, lambda p: p.folder_states())
        before = self._index.folder_states(account_id)
        states: dict[str, str] = {}
        seen: dict[str, datetime | None] = {}  # id -> created
        removed: set[str] = set()
        arrived_new: set[str] = set()  # in folders asked for the first time
        since: dict[str, datetime] = {}
        for folder_id in folders:
            last = _delta_state(before.get(folder_id))
            try:
                found = await self._folder_changes(
                    account_id, folder_id, last[0] if last else None
                )
            except ChangesExpiredError:
                last = None
                found = await self._folder_changes(account_id, folder_id, None)
            states[folder_id] = json.dumps(
                {"token": found.token, "at": now.isoformat()}
            )
            if last is None:
                arrived_new |= {m.id for m in found.changed}
                continue
            for message in found.changed:
                seen[message.id] = message.created
                since[message.id] = last[1]
            removed |= set(found.removed)
        self._index.apply(account_id, IndexChanges(states=states))
        if not before:
            return
        # Deleted: removed and seen nowhere. Moved: removed here, seen there.
        created = [
            i
            for i, at in seen.items()
            if i not in removed and at is not None and at >= since[i]
        ]
        updated = [i for i in seen if i not in created]
        updated += sorted((removed & arrived_new) - set(seen))
        deleted = sorted(removed - set(seen) - arrived_new)
        self.changed(account_id, "message.created", created)
        self.changed(account_id, "message.updated", updated)
        self.changed(account_id, "message.deleted", deleted)

    async def _folder_changes(
        self, account_id: str, folder_id: str, token: str | None
    ) -> FolderChanges:
        return await self._adapters.call(
            account_id, lambda p: p.folder_changes(folder_id, token)
        )

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
        # Messages that stayed but whose flags changed, where the provider
        # can tell (IMAP with CONDSTORE).
        stayed = {
            e.native_id: e for e in entries if present.get(e.native_id) == e.folder_id
        }
        flagged: list[str] = []
        for folder_id in changed:
            known = [n for n, e in stayed.items() if e.folder_id == folder_id]
            if folder_id in before and known:
                natives = await self._flag_changes(
                    account_id, folder_id, before[folder_id], known
                )
                flagged += [stayed[n].id for n in natives if n in stayed]

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
            # A message renumbered in its folder (a new UIDVALIDITY) did not
            # change for the caller. One that went to another folder did.
            elsewhere = [e.id for e, n in moved.items() if present[n] != e.folder_id]
            self.changed(account_id, "message.updated", elsewhere + flagged)
            self.changed(account_id, "message.deleted", changes.removed)


def _delta_state(stored: str | None) -> tuple[str, datetime] | None:
    """The token and time of a folder's stored delta state, None for a
    state of another kind or none at all."""
    if stored is None:
        return None
    try:
        value = json.loads(stored)
        return str(value["token"]), datetime.fromisoformat(value["at"])
    except (ValueError, TypeError, KeyError):
        return None


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
