"""The move of the records from one database to another, the file of
SQLite to a schema on PostgreSQL or back (``storage move``).

Before anything is written, every value of the source is held to the
kind of its column: SQLite keeps a text in a column of numbers or of
bytes, which PostgreSQL refuses or takes as something else. A value that
does not fit stops the move. The message names the table, the column and
how many, never a value.
"""

from __future__ import annotations

from dataclasses import dataclass

from .storage import Records

_FITS: dict[str, type] = {"text": str, "number": int, "bytes": bytes}


class MoveError(Exception):
    """A move that cannot be made or did not hold: what is wrong, never a
    value of a row."""


@dataclass(frozen=True, slots=True)
class Misfit:
    """How many values of ``column`` of ``table`` do not fit its kind."""

    table: str
    column: str
    count: int


def misfits(records: Records) -> list[Misfit]:
    """Each column of ``records`` with values that do not fit its kind,
    table by table in the order of their references."""
    found: list[Misfit] = []
    for table in records.tables():
        fits = [_FITS[kind] for kind in table.kinds]
        counts = [0] * len(fits)
        for row in records.rows(table.name):
            for index, value in enumerate(row):
                if value is not None and not isinstance(value, fits[index]):
                    counts[index] += 1
        found += [
            Misfit(table.name, column, count)
            for column, count in zip(table.columns, counts, strict=True)
            if count
        ]
    return found


def refused(found: list[Misfit]) -> MoveError:
    """The error that stops a move for ``found``, one line per column."""
    lines = [f"  {f.table}.{f.column}: {f.count}" for f in found]
    return MoveError(
        "values that do not fit their column, nothing was written:\n" + "\n".join(lines)
    )
