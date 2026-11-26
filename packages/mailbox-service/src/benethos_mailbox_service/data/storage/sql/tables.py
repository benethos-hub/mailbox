"""The tables of the schema for the logical export, which knows no table
by name: their columns and keys from the definitions, in the order of
their references, their rows read in chunks by key and written back.

Every name of a table or a column comes from the definitions, never
from a caller. Values always go into a statement as parameters.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Any

import sqlalchemy as sa

from ....errors import StorageError
from .dialect import count_on_from, insert_or_update
from .schema import METADATA, changes, meta

# The tables that keep account of the database itself and hold no
# record: not in the export. Alembic's mark of the revisions.
BOOKKEEPING = frozenset({"alembic_version"})
# The rows of a table read or written at once by an export.
ROWS_CHUNK = 500


@dataclass(frozen=True, slots=True)
class Table:
    """A table of the schema: its name, its columns in their order, and
    the columns of its key."""

    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]


def read_tables(conn: sa.Connection) -> list[Table]:
    """Every table of the schema the database holds, each after the
    tables it refers to. The columns are those of the definitions: a
    database made at an older schema for a test lacks some."""
    held = set(sa.inspect(conn).get_table_names())
    return [
        Table(
            table.name,
            tuple(column.name for column in table.columns),
            tuple(column.name for column in table.primary_key.columns),
        )
        for table in METADATA.sorted_tables
        if table.name in held and table.name not in BOOKKEEPING
    ]


def stored_schema(conn: sa.Connection) -> int:
    """The schema the database says it is in, 0 before the first step."""
    if not sa.inspect(conn).has_table(meta.name):
        return 0
    stored = conn.execute(
        sa.select(meta.c.value).where(meta.c.key == "schema_version")
    ).scalar()
    return 0 if stored is None else int(stored)


class Fixed:
    """The records of a database as the one transaction open on ``conn``
    sees them: its schema, its tables and their rows."""

    def __init__(self, conn: sa.Connection) -> None:
        self._conn = conn

    def schema_version(self) -> int:
        return stored_schema(self._conn)

    def tables(self) -> list[Table]:
        return read_tables(self._conn)

    def rows(self, table: str) -> Iterator[tuple[Any, ...]]:
        """The rows of ``table`` in the order of its key, read in chunks."""
        shape = table_named(self.tables(), table)
        after: tuple[Any, ...] | None = None
        while True:
            part = read_chunk(self._conn, shape, after, ROWS_CHUNK)
            yield from part
            if len(part) < ROWS_CHUNK:
                return
            after = key_of(shape, part[-1])


def table_named(tables: Iterable[Table], name: str) -> Table:
    for table in tables:
        if table.name == name:
            return table
    raise StorageError(f"the schema has no table {name}")


def align_changes(conn: sa.Connection) -> None:
    """The counter of the change feed at least at the last number handed
    out, so a feed whose newest rows were purged never hands one out
    again."""
    last = conn.execute(
        sa.select(meta.c.value).where(meta.c.key == "changes_last")
    ).scalar()
    if last is not None:
        count_on_from(conn, changes, int(last))


def read_chunk(
    conn: sa.Connection, table: Table, after: Sequence[Any] | None, size: int
) -> list[tuple[Any, ...]]:
    """Up to ``size`` rows of ``table`` in the order of its key, those
    after the key ``after``, from the first without it."""
    stored = _as_stored(table)
    key = [stored.c[name] for name in table.key]
    query = sa.select(*(stored.c[name] for name in table.columns))
    if after is not None:
        query = query.where(sa.tuple_(*key) > sa.tuple_(*after))
    return [tuple(row) for row in conn.execute(query.order_by(*key).limit(size))]


def key_of(table: Table, row: Sequence[Any]) -> tuple[Any, ...]:
    """The key of ``row``, a row of ``table`` as ``read_chunk`` reads it."""
    return tuple(row[table.columns.index(c)] for c in table.key)


def fill_table(
    conn: sa.Connection,
    table: Table,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    size: int,
) -> int:
    """Write ``rows``, each with the values of ``columns``, into ``table``,
    which holds none yet: only ``meta`` holds what the schema wrote, and
    a row of the same key replaces it. Answers how many."""
    unknown = [c for c in columns if c not in table.columns]
    if unknown or len(set(columns)) != len(columns):
        raise StorageError(f"the columns do not fit the table {table.name}")
    stored = _as_stored(table)
    first = sa.select(*(stored.c[name] for name in table.key)).limit(1)
    if table.name != meta.name and conn.execute(first).first():
        raise StorageError(f"the table {table.name} is not empty")
    statement: sa.Insert = sa.insert(stored)
    if table.name == meta.name:
        statement = insert_or_update(meta, table.key, list(columns), conn.dialect)
    count = 0
    stream = iter(rows)
    while part := list(islice(stream, size)):
        conn.execute(statement, [dict(zip(columns, row, strict=True)) for row in part])
        count += len(part)
    return count


def _as_stored(table: Table) -> sa.TableClause:
    """``table`` with columns of no type: the values go in and come out
    as the database holds them, as an export needs them, also a text in
    a column of bytes that an older version wrote."""
    return sa.table(table.name, *(sa.column(name) for name in table.columns))
