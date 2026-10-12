"""What one pass of the sync finds, as values and pure functions: the
folders' contents against the index, the moves among them, what the
index becomes, and the counts for the log."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime

from ...common.clock import iso, parse_iso
from ...data.providers import FolderChanges, ThreadHeaders
from ...data.storage import IndexChanges, IndexEntry, ThreadChain


@dataclass(frozen=True)
class Seen:
    """What a pass found in the changed folders: the index entries there,
    the folder each provider id is in now, and the headers read."""

    entries: list[IndexEntry]
    present: dict[str, str]
    headers: dict[str, ThreadHeaders]

    def message_id(self, native: str) -> str | None:
        """The ``Message-ID`` read for a provider id, if any."""
        found = self.headers.get(native)
        return found.message_id if found is not None else None

    @property
    def arrived(self) -> list[str]:
        indexed = {e.native_id for e in self.entries}
        return [n for n in self.present if n not in indexed]

    @property
    def left(self) -> list[IndexEntry]:
        return [e for e in self.entries if e.native_id not in self.present]

    @property
    def stayed(self) -> dict[str, IndexEntry]:
        """By provider id, the entries still in the folder the index says."""
        return {
            e.native_id: e
            for e in self.entries
            if self.present.get(e.native_id) == e.folder_id
        }


@dataclass(frozen=True)
class Counts:
    """What one pass found, for the log."""

    folders: int
    created: int = 0
    updated: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class DeltaState:
    """A folder's state as the index keeps it for a provider that tells
    what changed: the provider's token, and when it was handed out."""

    token: str
    at: datetime

    def stored(self) -> str:
        return json.dumps({"token": self.token, "at": iso(self.at)})


def delta_state(stored: str | None) -> DeltaState | None:
    """A folder's stored delta state, None for a state of another kind or
    none at all."""
    if stored is None:
        return None
    try:
        value = json.loads(stored)
        at = parse_iso(str(value["at"]))
    except (ValueError, TypeError, KeyError):
        return None
    return None if at is None else DeltaState(str(value["token"]), at)


@dataclass
class DeltaPass:
    """What the folders of one delta pass told, folder by folder, and what
    was created, updated and deleted by it."""

    seen: dict[str, datetime | None] = field(default_factory=dict)  # -> created
    since: dict[str, datetime] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)
    where: dict[str, str] = field(default_factory=dict)  # -> its folder now
    # -> the folder it left. Empty where several folders say so: a provider
    # that cannot tell where a deleted message was (JMAP) reports it
    # removed from each.
    gone_from: dict[str, str] = field(default_factory=dict)
    known: set[str] = field(default_factory=set)  # listed, not reported

    def add(
        self,
        folder_id: str,
        found: FolderChanges,
        last: DeltaState | None,
        expired: datetime | None,
    ) -> None:
        """One folder's changes since ``last``. Without it, the folder is
        listed whole: known before, or new in a folder asked for the first
        time. After a forgotten token (``expired``), what came since then
        is new."""
        for message in found.changed:
            self.where[message.id] = folder_id
            at = message.created
            if last is not None:
                self.seen[message.id] = at
                self.since[message.id] = last.at
            elif expired is not None and at is not None and at >= expired:
                self.seen[message.id] = at
                self.since[message.id] = expired
            else:
                self.known.add(message.id)
        if last is None:
            return
        self.removed |= set(found.removed)
        for message_id in found.removed:
            was = self.gone_from.setdefault(message_id, folder_id)
            if was != folder_id:
                self.gone_from[message_id] = ""

    def outcome(self) -> tuple[list[str], list[str], list[str]]:
        """Created, updated and deleted. Deleted: removed and seen nowhere.
        Moved: removed here, seen there."""
        created = [
            i
            for i, at in self.seen.items()
            if i not in self.removed and at is not None and at >= self.since[i]
        ]
        updated = [i for i in self.seen if i not in created]
        updated += sorted((self.removed & self.known) - set(self.seen))
        deleted = sorted(self.removed - set(self.seen) - self.known)
        return created, updated, deleted


def moves(seen: Seen) -> dict[IndexEntry, str]:
    """Which message that left is which one that arrived: same
    ``Message-ID``, and exactly one on each side."""
    gone: dict[str, list[IndexEntry]] = {}
    for entry in seen.left:
        if entry.header:
            gone.setdefault(entry.header, []).append(entry)
    came: dict[str, list[str]] = {}
    for native in seen.arrived:
        header = seen.message_id(native)
        if header:
            came.setdefault(header, []).append(native)
    return {
        olds[0]: came[header][0]
        for header, olds in gone.items()
        if len(olds) == 1 and len(came.get(header, [])) == 1
    }


def index_changes(
    states: dict[str, str],
    seen: Seen,
    moved: dict[IndexEntry, str],
    new_id: Callable[[], str],
) -> IndexChanges:
    """The index after a pass: headers read now, moves under their old
    ids, what left removed, what arrived added under a new id."""
    present = seen.present
    changes = IndexChanges(states=states)
    for entry in seen.entries:
        header = seen.message_id(entry.native_id)
        if entry.native_id in present and entry.header is None and header:
            changes.updated.append(replace(entry, header=header))
    for old, native in moved.items():
        changes.updated.append(
            replace(old, native_id=native, folder_id=present[native])
        )
    taken = set(moved.values())
    changes.removed = [e.id for e in seen.left if e not in moved]
    changes.added = [
        IndexEntry(new_id(), n, present[n], seen.message_id(n))
        for n in seen.arrived
        if n not in taken
    ]
    return changes


def chain(message_id: str, headers: ThreadHeaders, references: int) -> ThreadChain:
    """The headers that tie a message to its conversation: its own
    ``Message-ID``, the last ``references`` of its ``References`` and the
    one it answers."""
    kept = headers.references[-references:] if references > 0 else ()
    named = (headers.message_id, *kept, headers.in_reply_to)
    return ThreadChain(message_id, tuple(dict.fromkeys(h for h in named if h)))
