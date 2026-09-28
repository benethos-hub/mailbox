"""The rows of one table keyed by ``id``: list, get and delete are the
same for every record kept that way. A repository extends it or holds
one, and adds its own ``save``, since the columns differ."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Generic, TypeVar

from .database import Database

T = TypeVar("T")


class SqliteRows(Generic[T]):
    def __init__(
        self,
        db: Database,
        table: str,
        what: str,
        of: Callable[[sqlite3.Row], T],
        *,
        order: str = "rowid",
    ) -> None:
        self._db = db
        self._table = table
        self._what = what
        self._of = of
        self._order = order

    def list(self) -> list[T]:
        rows = self._db.query(f"SELECT * FROM {self._table} ORDER BY {self._order}")
        return [self._of(row) for row in rows]

    def get(self, row_id: str) -> T:
        return self._of(self.row(row_id))

    def row(self, row_id: str) -> sqlite3.Row:
        """The row itself, for a column the record does not carry.
        NotFoundError when it is not there."""
        return self._db.must_find(
            f"SELECT * FROM {self._table} WHERE id = ?", (row_id,), self._what, row_id
        )

    def exists(self, row_id: str) -> bool:
        return (
            self._db.one(f"SELECT 1 FROM {self._table} WHERE id = ?", (row_id,))
            is not None
        )

    def delete(self, row_id: str) -> None:
        self._db.must_change(
            f"DELETE FROM {self._table} WHERE id = ?", (row_id,), self._what, row_id
        )
