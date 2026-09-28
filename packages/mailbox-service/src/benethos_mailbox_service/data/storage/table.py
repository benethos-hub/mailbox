"""Rows by id, for the in-memory repositories, and the one answer every
repository gives for an id it does not know."""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, Protocol, TypeVar

from ...errors import ConflictError, missing

K = TypeVar("K")
T = TypeVar("T")


class Record(Protocol):
    id: str


R = TypeVar("R", bound=Record)


def drop_where(rows: dict[K, T], drop: Callable[[K, T], bool]) -> int:
    """Remove every row ``drop`` picks, by its key and its value. Returns
    how many there were."""
    gone = [key for key, row in rows.items() if drop(key, row)]
    for key in gone:
        del rows[key]
    return len(gone)


class Table(Generic[T]):
    """Rows by id, in the order they came."""

    def __init__(self, what: str) -> None:
        self._what = what
        self._rows: dict[str, T] = {}

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, row_id: str) -> bool:
        return row_id in self._rows

    def list(self) -> list[T]:
        return list(self._rows.values())

    def get(self, row_id: str) -> T:
        try:
            return self._rows[row_id]
        except KeyError:
            raise missing(self._what, row_id) from None

    def put(self, row_id: str, row: T) -> None:
        self._rows[row_id] = row

    def add(self, row_id: str, row: T) -> None:
        """A new row. An id that exists is a conflict, as it is in SQL."""
        if row_id in self._rows:
            raise ConflictError(f"{self._what} {row_id} exists already")
        self._rows[row_id] = row

    def delete(self, row_id: str) -> None:
        self.get(row_id)
        del self._rows[row_id]


class TableRepository(Generic[R]):
    """An in-memory repository of records kept by their ``id``: list, get,
    save and delete, as the SQLite ones do it."""

    def __init__(self, what: str) -> None:
        self._rows: Table[R] = Table(what)

    def list(self) -> list[R]:
        return self._rows.list()

    def get(self, row_id: str) -> R:
        return self._rows.get(row_id)

    def save(self, record: R) -> None:
        self._rows.put(record.id, record)

    def delete(self, row_id: str) -> None:
        self._rows.delete(row_id)
