"""The id mapping: our stable message ids and where each message is now.

Holds per message only our id, the provider's own id of its current place
(for IMAP folder, UIDVALIDITY and UID), the folder, the ``Message-ID``
header and the thread, and per folder an opaque state. Per thread the
``Message-ID`` headers that tie messages to it. No subject, sender or
content. The repository only stores. The domain decides which entry
belongs to which message, and which headers tie a message to others.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from itertools import count
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IndexEntry:
    id: str  # ours, stable
    native_id: str  # the provider's id of the current place
    folder_id: str
    header: str | None = None  # the Message-ID header, once known
    thread_id: str | None = None  # the conversation, once threaded


@dataclass(frozen=True, slots=True)
class ThreadChain:
    """One message and the ``Message-ID`` headers that tie it to its
    conversation: its own, the one it answers and those it references."""

    message_id: str  # ours
    headers: tuple[str, ...]


@dataclass
class IndexChanges:
    """One sync pass of one account, applied at once."""

    added: list[IndexEntry] = field(default_factory=list)
    # Entries whose place or header changed, by their id.
    updated: list[IndexEntry] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # Every folder's state after the pass. Folders missing here are dropped.
    states: dict[str, str] = field(default_factory=dict)


class MessageIndexRepository(Protocol):
    def get(self, account_id: str, message_id: str) -> IndexEntry | None: ...

    def by_native(
        self, account_id: str, native_ids: Iterable[str]
    ) -> dict[str, IndexEntry]:
        """The entries of these provider ids, keyed by provider id."""
        ...

    def in_folders(
        self, account_id: str, folder_ids: Iterable[str]
    ) -> list[IndexEntry]: ...

    def add(self, account_id: str, entries: Iterable[IndexEntry]) -> None:
        """Adds entries. A provider id that already has one keeps it, and
        so does an id that exists already."""
        ...

    def apply(self, account_id: str, changes: IndexChanges) -> None:
        """Removes, updates, adds and replaces the folder states, in one go.
        An update takes over its provider id from any other entry."""
        ...

    def relocate(self, account_id: str, entry: IndexEntry) -> None:
        """A message moved: its entry gets the new place and header, and
        keeps its thread. Takes over the provider id from any other entry.
        An id the index does not know changes nothing."""
        ...

    def drop(self, account_id: str, message_id: str) -> None:
        """A message is gone for good."""
        ...

    def folder_states(self, account_id: str) -> dict[str, str]: ...

    def forget_account(self, account_id: str) -> None: ...

    # --- threads ----------------------------------------------------------------------

    def thread(
        self,
        account_id: str,
        chains: Iterable[ThreadChain],
        new_thread: Callable[[], str],
    ) -> dict[str, str]:
        """Each message joins the thread that one of its headers is tied
        to, or a new one, and its headers are tied to it. Where a chain
        reaches several threads, the younger ones go into the oldest, in
        one go. Answers the messages whose thread changed so, other than
        those of ``chains``, each with its thread now. A message the index
        does not know is passed over."""
        ...

    def threads_of(self, account_id: str, message_ids: Iterable[str]) -> dict[str, str]:
        """The thread of each of these messages that has one."""
        ...

    def in_thread(self, account_id: str, thread_id: str) -> list[IndexEntry]:
        """The entries of a thread, in the order they came."""
        ...

    def unthreaded(self, account_id: str, limit: int) -> list[IndexEntry]:
        """At most ``limit`` entries without a thread yet, oldest first."""
        ...


class InMemoryMessageIndexRepository:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, IndexEntry]] = {}  # account -> id ->
        self._states: dict[str, dict[str, str]] = {}
        self._links: dict[str, dict[str, str]] = {}  # account -> header -> thread
        self._born: dict[str, int] = {}  # thread -> when its first link came
        self._clock = count()

    def get(self, account_id: str, message_id: str) -> IndexEntry | None:
        return self._entries.get(account_id, {}).get(message_id)

    def by_native(
        self, account_id: str, native_ids: Iterable[str]
    ) -> dict[str, IndexEntry]:
        wanted = set(native_ids)
        return {
            e.native_id: e
            for e in self._entries.get(account_id, {}).values()
            if e.native_id in wanted
        }

    def in_folders(
        self, account_id: str, folder_ids: Iterable[str]
    ) -> list[IndexEntry]:
        wanted = set(folder_ids)
        return [
            e
            for e in self._entries.get(account_id, {}).values()
            if e.folder_id in wanted
        ]

    def add(self, account_id: str, entries: Iterable[IndexEntry]) -> None:
        entries = list(entries)
        taken = set(self.by_native(account_id, (e.native_id for e in entries)))
        own = self._entries.setdefault(account_id, {})
        for entry in entries:
            if entry.native_id not in taken and entry.id not in own:
                own[entry.id] = entry
                taken.add(entry.native_id)

    def apply(self, account_id: str, changes: IndexChanges) -> None:
        for message_id in changes.removed:
            self._remove(account_id, message_id)
        for entry in changes.updated:
            self.relocate(account_id, entry)
        self.add(account_id, changes.added)
        self._states[account_id] = dict(changes.states)

    def relocate(self, account_id: str, entry: IndexEntry) -> None:
        own = self._entries.setdefault(account_id, {})
        if entry.id not in own:
            return
        for other in [
            o.id
            for o in own.values()
            if o.native_id == entry.native_id and o.id != entry.id
        ]:
            self._remove(account_id, other)
        own[entry.id] = replace(entry, thread_id=own[entry.id].thread_id)

    def drop(self, account_id: str, message_id: str) -> None:
        self._remove(account_id, message_id)

    def folder_states(self, account_id: str) -> dict[str, str]:
        return dict(self._states.get(account_id, {}))

    def forget_account(self, account_id: str) -> None:
        self._entries.pop(account_id, None)
        self._states.pop(account_id, None)
        self._links.pop(account_id, None)

    def thread(
        self,
        account_id: str,
        chains: Iterable[ThreadChain],
        new_thread: Callable[[], str],
    ) -> dict[str, str]:
        chains = list(chains)
        merged: dict[str, str] = {}
        for chain in chains:
            merged.update(self._join(account_id, chain, new_thread))
        for chain in chains:
            merged.pop(chain.message_id, None)
        return merged

    def _join(
        self, account_id: str, chain: ThreadChain, new_thread: Callable[[], str]
    ) -> dict[str, str]:
        own = self._entries.get(account_id, {})
        links = self._links.setdefault(account_id, {})
        entry = own.get(chain.message_id)
        if entry is None:
            return {}
        found = {links[h] for h in chain.headers if h in links}
        if entry.thread_id is not None:
            found.add(entry.thread_id)
        # A thread without links, of a message without headers, last.
        ordered = sorted(found, key=lambda t: self._born.get(t, sys.maxsize))
        thread = ordered[0] if ordered else new_thread()
        younger = set(ordered[1:])
        for header, linked in list(links.items()):
            if linked in younger:
                links[header] = thread
        merged = {o.id: thread for o in own.values() if o.thread_id in younger}
        for other in merged:
            own[other] = replace(own[other], thread_id=thread)
        for header in chain.headers:
            links.setdefault(header, thread)
        if chain.headers:
            self._born.setdefault(thread, next(self._clock))
        own[entry.id] = replace(own[entry.id], thread_id=thread)
        return merged

    def threads_of(self, account_id: str, message_ids: Iterable[str]) -> dict[str, str]:
        own = self._entries.get(account_id, {})
        return {
            i: entry.thread_id
            for i in message_ids
            if (entry := own.get(i)) is not None and entry.thread_id is not None
        }

    def in_thread(self, account_id: str, thread_id: str) -> list[IndexEntry]:
        return [
            e
            for e in self._entries.get(account_id, {}).values()
            if e.thread_id == thread_id
        ]

    def unthreaded(self, account_id: str, limit: int) -> list[IndexEntry]:
        own = self._entries.get(account_id, {}).values()
        return [e for e in own if e.thread_id is None][:limit]

    def _remove(self, account_id: str, message_id: str) -> None:
        """An entry goes. A thread without a message left loses its links."""
        own = self._entries.get(account_id, {})
        entry = own.pop(message_id, None)
        if entry is None or entry.thread_id is None:
            return
        if any(e.thread_id == entry.thread_id for e in own.values()):
            return
        links = self._links.get(account_id, {})
        for header in [h for h, t in links.items() if t == entry.thread_id]:
            del links[header]
