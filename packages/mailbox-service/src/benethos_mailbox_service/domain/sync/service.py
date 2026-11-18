"""Stable message ids, and the sync that keeps them (CONCEPT 4.1, 8.1).

A provider without ``STABLE_IDS`` names a message by its place, e.g. IMAP
folder, UIDVALIDITY and UID. Callers get our own id instead, kept in the
index. A sync pass compares the provider's folders with the index: a message
that left one folder and one with the same ``Message-ID`` that arrived in
another is the same message and keeps its id. Anything ambiguous is not
guessed: the old id is dropped and the new place gets a new one.

A provider with stable ids needs no index. Where it reports changes per
folder (``DELTA``, Graph delta queries), a pass asks each folder what
changed since its last token and records that instead. The passes run
in ``runner``.

Where the adapter has ``THREADS`` but no thread ids of its own (IMAP),
the index keeps the threads too (``threads``).

What a pass finds goes into the change feed: new messages as created,
moved ones, ones whose thread went into another and, where the provider
can tell, ones whose flags changed as updated, vanished ones as deleted.
The first pass of an account records nothing, since the messages
already there are not new.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import TypeVar

from benethos_mailbox_common.values import secret

from ...common.clock import utc_now
from ...data.providers import (
    ThreadHeaders,
)
from ...data.storage import IndexEntry, MessageIndexRepository
from ...errors import (
    MailboxServiceError,
)
from ..accounts import Adapters
from ..activity import ActivityLog
from ..changes import (
    ChangeFeed,
    MailboxChange,
    MessagesCreated,
)
from .runner import SyncRunner, SyncState
from .threads import REFERENCES, IndexThreads, new_thread_id
from .writes import OwnWrites

T = TypeVar("T")


def new_message_id() -> str:
    return secret.new_id("msg")


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
        self._writes = OwnWrites()
        self._runner = SyncRunner(
            adapters,
            index,
            feed,
            self._threads,
            self._writes,
            new_id,
            clock,
            self._activity,
        )

    @property
    def feed(self) -> ChangeFeed:
        """The change feed this service records into."""
        return self._feed

    def mapped(self, account_id: str) -> bool:
        """Whether the account's ids go through the index."""
        return self._runner.mapped(account_id)

    def watched(self, account_id: str) -> bool:
        """Whether a sync pass does anything for the account: keep its index,
        or ask its folders what changed."""
        return self._runner.watched(account_id)

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
            self._runner.report_merged(account_id, merged, set(ours))
        return [known[native].id for native in natives]

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
            self._writes.done(account_id)

    @contextmanager
    def writing(self, account_id: str) -> Iterator[None]:
        """A change of ours to messages, from the provider's call to the
        index following it: a pass it overtakes applies nothing."""
        with self._writes.writing(account_id):
            yield

    @contextmanager
    def pausing(self, account_id: str) -> Iterator[None]:
        """Inside ``writing``, around a pass the change asks for itself."""
        with self._writes.pausing(account_id):
            yield

    def forget_account(self, account_id: str) -> None:
        """An account is deleted: its ids and its sync state go."""
        self._index.forget_account(account_id)
        self._runner.forget(account_id)
        self._writes.forget(account_id)

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
            self._writes.done(account_id)

    def changed(self, change: MailboxChange) -> None:
        """Record a change in the change feed."""
        self._feed.record(change)

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

    # --- sync -------------------------------------------------------------------------

    async def sync_account(self, account_id: str) -> None:
        """Bring the index of one account up to date (``SyncRunner``)."""
        await self._runner.sync_account(account_id)

    def state(self, account_id: str) -> SyncState:
        """How the passes of the account went since the start."""
        return self._runner.state(account_id)


def _message_id(headers: ThreadHeaders | None) -> str | None:
    return headers.message_id if headers is not None else None
