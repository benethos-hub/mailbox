"""The tables of the schema as they are stored, for the logical export,
which knows no table by name: their columns and keys, in the order of
their references, their rows read in chunks by key and written back.

Every name of a table or a column comes from the schema, never from a
caller. Values always go into a statement as parameters.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Any

from ....errors import StorageError

# The table whose rows the migrations write, and the rows of a fill
# replace by key.
META = "meta"


@dataclass(frozen=True, slots=True)
class Table:
    """A table of the schema: its name, its columns in their order, and
    the columns of its key."""

    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]


def read_tables(db: sqlite3.Connection) -> list[Table]:
    """Every table of the schema, each after the tables it refers to,
    otherwise by name. SQLite's own tables are not among them."""
    names = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    found: dict[str, Table] = {}
    refers: dict[str, set[str]] = {}
    for name in names:
        info = db.execute("SELECT * FROM pragma_table_info(?)", (name,)).fetchall()
        key = [row["name"] for row in sorted(info, key=lambda r: r["pk"]) if row["pk"]]
        found[name] = Table(name, tuple(row["name"] for row in info), tuple(key))
        refers[name] = {
            row["table"]
            for row in db.execute("SELECT * FROM pragma_foreign_key_list(?)", (name,))
        } - {name}
    ordered: list[Table] = []
    while refers:
        ready = [n for n in sorted(refers) if not refers[n] & refers.keys()]
        if not ready:
            raise StorageError(f"the tables refer to each other: {sorted(refers)}")
        for name in ready:
            ordered.append(found[name])
            del refers[name]
    return ordered


def read_chunk(
    db: sqlite3.Connection, table: Table, after: Sequence[Any] | None, size: int
) -> list[tuple[Any, ...]]:
    """Up to ``size`` rows of ``table`` in the order of its key, those
    after the key ``after``, from the first without it."""
    columns = ", ".join(_quoted(c) for c in table.columns)
    key = ", ".join(_quoted(c) for c in table.key)
    where = ""
    params: tuple[Any, ...] = ()
    if after is not None:
        where = f" WHERE ({key}) > ({', '.join('?' * len(table.key))})"
        params = tuple(after)
    return [
        tuple(row)
        for row in db.execute(
            f"SELECT {columns} FROM {_quoted(table.name)}{where}"
            f" ORDER BY {key} LIMIT ?",
            (*params, size),
        )
    ]


def key_of(table: Table, row: Sequence[Any]) -> tuple[Any, ...]:
    """The key of ``row``, a row of ``table`` as ``read_chunk`` reads it."""
    return tuple(row[table.columns.index(c)] for c in table.key)


def fill_table(
    db: sqlite3.Connection,
    table: Table,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    size: int,
) -> int:
    """Write ``rows``, each with the values of ``columns``, into ``table``,
    which holds none yet: only ``meta`` holds what the migrations wrote,
    and a row of the same key replaces it. Answers how many."""
    unknown = [c for c in columns if c not in table.columns]
    if unknown or len(set(columns)) != len(columns):
        raise StorageError(f"the columns do not fit the table {table.name}")
    if (
        table.name != META
        and db.execute(f"SELECT 1 FROM {_quoted(table.name)} LIMIT 1").fetchone()
    ):
        raise StorageError(f"the table {table.name} is not empty")
    names = [table.columns[table.columns.index(c)] for c in columns]
    statement = (
        f"INSERT INTO {_quoted(table.name)} ({', '.join(map(_quoted, names))})"
        f" VALUES ({', '.join('?' * len(names))})"
    )
    if table.name == META:
        key = ", ".join(map(_quoted, table.key))
        update = ", ".join(f"{_quoted(c)} = excluded.{_quoted(c)}" for c in names)
        statement += f" ON CONFLICT ({key}) DO UPDATE SET {update}"
    count = 0
    stream = iter(rows)
    while part := list(islice(stream, size)):
        db.executemany(statement, part)
        count += len(part)
    return count


def align_changes(db: sqlite3.Connection) -> None:
    """The counter of the change feed at least at the last number handed
    out, so a feed whose newest rows were purged never hands one out
    again."""
    row = db.execute("SELECT value FROM meta WHERE key = 'changes_last'").fetchone()
    if row is None or row[0] is None:
        return
    last = int(row[0])
    updated = db.execute(
        "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'changes'", (last,)
    ).rowcount
    if not updated:
        db.execute(
            "INSERT INTO sqlite_sequence (name, seq) VALUES ('changes', ?)", (last,)
        )


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
