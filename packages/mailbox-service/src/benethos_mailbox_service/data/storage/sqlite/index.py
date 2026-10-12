"""The message id mapping, folder states and threads in SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable

from ....common.chunks import batched
from ..index import IndexChanges, IndexEntry, ThreadChain
from .database import IN_CHUNK, Database


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
        rows = self._db.query_in(
            "SELECT * FROM message_index WHERE account_id = ? AND native_id {in}",
            native_ids,
            before=(account_id,),
        )
        return {row["native_id"]: _entry(row) for row in rows}

    def in_folders(
        self, account_id: str, folder_ids: Iterable[str]
    ) -> list[IndexEntry]:
        rows = self._db.query_in(
            "SELECT rowid, * FROM message_index"
            " WHERE account_id = ? AND folder_id {in}",
            folder_ids,
            before=(account_id,),
        )
        # In the order the entries came, across the chunks of the query.
        return [_entry(row) for row in sorted(rows, key=lambda row: row["rowid"])]

    def add(self, account_id: str, entries: Iterable[IndexEntry]) -> None:
        with self._db.transaction() as db:
            _insert(db, account_id, entries)

    def apply(self, account_id: str, changes: IndexChanges) -> None:
        with self._db.transaction() as db:
            _remove(db, account_id, changes.removed)
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
        with self._db.transaction() as db:
            _remove(db, account_id, [message_id])

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
            db.execute("DELETE FROM thread_links WHERE account_id = ?", (account_id,))
        # The index of an account is most of the file: give its pages back.
        self._db.shrink()

    # --- threads ----------------------------------------------------------------------

    def thread(
        self,
        account_id: str,
        chains: Iterable[ThreadChain],
        new_thread: Callable[[], str],
    ) -> dict[str, str]:
        chains = list(chains)
        merged: dict[str, str] = {}
        with self._db.transaction() as db:
            for chain in chains:
                merged.update(_join(db, account_id, chain, new_thread))
        for chain in chains:
            merged.pop(chain.message_id, None)
        return merged

    def threads_of(self, account_id: str, message_ids: Iterable[str]) -> dict[str, str]:
        rows = self._db.query_in(
            "SELECT id, thread_id FROM message_index"
            " WHERE account_id = ? AND thread_id IS NOT NULL AND id {in}",
            message_ids,
            before=(account_id,),
        )
        return {row["id"]: row["thread_id"] for row in rows}

    def in_thread(self, account_id: str, thread_id: str) -> list[IndexEntry]:
        rows = self._db.query(
            "SELECT * FROM message_index WHERE account_id = ? AND thread_id = ?"
            " ORDER BY rowid",
            (account_id, thread_id),
        )
        return [_entry(row) for row in rows]

    def unthreaded(self, account_id: str, limit: int) -> list[IndexEntry]:
        rows = self._db.query(
            "SELECT * FROM message_index WHERE account_id = ? AND thread_id IS NULL"
            " ORDER BY rowid LIMIT ?",
            (account_id, limit),
        )
        return [_entry(row) for row in rows]


def _join(
    db: sqlite3.Connection,
    account_id: str,
    chain: ThreadChain,
    new_thread: Callable[[], str],
) -> dict[str, str]:
    """One message into its thread, as ``thread`` describes. Answers the
    messages whose thread changed by a merge."""
    row = db.execute(
        "SELECT thread_id FROM message_index WHERE account_id = ? AND id = ?",
        (account_id, chain.message_id),
    ).fetchone()
    if row is None:
        return {}
    headers = list(dict.fromkeys(chain.headers))
    marks = ", ".join("?" * len(headers))
    # The oldest thread first: the one whose first link came first.
    found = (
        [
            r["thread_id"]
            for r in db.execute(
                "SELECT thread_id, MIN(rowid) AS born FROM thread_links"
                f" WHERE account_id = ? AND header IN ({marks})"
                " GROUP BY thread_id ORDER BY born",
                (account_id, *headers),
            )
        ]
        if headers
        else []
    )
    own = row["thread_id"]
    if own is not None and own not in found:
        found.append(own)  # without links: never the oldest
    thread = found[0] if found else new_thread()
    merged: dict[str, str] = {}
    for younger in found[1:]:
        for r in db.execute(
            "SELECT id FROM message_index WHERE account_id = ? AND thread_id = ?",
            (account_id, younger),
        ):
            merged[r["id"]] = thread
        for table in ("message_index", "thread_links"):
            db.execute(
                f"UPDATE {table} SET thread_id = ?"
                " WHERE account_id = ? AND thread_id = ?",
                (thread, account_id, younger),
            )
    db.executemany(
        "INSERT OR IGNORE INTO thread_links (account_id, header, thread_id)"
        " VALUES (?, ?, ?)",
        [(account_id, header, thread) for header in headers],
    )
    db.execute(
        "UPDATE message_index SET thread_id = ? WHERE account_id = ? AND id = ?",
        (thread, account_id, chain.message_id),
    )
    return merged


def _remove(db: sqlite3.Connection, account_id: str, message_ids: list[str]) -> None:
    """Entries go. A thread without a message left loses its links."""
    threads: set[str] = set()
    for chunk in batched(message_ids, IN_CHUNK):
        marks = ", ".join("?" * len(chunk))
        threads |= {
            r["thread_id"]
            for r in db.execute(
                "SELECT DISTINCT thread_id FROM message_index"
                f" WHERE account_id = ? AND thread_id IS NOT NULL AND id IN ({marks})",
                (account_id, *chunk),
            )
        }
    db.executemany(
        "DELETE FROM message_index WHERE account_id = ? AND id = ?",
        [(account_id, message_id) for message_id in message_ids],
    )
    _prune(db, account_id, threads)


def _prune(db: sqlite3.Connection, account_id: str, threads: Iterable[str]) -> None:
    db.executemany(
        "DELETE FROM thread_links WHERE account_id = ? AND thread_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM message_index"
        " WHERE account_id = ? AND thread_id = ?)",
        [(account_id, t, account_id, t) for t in threads],
    )


def _update(db: sqlite3.Connection, account_id: str, entry: IndexEntry) -> None:
    """The entry's new place. Another entry holding that place gives it up.
    An id the index does not know changes nothing. The thread stays."""
    known = db.execute(
        "SELECT 1 FROM message_index WHERE account_id = ? AND id = ?",
        (account_id, entry.id),
    ).fetchone()
    if known is None:
        return
    others = [
        r["id"]
        for r in db.execute(
            "SELECT id FROM message_index"
            " WHERE account_id = ? AND native_id = ? AND id <> ?",
            (account_id, entry.native_id, entry.id),
        )
    ]
    if others:
        _remove(db, account_id, others)
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
        " (id, account_id, native_id, folder_id, header, thread_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (e.id, account_id, e.native_id, e.folder_id, e.header, e.thread_id)
            for e in entries
        ],
    )


def _entry(row: sqlite3.Row) -> IndexEntry:
    return IndexEntry(
        id=row["id"],
        native_id=row["native_id"],
        folder_id=row["folder_id"],
        header=row["header"],
        thread_id=row["thread_id"],
    )
