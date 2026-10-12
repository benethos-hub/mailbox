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

Where the adapter has ``THREADS`` but no thread ids of its own (IMAP),
the index keeps the threads too (``threads``).

What a pass finds goes into the change feed: new messages as created,
moved ones, ones whose thread went into another and, where the provider
can tell, ones whose flags changed as updated, vanished ones as deleted.
The first pass of an account records nothing, since the messages
already there are not new.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TypeVar

from benethos_mailbox_common.log import redact
from benethos_mailbox_common.values import secret

from ...common.clock import utc_now
from ...common.locks import KeyedLocks
from ...data.providers import Capability, FolderChanges, ThreadHeaders
from ...data.storage import IndexChanges, IndexEntry, MessageIndexRepository
from ...errors import (
    ChangesExpiredError,
    MailboxServiceError,
    MessageNotFoundError,
    missing_message,
)
from ..accounts import Adapters, deltas
from ..activity import SERVICE, ActivityLog
from ..activity import sync as said
from ..changes import (
    ChangeFeed,
    MailboxChange,
    MessagesCreated,
    MessagesDeleted,
    MessagesUpdated,
)
from .passes import (
    Counts,
    DeltaPass,
    DeltaState,
    Seen,
    delta_state,
    index_changes,
    moves,
)
from .threads import REFERENCES, IndexThreads, new_thread_id

T = TypeVar("T")


def new_message_id() -> str:
    return secret.new_id("msg")


@dataclass(frozen=True, slots=True)
class SyncState:
    """How the passes of one account went, since the service started.
    Kept in memory only."""

    last_sync_at: datetime | None = None
    # The last pass that failed, and why. Cleared by one that succeeds.
    last_error: str | None = None
    last_error_at: datetime | None = None


