"""A disk under a database that fails, for the tests of the database."""

from __future__ import annotations

import sqlite3

import sqlalchemy as sa

from benethos_mailbox_service.data.storage import Database

from ...schema_helpers import driver, engine


class Disk:
    """A disk under a database that fails a COMMIT, as a full one does:
    the one place that knows where the engine and the connection of a
    database sit."""

    def __init__(self) -> None:
        self._failing: list[sa.Engine] = []

    def fail_commit(self, db: Database) -> None:
        found = engine(db)
        sa.event.listen(found, "commit", _fail)
        self._failing.append(found)

    def mend(self) -> None:
        while self._failing:
            sa.event.remove(self._failing.pop(), "commit", _fail)

    @staticmethod
    def in_transaction(db: Database) -> bool:
        return bool(driver(db).in_transaction)


def _fail(connection: sa.Connection) -> None:
    raise sqlite3.OperationalError("disk I/O error")


def traced(db: Database) -> list[str]:
    """Every statement the database runs from now on, as the driver sees
    it."""
    said: list[str] = []
    driver(db).set_trace_callback(said.append)
    return said
