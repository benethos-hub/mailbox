"""The id mapping: our stable message ids and where each message is now.

Holds per message only our id, the provider's own id of its current place
(for IMAP folder, UIDVALIDITY and UID), the folder and the ``Message-ID``
header, and per folder an opaque state. No subject, sender or content.
The repository stores; which entry belongs to which message the domain
decides.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class IndexEntry:
    id: str  # ours, stable
    native_id: str  # the provider's id of the current place
    folder_id: str
    header: str | None = None  # the Message-ID header, once known


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
        """A message moved: its entry gets the new place. Takes over the
        provider id from any other entry. An id the index does not know
        changes nothing."""
        ...

    def drop(self, account_id: str, message_id: str) -> None:
        """A message is gone for good."""
        ...

    def folder_states(self, account_id: str) -> dict[str, str]: ...

    def forget_account(self, account_id: str) -> None: ...


class InMemoryMessageIndexRepository:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, IndexEntry]] = {}  # account -> id ->
        self._states: dict[str, dict[str, str]] = {}

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
        own = self._entries.setdefault(account_id, {})
        for message_id in changes.removed:
            own.pop(message_id, None)
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
            del own[other]
        own[entry.id] = entry

    def drop(self, account_id: str, message_id: str) -> None:
        self._entries.get(account_id, {}).pop(message_id, None)

    def folder_states(self, account_id: str) -> dict[str, str]:
        return dict(self._states.get(account_id, {}))

    def forget_account(self, account_id: str) -> None:
        self._entries.pop(account_id, None)
        self._states.pop(account_id, None)
