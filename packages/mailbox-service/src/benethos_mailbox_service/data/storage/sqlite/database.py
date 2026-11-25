"""The database the repositories use: one connection per process,
guarded by a lock, since every call is short, its transactions and its
queries. What hangs on the file, its schema and ``sqlite3`` itself is in
``file``. Every failure of sqlite3 leaves this module as a
MailboxServiceError: a constraint as ConflictError, anything else as
StorageError.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from ....common.chunks import batched
from ....common.clock import iso
from ....errors import StorageError, missing
from . import file
from .file import Migrated, translated
from .migrations import SCHEMA_VERSION
from .tables import (
    Table,
    align_changes,
    fill_table,
    key_of,
    read_chunk,
    read_tables,
)

T = TypeVar("T")
# Stays below SQLite's limit of host parameters in one statement.
IN_CHUNK = 500
# The rows of a table read or written at once by an export.
ROWS_CHUNK = 500


class Database:
    """The database at ``path``, readable by its owner alone. Without a
    path it lives in memory, for tests. ``keep_copy``: a file of a schema
    before ``COPY_BEFORE`` is copied before it is migrated. ``schema``: a
    new database is made at that schema and migrated no further, to take
    the records of an export of it."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        keep_copy: bool = True,
        schema: int | None = None,
    ) -> None:
        self._path = path
        self._connection, migrated = file.open_file(
            path,
            keep_copy=keep_copy,
            schema=SCHEMA_VERSION if schema is None else schema,
        )
        self._lock = threading.RLock()
        self._depth = 0  # of savepoints inside the open transaction
        # Set when opening migrated the schema. The data layer logs
        # nothing: the service logs it at start.
        self.migrated: Migrated | None = migrated

    def purge(self, table: str, column: str, before: datetime) -> int:
        """The rows of ``table`` whose time in ``column`` lies before
        ``before``, deleted, and the file shrunk after. Answers how many.
        ``table`` and ``column`` are names in code, never a caller's."""
        removed = self.execute(
            f"DELETE FROM {table} WHERE {column} < ?", (iso(before),)
        )
        if removed:
            self.shrink()
        return removed

    def shrink(self) -> None:
        """Give the pages a deletion freed back to the file system, so the
        file follows what it holds. Cheap when there is nothing to give
        back. Inside a transaction it waits for the next call."""
        with self._lock:
            if self._connection.in_transaction:
                return
            file.shrink(self._connection)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One transaction. Inside another one, a savepoint: it is released
        into the outer transaction, or rolled back alone."""
        with self._lock:
            if self._connection.in_transaction:
                with self._savepoint():
                    yield self._connection
                return
            with translated():
                self._connection.execute("BEGIN IMMEDIATE")
            try:
                with translated():
                    yield self._connection
                    self._connection.execute("COMMIT")
            except BaseException:
                self._rollback("ROLLBACK")
                raise

    @contextmanager
    def _savepoint(self) -> Iterator[None]:
        self._depth += 1
        name = f"sp{self._depth}"
        try:
            with translated():
                self._connection.execute(f"SAVEPOINT {name}")
            try:
                with translated():
                    yield
                    self._connection.execute(f"RELEASE {name}")
            except BaseException:
                self._rollback(f"ROLLBACK TO {name}")
                self._rollback(f"RELEASE {name}")
                raise
        finally:
            self._depth -= 1

    def _rollback(self, statement: str) -> None:
        """Undo as far as possible. A failure here would only hide the
        one being raised."""
        with suppress(sqlite3.Error):
            self._connection.execute(statement)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock, translated():
            return self._connection.execute(sql, params).fetchall()

    def query_in(
        self,
        sql: str,
        values: Iterable[Any],
        before: tuple[Any, ...] = (),
        after: tuple[Any, ...] = (),
    ) -> list[sqlite3.Row]:
        """The rows of ``sql`` for every value, each once. ``{in}`` in
        ``sql`` stands for ``IN (...)`` of the values, ``before`` and
        ``after`` are the parameters around them. In chunks of
        ``IN_CHUNK``, since SQLite caps the parameters of one statement:
        the rows come chunk by chunk, not in the order of one query."""
        rows: list[sqlite3.Row] = []
        for chunk in batched(list(dict.fromkeys(values)), IN_CHUNK):
            marks = ", ".join("?" * len(chunk))
            rows += self.query(
                sql.replace("{in}", f"IN ({marks})"), (*before, *chunk, *after)
            )
        return rows

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """The first row, or None."""
        with self._lock, translated():
            row: sqlite3.Row | None = self._connection.execute(sql, params).fetchone()
            return row

    def one_as(
        self, read: Callable[[sqlite3.Row], T], sql: str, params: tuple[Any, ...] = ()
    ) -> T | None:
        """The first row as ``read`` makes it a record, or None."""
        row = self.one(sql, params)
        return None if row is None else read(row)

    def query_as(
        self, read: Callable[[sqlite3.Row], T], sql: str, params: tuple[Any, ...] = ()
    ) -> list[T]:
        """Every row as ``read`` makes it a record."""
        return [read(row) for row in self.query(sql, params)]

    def scalar(self, sql: str, params: tuple[Any, ...] = (), default: int = 0) -> int:
        """The first value of the first row, a number, or ``default``
        without a row."""
        row = self.one(sql, params)
        return default if row is None or row[0] is None else int(row[0])

    def must_find(
        self, sql: str, params: tuple[Any, ...], what: str, row_id: str
    ) -> sqlite3.Row:
        """``one`` for a row that must be there: NotFoundError when not."""
        row = self.one(sql, params)
        if row is None:
            raise missing(what, row_id)
        return row

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """One statement in a transaction of its own. Returns the rows it changed."""
        with self.transaction() as db:
            return db.execute(sql, params).rowcount

    def must_change(
        self, sql: str, params: tuple[Any, ...], what: str, row_id: str
    ) -> None:
        """``execute`` for a statement about one row: NotFoundError when
        the row is not there."""
        if not self.execute(sql, params):
            raise missing(what, row_id)

    def serving(self) -> AbstractContextManager[bool]:
        """Mark the database as used by a running service, for as long as
        the block runs, so that a restore refuses to replace it. Yields
        False when another service marked it already."""
        return file.serving(self._path)

    def tables(self) -> list[Table]:
        """Every table of the schema with its columns and key, each after
        the tables it refers to."""
        with self._lock, translated():
            return read_tables(self._connection)

    def rows(self, table: str) -> Iterator[tuple[Any, ...]]:
        """The rows of ``table``, a table of ``tables``, as tuples of its
        columns in the order of its key. Read in chunks, each under the
        lock, so the whole table is never in memory."""
        shape = self._table(table)
        after: tuple[Any, ...] | None = None
        while True:
            with self._lock, translated():
                part = read_chunk(self._connection, shape, after, ROWS_CHUNK)
            yield from part
            if len(part) < ROWS_CHUNK:
                return
            after = key_of(shape, part[-1])

    def fill(
        self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
    ) -> int:
        """Write ``rows`` into ``table``, which holds none yet, in one
        transaction. The change feed then counts on from the last number
        it handed out. Answers how many rows."""
        shape = self._table(table)
        with self.transaction() as db:
            count = fill_table(db, shape, columns, rows, ROWS_CHUNK)
            align_changes(db)
        return count

    def _table(self, name: str) -> Table:
        for table in self.tables():
            if table.name == name:
                return table
        raise StorageError(f"the schema has no table {name}")

    def schema_version(self) -> int:
        with self._lock:
            return file.schema_version(self._connection)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def snapshot_file(self) -> AbstractContextManager[Path]:
        """A consistent copy of the whole database, taken while it is in
        use, as a file beside it, readable by its owner alone. It is gone
        when the block ends. A copy left by a crash is replaced. Another
        process making one at the same time is refused."""
        return file.snapshot(self._connection, self._path, self._lock)
