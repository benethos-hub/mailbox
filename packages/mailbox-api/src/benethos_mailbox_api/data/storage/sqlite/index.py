"""The message id mapping and folder states in SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator

from ..index import IndexChanges, IndexEntry
from .database import Database

# Stays below SQLite's limit of host parameters in one statement.
_CHUNK = 500


def _chunks(values: list[str]) -> Iterator[list[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


class SqliteMessageIndexRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, account_id: str, message_id: str) -> IndexEntry | None:
        row = self._db.one(
            "SELECT * FROM message_index WHERE account_id = ? AND id = ?",
            (account_id, message_id),
        )
        return _entry(row) if row is not None else None

    def by_native(
        self, account_id: str, native_ids: Iterable[str]
    ) -> dict[str, IndexEntry]:
        found: dict[str, IndexEntry] = {}
        for chunk in _chunks(list(dict.fromkeys(native_ids))):
            marks = ", ".join("?" * len(chunk))
            for row in self._db.query(
                "SELECT * FROM message_index WHERE account_id = ?"
                f" AND native_id IN ({marks})",
                (account_id, *chunk),
            ):
                found[row["native_id"]] = _entry(row)
        return found

    def in_folders(
        self, account_id: str, folder_ids: Iterable[str]
    ) -> list[IndexEntry]:
        found: list[IndexEntry] = []
        for chunk in _chunks(list(dict.fromkeys(folder_ids))):
            marks = ", ".join("?" * len(chunk))
            found += [
                _entry(row)
                for row in self._db.query(
                    "SELECT * FROM message_index WHERE account_id = ?"
                    f" AND folder_id IN ({marks}) ORDER BY rowid",
                    (account_id, *chunk),
                )
            ]
        return found

    def add(self, account_id: str, entries: Iterable[IndexEntry]) -> None:
        with self._db.transaction() as db:
            _insert(db, account_id, entries)

    def apply(self, account_id: str, changes: IndexChanges) -> None:
        with self._db.transaction() as db:
            db.executemany(
                "DELETE FROM message_index WHERE account_id = ? AND id = ?",
                [(account_id, message_id) for message_id in changes.removed],
            )
            for entry in changes.updated:
                _update(db, account_id, entry)
            _insert(db, account_id, changes.added)
            db.execute("DELETE FROM folder_states WHERE account_id = ?", (account_id,))
            db.executemany(
                "INSERT INTO folder_states (account_id, folder_id, state)"
                " VALUES (?, ?, ?)",
                [(account_id, f, s) for f, s in changes.states.items()],
            )

    def relocate(self, account_id: str, entry: IndexEntry) -> None:
        with self._db.transaction() as db:
            _update(db, account_id, entry)

    def drop(self, account_id: str, message_id: str) -> None:
        self._db.execute(
            "DELETE FROM message_index WHERE account_id = ? AND id = ?",
            (account_id, message_id),
        )

    def folder_states(self, account_id: str) -> dict[str, str]:
        rows = self._db.query(
            "SELECT folder_id, state FROM folder_states WHERE account_id = ?",
            (account_id,),
        )
        return {row["folder_id"]: row["state"] for row in rows}

    def forget_account(self, account_id: str) -> None:
        with self._db.transaction() as db:
            db.execute("DELETE FROM message_index WHERE account_id = ?", (account_id,))
            db.execute("DELETE FROM folder_states WHERE account_id = ?", (account_id,))


def _update(db: sqlite3.Connection, account_id: str, entry: IndexEntry) -> None:
    """The entry's new place; another entry holding that place gives it up.
    An id the index does not know changes nothing."""
    known = db.execute(
        "SELECT 1 FROM message_index WHERE account_id = ? AND id = ?",
        (account_id, entry.id),
    ).fetchone()
    if known is None:
        return
    db.execute(
        "DELETE FROM message_index WHERE account_id = ? AND native_id = ? AND id <> ?",
        (account_id, entry.native_id, entry.id),
    )
    db.execute(
        "UPDATE message_index SET native_id = ?, folder_id = ?, header = ?"
        " WHERE account_id = ? AND id = ?",
        (entry.native_id, entry.folder_id, entry.header, account_id, entry.id),
    )


def _insert(
    db: sqlite3.Connection, account_id: str, entries: Iterable[IndexEntry]
) -> None:
    db.executemany(
        "INSERT OR IGNORE INTO message_index"
        " (id, account_id, native_id, folder_id, header) VALUES (?, ?, ?, ?, ?)",
        [(e.id, account_id, e.native_id, e.folder_id, e.header) for e in entries],
    )


def _entry(row: sqlite3.Row) -> IndexEntry:
    return IndexEntry(
        id=row["id"],
        native_id=row["native_id"],
        folder_id=row["folder_id"],
        header=row["header"],
    )
