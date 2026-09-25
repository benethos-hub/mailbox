"""Rows by id, for the in-memory repositories, and the one answer every
repository gives for an id it does not know."""

from __future__ import annotations

from typing import Generic, TypeVar

from ...errors import NotFoundError

T = TypeVar("T")


def missing(what: str, row_id: str) -> NotFoundError:
    return NotFoundError(f"{what} {row_id} not found")


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

    def delete(self, row_id: str) -> None:
        self.get(row_id)
        del self._rows[row_id]
