"""The rows of one table keyed by ``id``: list, get and delete are the
same for every record kept that way. Each repository adds its own
``save``, since the columns differ."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Generic, TypeVar

from ..table import missing
from .database import Database

T = TypeVar("T")


class SqliteRows(Generic[T]):
    def __init__(
        self, db: Database, table: str, what: str, of: Callable[[sqlite3.Row], T]
    ) -> None:
        self._db = db
        self._table = table
        self._what = what
        self._of = of

    def list(self) -> list[T]:
        rows = self._db.query(f"SELECT * FROM {self._table} ORDER BY rowid")
        return [self._of(row) for row in rows]

    def get(self, row_id: str) -> T:
        row = self._db.one(f"SELECT * FROM {self._table} WHERE id = ?", (row_id,))
        if row is None:
            raise missing(self._what, row_id)
        return self._of(row)

    def delete(self, row_id: str) -> None:
        self._db.must_change(
            f"DELETE FROM {self._table} WHERE id = ?", (row_id,), self._what, row_id
        )
