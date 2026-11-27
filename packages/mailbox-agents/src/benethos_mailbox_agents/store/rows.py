"""What every part of the state file stands on: the connection and the
name of the file, the ways a part reads and writes in a transaction,
and a time as it is stored. :class:`store.Store` is made of the
parts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

from ..errors import StateFileError


def _text(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("a time stored must carry its zone")
    return moment.astimezone(UTC).isoformat()


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


@contextmanager
def _sqlite(name: str) -> Iterator[None]:
    """A :class:`StateFileError` for any error of sqlite, naming the file
    and what sqlite said: the store is the one home of sqlite3, and no
    caller knows its errors. So is a text it cannot write as UTF-8, which
    it raises outside its own errors, named without the text."""
    try:
        yield
    except sqlite3.Error as exc:
        raise StateFileError(f"the state file {name or ''}: {exc}") from None
    except UnicodeEncodeError:
        raise StateFileError(
            f"the state file {name or ''}: a text that is not valid UTF-8"
        ) from None


class _Rows:
    """The connection a part of the store reads and writes through."""

    _db: sqlite3.Connection
    _name: str

    @property
    def version(self) -> int:
        """The schema version of the file, its ``user_version``."""
        with _sqlite(self._name):
            found: int = self._db.execute("PRAGMA user_version").fetchone()[0]
        return found

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _one(self, sql: str, *args: Any) -> Any:
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as rows:
            return rows.fetchone()

    def _all(self, sql: str, *args: Any) -> list[Any]:
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as rows:
            return rows.fetchall()

    def _write(self, sql: str, *args: Any) -> int:
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as done:
            return done.rowcount

    def _insert(self, sql: str, *args: Any) -> int:
        """Insert one row. Answers its id."""
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as done:
            if done.lastrowid is None:
                raise RuntimeError("an insert answered no row id")
            return done.lastrowid