class SyncService:
    def __init__(
        self,
        adapters: Adapters,
        index: MessageIndexRepository,
        feed: ChangeFeed,
        new_id: Callable[[], str] = new_message_id,
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
        references: int = REFERENCES,
        new_thread: Callable[[], str] = new_thread_id,
    ) -> None:
        self._adapters = adapters
        self._index = index
        self._new_id = new_id
        self._threads = IndexThreads(adapters, index, references, new_thread)
        self._feed = feed
        self._clock = clock
        self._activity = activity or ActivityLog(clock)
        self._locks: KeyedLocks[str] = KeyedLocks()
        self._states: dict[str, SyncState] = {}

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
        before the next sync can only be followed by it. Where the index
        keeps threads, they join theirs at once, and so do known ones the
        sync has not threaded yet."""
        places = list(places)
        if not self.mapped(account_id):
            return [native for native, _ in places]
        natives = [native for native, _ in places]
        known = self._index.by_native(account_id, natives)
        missing = [(n, f) for n, f in dict(places).items() if n not in known]
        waiting = (
            [e for e in known.values() if e.thread_id is None]
            if self._threads.kept(account_id)
            else []
        )
        if not missing and not waiting:
            return [known[native].id for native in natives]
        wanted = [n for n, _ in missing] + [e.native_id for e in waiting]
        headers = await self._headers(account_id, wanted)
        added = [
            IndexEntry(self._new_id(), n, f, _message_id(headers.get(n)))
            for n, f in missing
        ]
        # Before the first sync, every message is still unknown.
        synced = bool(self._index.folder_states(account_id))
        ours = {e.id: e.folder_id for e in added}
        if added:
            self._index.add(account_id, added)
            # Read back: a sync may have added the same place meanwhile.
            known = self._index.by_native(account_id, natives)
            if synced:
                self.changed(
                    MessagesCreated(
                        account_id,
                        [e.id for e in known.values() if e.id in ours],
                        ours,
                    )
                )
        merged = self._threads.join(account_id, [*added, *waiting], headers)
        if synced:
            self._report_merged(account_id, merged, set(ours))
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
                raise missing_message(message_id) from None
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

    def forget_account(self, account_id: str) -> None:
        """An account is deleted: its ids and its sync state go."""
        self._index.forget_account(account_id)
        self._states.pop(account_id, None)

    def folder_of(self, account_id: str, message_id: str) -> str | None:
        """The folder the index has for a message, None where it keeps no
        index or does not know the message."""
        if not self.mapped(account_id):
            return None
        entry = self._index.get(account_id, message_id)
        return entry.folder_id if entry is not None else None

    def forget(self, account_id: str, message_id: str) -> None:
        """A message is gone for good: its id answers 404 from now on."""
        if self.mapped(account_id):
            self._index.drop(account_id, message_id)

    def changed(self, change: MailboxChange) -> None:
        """Record a change in the change feed."""
        self._feed.record(change)

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

    def thread_ids(self, account_id: str, message_ids: list[str]) -> dict[str, str]:
        """The thread of each message the index has one for. Empty where
        the index keeps no threads."""
        return self._threads.of(account_id, message_ids)

    def keeps_threads(self, account_id: str) -> bool:
        """Whether the index keeps the account's threads."""
        return self._threads.kept(account_id)

    def thread_entries(self, account_id: str, thread_id: str) -> list[IndexEntry]:
        """The index entries of a thread, in the order they came."""
        return self._index.in_thread(account_id, thread_id)

    async def _headers(
        self, account_id: str, natives: list[str]
    ) -> dict[str, ThreadHeaders]:
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
            raise missing_message(message_id)
        return entry.native_id

    # --- sync -------------------------------------------------------------------------

    async def sync_account(self, account_id: str) -> None:
        """Bring the index of one account up to date. Reads only the folders
        whose state changed. A failure changes nothing."""
        if not self.watched(account_id):
            return
        lock = self._locks.get(account_id)
        async with lock:
            state = self.state(account_id)
            try:
                if self.mapped(account_id):
                    counts = await self._sync(account_id)
                else:
                    counts = await self._sync_delta(account_id)
            except MailboxServiceError as exc:
                self._states[account_id] = replace(
                    state,
                    last_error=redact.redact(exc.message),
                    last_error_at=self._clock(),
                )
                raise
            self._states[account_id] = SyncState(last_sync_at=self._clock())
        self._activity.record(
            said.Synced(
                by=SERVICE,
                account=self._adapters.record(account_id),
                folders=counts.folders,
                created=counts.created,
                updated=counts.updated,
                deleted=counts.deleted,
            )
        )

    def state(self, account_id: str) -> SyncState:
        """How the passes of the account went since the start."""
        return self._states.get(account_id, SyncState())

    async def _sync_delta(self, account_id: str) -> Counts:
        """Ask every folder what changed since its last token. A folder asked
        for the first time only hands out its token. The stored state of a
        folder is its token and when the pass that got it began."""
        now = self._clock()
        folders = await self._adapters.call(account_id, lambda p: p.folder_states())
        before = self._index.folder_states(account_id)
        states: dict[str, str] = {}
        found = DeltaPass()
        for folder_id in folders:
            last = delta_state(before.get(folder_id))
            expired = None  # since when, where the provider forgot the token
            try:
                changes = await self._folder_changes(
                    account_id, folder_id, last.token if last else None
                )
            except ChangesExpiredError:
                expired, last = (last.at if last else None), None
                changes = await self._folder_changes(
                    account_id, folder_id, None, expired
                )
            states[folder_id] = DeltaState(changes.token, now).stored()
            found.add(folder_id, changes, last, expired)
        self._index.apply(account_id, IndexChanges(states=states))
        if not before:
            return Counts(len(folders))
        created, updated, deleted = found.outcome()
        self.changed(MessagesCreated(account_id, created, found.where))
        self.changed(MessagesUpdated(account_id, updated, found.where))
        self.changed(MessagesDeleted(account_id, deleted, found.gone_from))
        return Counts(len(folders), len(created), len(updated), len(deleted))

    async def _folder_changes(
        self,
        account_id: str,
        folder_id: str,
        token: str | None,
        since: datetime | None = None,
    ) -> FolderChanges:
        return await self._adapters.call(
            account_id, lambda p: deltas(p).folder_changes(folder_id, token, since)
        )

    async def _sync(self, account_id: str) -> Counts:
        """Compare the folders whose state changed with the index: what
        arrived, left, moved, or changed its flags. Then thread what
        arrived, and a portion of the entries without a thread."""
        states = await self._adapters.call(account_id, lambda p: p.folder_states())
        before = self._index.folder_states(account_id)
        changed = [f for f, state in states.items() if before.get(f) != state]
        vanished = [f for f in before if f not in states]
        counts = Counts(len(states))
        merged: dict[str, str] = {}
        created: set[str] = set()
        if changed or vanished:
            seen = await self._seen(account_id, changed, vanished)
            flagged = await self._flagged(account_id, changed, before, seen)
            moved = moves(seen)
            changes = index_changes(states, seen, moved, self._new_id)
            self._index.apply(account_id, changes)
            if before:
                counts = self._report(
                    account_id, seen, moved, changes, flagged, len(states)
                )
            merged = self._threads.join(account_id, changes.added, seen.headers)
            created = {e.id for e in changes.added}
        merged.update(await self._threads.backfill(account_id))
        if before:
            reported = self._report_merged(account_id, merged, created)
            counts = replace(counts, updated=counts.updated + reported)
        return counts

    # --- threads ----------------------------------------------------------------------

    def _report_merged(
        self, account_id: str, merged: dict[str, str], created: set[str]
    ) -> int:
        """Messages whose thread went into another, as updated. Those new
        in this pass are reported as created already. Answers how many."""
        moved = self._threads.moved(account_id, merged, created)
        self.changed(MessagesUpdated(account_id, list(moved), moved))
        return len(moved)

    async def _seen(
        self, account_id: str, changed: list[str], vanished: list[str]
    ) -> Seen:
        """What is in the changed folders now, against the index entries of
        those and of the folders that vanished, with the Message-IDs of
        what arrived and of what the index has none for."""
        present: dict[str, str] = {}  # provider id -> folder
        for folder_id in changed:
            for native in await self._contents(account_id, folder_id):
                present[native] = folder_id
        entries = self._index.in_folders(account_id, changed + vanished)
        seen = Seen(entries, present, {})
        wanted = seen.arrived + [
            e.native_id for e in entries if e.header is None and e.native_id in present
        ]
        if not wanted:
            return seen
        headers = await self._adapters.call(
            account_id, lambda p: p.message_headers(wanted)
        )
        return replace(seen, headers=headers)

    async def _flagged(
        self,
        account_id: str,
        changed: list[str],
        before: dict[str, str],
        seen: Seen,
    ) -> list[str]:
        """Messages that stayed but whose flags changed, where the provider
        can tell (IMAP with CONDSTORE)."""
        stayed = seen.stayed
        flagged: list[str] = []
        for folder_id in changed:
            known = [n for n, e in stayed.items() if e.folder_id == folder_id]
            if folder_id in before and known:
                natives = await self._flag_changes(
                    account_id, folder_id, before[folder_id], known
                )
                flagged += [stayed[n].id for n in natives if n in stayed]
        return flagged

    def _report(
        self,
        account_id: str,
        seen: Seen,
        moved: dict[IndexEntry, str],
        changes: IndexChanges,
        flagged: list[str],
        folders: int,
    ) -> Counts:
        """The changes of a pass in the change feed."""
        present = seen.present
        self.changed(
            MessagesCreated(
                account_id,
                [e.id for e in changes.added],
                {e.id: e.folder_id for e in changes.added},
            )
        )
        # A message renumbered in its folder (a new UIDVALIDITY) did not
        # change for the caller. One that went to another folder did.
        elsewhere = [e.id for e, n in moved.items() if present[n] != e.folder_id]
        now_in = {e.id: present[n] for e, n in moved.items()}
        now_in.update((e.id, e.folder_id) for e in seen.stayed.values())
        self.changed(MessagesUpdated(account_id, elsewhere + flagged, now_in))
        self.changed(
            MessagesDeleted(
                account_id,
                changes.removed,
                {e.id: e.folder_id for e in seen.left if e not in moved},
            )
        )
        return Counts(
            folders,
            len(changes.added),
            len(elsewhere + flagged),
            len(changes.removed),
        )


def _message_id(headers: ThreadHeaders | None) -> str | None:
    return headers.message_id if headers is not None else None
