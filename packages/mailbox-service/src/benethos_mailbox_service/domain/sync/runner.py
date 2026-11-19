"""The sync pass of one account, and how the passes went (CONCEPT 4.1,
8.1).

A pass of an account whose ids go through the index compares the
provider's folders with it: what arrived, left, moved, or changed its
flags. A change of ours that overtakes it makes it read again: it reads
at most ``ATTEMPTS`` times. A pass of an account with ``DELTA`` (Graph
delta queries) asks each folder what changed since its last token.

What a pass finds goes into the change feed: new messages as created,
moved ones, ones whose thread went into another and, where the provider
can tell, ones whose flags changed as updated, vanished ones as deleted.
The first pass of an account records nothing, since the messages
already there are not new. ``SyncService`` keeps the ids and hands its
passes to this one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from benethos_mailbox_common.log import redact

from ...common.locks import KeyedLocks
from ...data.providers import Deltas, FlagChanges, FolderChanges, Reads
from ...data.storage import IndexChanges, IndexEntry, MessageIndexRepository
from ...errors import ChangesExpiredError, MailboxServiceError
from ..accounts import Adapters, deltas
from ..activity import SERVICE, ActivityLog
from ..activity import sync as said
from ..changes import ChangeFeed, MessagesCreated, MessagesDeleted, MessagesUpdated
from .passes import (
    Counts,
    DeltaPass,
    DeltaState,
    Seen,
    delta_state,
    index_changes,
    moves,
    report,
)
from .threads import IndexThreads
from .writes import OwnWrites

# How often a pass reads again when a change of ours overtook it, before
# it leaves the index to the next pass.
ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class Overtaken:
    """A pass a change of ours overtook: nothing of it was applied."""

    folders: int


@dataclass(frozen=True, slots=True)
class SyncState:
    """How the passes of one account went, since the service started.
    Kept in memory only."""

    last_sync_at: datetime | None = None
    # Passes that succeeded.
    passes: int = 0
    # The last pass that failed, and why. Cleared by one that succeeds.
    last_error: str | None = None
    last_error_at: datetime | None = None


class SyncRunner:
    """The passes of every account, one at a time per account."""

    def __init__(
        self,
        adapters: Adapters,
        index: MessageIndexRepository,
        feed: ChangeFeed,
        threads: IndexThreads,
        writes: OwnWrites,
        new_id: Callable[[], str],
        clock: Callable[[], datetime],
        activity: ActivityLog,
    ) -> None:
        self._adapters = adapters
        self._index = index
        self._feed = feed
        self._threads = threads
        self._writes = writes
        self._new_id = new_id
        self._clock = clock
        self._activity = activity
        self._locks: KeyedLocks[str] = KeyedLocks()
        self._states: dict[str, SyncState] = {}

    def mapped(self, account_id: str) -> bool:
        """Whether the account's ids go through the index."""
        return not self._adapters.stable_ids(account_id)

    def watched(self, account_id: str) -> bool:
        """Whether a sync pass does anything for the account: keep its index,
        or ask its folders what changed."""
        return self.mapped(account_id) or isinstance(
            self._adapters.get(account_id), Deltas
        )

    def forget(self, account_id: str) -> None:
        """An account is deleted: how its passes went goes."""
        self._states.pop(account_id, None)

    async def sync_account(self, account_id: str) -> None:
        """Bring the index of one account up to date. Reads only the folders
        whose state changed. A failure changes nothing, nor does a pass
        given up."""
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
            if isinstance(counts, Overtaken):
                return
            self._states[account_id] = SyncState(
                last_sync_at=self._clock(), passes=state.passes + 1
            )
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

    def report_merged(
        self, account_id: str, merged: dict[str, str], created: set[str]
    ) -> int:
        """Messages whose thread went into another, as updated. Those new
        in this pass are reported as created already. Answers how many."""
        moved = self._threads.moved(account_id, merged, created)
        self._feed.record(MessagesUpdated(account_id, list(moved), moved))
        return len(moved)

    async def _sync_delta(self, account_id: str) -> Counts:
        """Ask every folder what changed since its last token. A folder asked
        for the first time only hands out its token. The stored state of a
        folder is its token and when the pass that got it began."""
        now = self._clock()
        folders = await self._adapters.call(account_id, lambda p: p.folder_states())
        before = self._index.folder_states(account_id)
        await self._other_folders(account_id, folders, before)
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
        self._feed.record(MessagesCreated(account_id, created, found.where))
        self._feed.record(MessagesUpdated(account_id, updated, found.where))
        self._feed.record(MessagesDeleted(account_id, deleted, found.gone_from))
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

    async def _other_folders(
        self, account_id: str, now: Mapping[str, object], before: Mapping[str, object]
    ) -> None:
        """A folder came or went since the last pass: what the account can
        do may have changed with it, such as a trash made in another mail
        program. Its server is asked again (UNIFORM R4)."""
        if set(now) == set(before):
            return
        try:
            await self._adapters.learn(account_id)
        except MailboxServiceError:
            return  # asked again with the next change of folders

    async def _sync(self, account_id: str) -> Counts | Overtaken:
        """A pass, read again where a change of ours overtook it. After
        ``ATTEMPTS`` the index stays as it was and the folder states are
        not kept, so the next pass reads the folders again."""
        account = self._adapters.record(account_id)
        for attempt in range(1, ATTEMPTS + 1):
            found = await self._attempt(account_id)
            if isinstance(found, Counts):
                return found
            if attempt < ATTEMPTS:
                self._activity.record(said.PassOvertaken(by=SERVICE, account=account))
        self._activity.record(
            said.PassGivenUp(by=SERVICE, account=account, attempts=ATTEMPTS)
        )
        return found

    async def _attempt(self, account_id: str) -> Counts | Overtaken:
        """Compare the folders whose state changed with the index: what
        arrived, left, moved, or changed its flags. Then thread what
        arrived, and a portion of the entries without a thread. Nothing
        is applied where a change of ours runs or ended since it began."""
        mark = self._writes.mark(account_id)
        states = await self._adapters.call(account_id, lambda p: p.folder_states())
        before = self._index.folder_states(account_id)
        await self._other_folders(account_id, states, before)
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
            # No await between this check and the writing below.
            if self._writes.overtaken(account_id, mark):
                return Overtaken(len(states))
            self._index.apply(account_id, changes)
            changes.added = self._taken(account_id, changes.added)
            if before:
                found = report(account_id, seen, moved, changes, flagged, len(states))
                for change in found.changes:
                    self._feed.record(change)
                counts = found.counts
            merged = self._threads.join(account_id, changes.added, seen.headers)
            created = {e.id for e in changes.added}
        merged.update(await self._threads.backfill(account_id))
        if before:
            reported = self.report_merged(account_id, merged, created)
            counts = replace(counts, updated=counts.updated + reported)
        return counts

    def _taken(self, account_id: str, added: list[IndexEntry]) -> list[IndexEntry]:
        """The entries the index took. A list may have given a place its
        id while the pass read: that id stays, and the pass tells none
        of its own for it."""
        stored = self._index.by_native(account_id, [e.native_id for e in added])
        return [
            e
            for e in added
            if (now := stored.get(e.native_id)) is not None and now.id == e.id
        ]

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

    async def _contents(self, account_id: str, folder_id: str) -> list[str]:
        return await self._adapters.call(
            account_id, lambda p: p.folder_contents(folder_id)
        )

    async def _flag_changes(
        self, account_id: str, folder_id: str, since: str, natives: list[str]
    ) -> list[str]:
        async def asked(adapter: Reads) -> list[str]:
            if not isinstance(adapter, FlagChanges):
                return []  # the adapter tells no flag changes this way
            return await adapter.flag_changes(folder_id, since, natives)

        return await self._adapters.call(account_id, asked)
