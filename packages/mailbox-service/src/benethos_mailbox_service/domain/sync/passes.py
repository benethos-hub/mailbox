"""What one pass of the sync finds, as values and pure functions: the
folders' contents against the index, the moves among them, what the
index becomes, and the counts for the log."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from ...common.clock import iso, parse_iso
from ...data.storage import IndexChanges, IndexEntry


@dataclass(frozen=True)
class Seen:
    """What a pass found in the changed folders: the index entries there,
    the folder each provider id is in now, and the Message-IDs read."""

    entries: list[IndexEntry]
    present: dict[str, str]
    headers: dict[str, str | None]

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


def moves(
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


def index_changes(
    states: dict[str, str],
    seen: Seen,
    moved: dict[IndexEntry, str],
    new_id: Callable[[], str],
) -> IndexChanges:
    """The index after a pass: headers read now, moves under their old
    ids, what left removed, what arrived added under a new id."""
    present, headers = seen.present, seen.headers
    changes = IndexChanges(states=states)
    for entry in seen.entries:
        header = headers.get(entry.native_id)
        if entry.native_id in present and entry.header is None and header:
            changes.updated.append(replace(entry, header=header))
    for old, native in moved.items():
        changes.updated.append(IndexEntry(old.id, native, present[native], old.header))
    taken = set(moved.values())
    changes.removed = [e.id for e in seen.left if e not in moved]
    changes.added = [
        IndexEntry(new_id(), n, present[n], headers.get(n))
        for n in seen.arrived
        if n not in taken
    ]
    return changes
