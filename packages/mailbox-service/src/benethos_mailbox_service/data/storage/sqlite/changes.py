"""The change log in SQLite. The sequence is the table's AUTOINCREMENT key,
which never hands out a number twice, not even after a purge."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable
from datetime import datetime

from ...models.changes import Event
from ..changes import LoggedChange
from .database import Database, iso, parse_iso

_HORIZON = "changes_horizon"
# Stays below SQLite's limit of host parameters in one statement.
_MAX_ACCOUNTS = 500


class SqliteChangeLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, events: Iterable[Event]) -> None:
        with self._db.transaction() as conn:
            conn.executemany(
                "INSERT INTO changes (account_id, message_id, type, at)"
                " VALUES (?, ?, ?, ?)",
                [(e.account_id, e.id, e.type, iso(e.at)) for e in events],
            )

    def after(
        self,
        account_ids: Iterable[str],
        seq: int,
        *,
        limit: int,
        types: Collection[str] | None = None,
    ) -> list[LoggedChange]:
        accounts = list(dict.fromkeys(account_ids))
        kinds = sorted(types) if types is not None else []
        if types is not None and not kinds:
            return []
        of_type = ""
        if kinds:
            of_type = " AND type IN (" + ", ".join("?" * len(kinds)) + ")"
        found: list[LoggedChange] = []
        for start in range(0, len(accounts), _MAX_ACCOUNTS):
            chunk = accounts[start : start + _MAX_ACCOUNTS]
            marks = ", ".join("?" * len(chunk))
            rows = self._db.query(
                f"SELECT * FROM changes WHERE seq > ? AND account_id IN ({marks})"
                f"{of_type} ORDER BY seq LIMIT ?",
                (seq, *chunk, *kinds, limit),
            )
            found += [_logged(row) for row in rows]
        return sorted(found, key=lambda e: e.seq)[:limit]

    def last(self) -> int:
        row = self._db.one("SELECT seq FROM sqlite_sequence WHERE name = 'changes'")
        return int(row["seq"]) if row is not None else 0

    def horizon(self) -> int:
        row = self._db.one("SELECT value FROM meta WHERE key = ?", (_HORIZON,))
        return int(row["value"]) if row is not None else 0

    def purge(self, before: datetime) -> None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT MAX(seq) AS seq FROM changes WHERE at < ?", (iso(before),)
            ).fetchone()
            if row["seq"] is None:
                return
            conn.execute("DELETE FROM changes WHERE at < ?", (iso(before),))
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key)"
                " DO UPDATE SET value ="
                " MAX(CAST(value AS INTEGER), CAST(excluded.value AS INTEGER))",
                (_HORIZON, str(row["seq"])),
            )

    def forget_account(self, account_id: str) -> None:
        # ON DELETE CASCADE does this as well. Said here, so both stores agree.
        self._db.execute("DELETE FROM changes WHERE account_id = ?", (account_id,))


def _logged(row: sqlite3.Row) -> LoggedChange:
    return LoggedChange(
        seq=row["seq"],
        event=Event(
            type=row["type"],
            id=row["message_id"],
            account_id=row["account_id"],
            at=parse_iso(row["at"]),
        ),
    )
