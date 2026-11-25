"""A disk under a database that fails, for the tests of the database."""

from __future__ import annotations

import sqlite3

import pytest

from benethos_mailbox_service.data.storage import Database


class Disk:
    """A disk under a database that fails a COMMIT, as a full one does:
    the one place that knows where the connection of a database sits."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    def fail_commit(self, db: Database) -> None:
        self._monkeypatch.setattr(db, "_connection", _FailingCommit(db._connection))

    def mend(self) -> None:
        self._monkeypatch.undo()

    @staticmethod
    def in_transaction(db: Database) -> bool:
        return db._connection.in_transaction


class _FailingCommit:
    """A connection whose COMMIT fails."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql: str, *args: object) -> object:
        if sql == "COMMIT":
            raise sqlite3.OperationalError("disk I/O error")
        return self._real.execute(sql, *args)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)
