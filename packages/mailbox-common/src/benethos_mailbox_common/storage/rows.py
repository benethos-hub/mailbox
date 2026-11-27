"""The rows of one table keyed by ``id``: list, get and delete are the
same for every record kept that way. A repository extends it or holds
one, and adds its own ``save``, since the columns differ. ``order``
names the columns a list is sorted by: every table says its own."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import sqlalchemy as sa

if TYPE_CHECKING:
    from .database import Database


T = TypeVar("T")


class SqlRows(Generic[T]):
    def __init__(
        self,
        db: Database,
        table: sa.Table,
        what: str,
        of: Callable[[sa.RowMapping], T],
        *,
        order: Sequence[sa.ColumnElement[Any]],
    ) -> None:
        self._db = db
        self._table = table
        self._what = what
        self._of = of
        self._order = order

    def list(self) -> list[T]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(self._table).order_by(*self._order)
            ).mappings()
            return [self._of(row) for row in rows]

    def get(self, row_id: str) -> T:
        return self._of(self.row(row_id))

    def row(self, row_id: str) -> sa.RowMapping:
        """The row itself, for a column the record does not carry. The
        error of a missing record when it is not there."""
        with self._db.connected() as conn:
            row = (
                conn.execute(sa.select(self._table).where(self._id == row_id))
                .mappings()
                .first()
            )
        if row is None:
            raise self._db.errors.missing(self._what, row_id)
        return row

    def exists(self, row_id: str) -> bool:
        with self._db.connected() as conn:
            found = conn.execute(
                sa.select(sa.literal(1)).where(self._id == row_id)
            ).first()
        return found is not None

    def delete(self, row_id: str) -> None:
        self.must_change(sa.delete(self._table).where(self._id == row_id), row_id)

    def must_change(self, statement: sa.Executable, row_id: str) -> None:
        """``statement`` about the row ``row_id``: the error of a missing
        record when it changed none."""
        if not rows_changed(self._db, statement):
            raise self._db.errors.missing(self._what, row_id)

    @property
    def _id(self) -> sa.ColumnElement[Any]:
        return self._table.c.id


def rows_changed(db: Database, statement: sa.Executable) -> int:
    """``statement`` in a transaction of its own, or in the one open. The
    rows it changed."""
    with db.connected() as conn:
        count: int = conn.execute(statement).rowcount
        return count


def next_position(table: sa.Table) -> sa.ScalarSelect[Any]:
    """The place after the last of ``table``, for a row added to a table
    listed by its column ``position``."""
    return sa.select(
        sa.func.coalesce(sa.func.max(table.c.position), 0) + 1
    ).scalar_subquery()
