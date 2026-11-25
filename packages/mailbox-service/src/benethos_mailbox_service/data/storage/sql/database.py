"""The database the repositories use: an engine of SQLAlchemy on the one
connection of the process, guarded by a lock, since every call is short.

The file, its schema and the connection itself come from ``sqlite/file``,
the one place under ``sql/`` that reaches into ``sqlite/``. Transactions
are SQLAlchemy's: one begins as ``dialect.begin`` says, and one inside
another is a savepoint. A failure of the database leaves this module as a
MailboxServiceError, a constraint as ConflictError, anything else as
StorageError, with the text of the driver and never one of SQLAlchemy,
which would hold the statement and its values.

For the time of the move to SQLAlchemy the old repositories still hand
SQL as text to ``query``, ``execute`` and the methods beside them, and
``transaction`` gives them the connection of the driver.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import sqlalchemy as sa

from ....common.clock import iso
from ....errors import ConflictError, StorageError, missing
from ..sqlite import file
from ..sqlite.file import Migrated
from ..sqlite.migrations import SCHEMA_VERSION
from .dialect import in_chunks, sqlite_engine
from .tables import (
    Table,
    align_changes,
    fill_table,
    key_of,
    read_chunk,
    read_tables,
)

T = TypeVar("T")
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
        self._driver, migrated = file.open_file(
            path,
            keep_copy=keep_copy,
            schema=SCHEMA_VERSION if schema is None else schema,
        )
        self._lock = threading.RLock()
        try:
            driver = self._driver
            self._engine = sqlite_engine(lambda: driver)
            self._connection = self._engine.connect()
        except BaseException:
            self._driver.close()
            raise
        # Set when opening migrated the schema. The data layer logs
        # nothing: the service logs it at start.
        self.migrated: Migrated | None = migrated

    @contextmanager
    def connected(self) -> Iterator[sa.Connection]:
        """The connection of SQLAlchemy in one transaction, for reading as
        for writing: a read too ends its transaction, or the next could not
        begin. Inside another one, a savepoint: it is released into the
        outer transaction, or rolled back alone."""
        with self._lock, translated():
            if self._connection.in_transaction():
                with self._connection.begin_nested():
                    yield self._connection
                return
            try:
                with self._connection.begin():
                    yield self._connection
            except BaseException:
                self._undo()
                raise

    def _undo(self) -> None:
        """No transaction left open after one failed, also not after a
        failed COMMIT, which SQLAlchemy forgets without telling the
        database. A failure here would only hide the one being raised."""
        with suppress(Exception):
            if self._driver.in_transaction:
                self._driver.rollback()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """One transaction, as ``connected``. Gives the connection of the
        driver, for the repositories that still hand it SQL as text."""
        with self.connected():
            yield self._driver

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
            if self._connection.in_transaction():
                return
            file.shrink(self._driver)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with self._lock, translated():
            rows: list[Any] = self._driver.execute(sql, params).fetchall()
            return rows

    def query_in(
        self,
        sql: str,
        values: Iterable[Any],
        before: tuple[Any, ...] = (),
        after: tuple[Any, ...] = (),
    ) -> list[Any]:
        """The rows of ``sql`` for every value, each once. ``{in}`` in
        ``sql`` stands for ``IN (...)`` of the values, ``before`` and
        ``after`` are the parameters around them. In chunks, since a
        database caps the parameters of one statement: the rows come
        chunk by chunk, not in the order of one query."""
        rows: list[Any] = []
        for chunk in in_chunks(values):
            marks = ", ".join("?" * len(chunk))
            rows += self.query(
                sql.replace("{in}", f"IN ({marks})"), (*before, *chunk, *after)
            )
        return rows

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        """The first row, or None."""
        with self._lock, translated():
            return self._driver.execute(sql, params).fetchone()

    def one_as(
        self, read: Callable[[Any], T], sql: str, params: tuple[Any, ...] = ()
    ) -> T | None:
        """The first row as ``read`` makes it a record, or None."""
        row = self.one(sql, params)
        return None if row is None else read(row)

    def query_as(
        self, read: Callable[[Any], T], sql: str, params: tuple[Any, ...] = ()
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
    ) -> Any:
        """``one`` for a row that must be there: NotFoundError when not."""
        row = self.one(sql, params)
        if row is None:
            raise missing(what, row_id)
        return row

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """One statement in a transaction of its own. Returns the rows it changed."""
        with self.transaction() as db:
            changed: int = db.execute(sql, params).rowcount
            return changed

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
        with self.connected() as conn:
            return read_tables(conn)

    def rows(self, table: str) -> Iterator[tuple[Any, ...]]:
        """The rows of ``table``, a table of ``tables``, as tuples of its
        columns in the order of its key. Read in chunks, each under the
        lock, so the whole table is never in memory."""
        shape = self._table(table)
        after: tuple[Any, ...] | None = None
        while True:
            with self.connected() as conn:
                part = read_chunk(conn, shape, after, ROWS_CHUNK)
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
        with self.connected() as conn:
            count = fill_table(conn, shape, columns, rows, ROWS_CHUNK)
            align_changes(conn)
        return count

    def _table(self, name: str) -> Table:
        for table in self.tables():
            if table.name == name:
                return table
        raise StorageError(f"the schema has no table {name}")

    def schema_version(self) -> int:
        with self._lock:
            return file.schema_version(self._driver)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
            self._engine.dispose()
            self._driver.close()

    def snapshot_file(self) -> AbstractContextManager[Path]:
        """A consistent copy of the whole database, taken while it is in
        use, as a file beside it, readable by its owner alone. It is gone
        when the block ends. A copy left by a crash is replaced. Another
        process making one at the same time is refused."""
        return file.snapshot(self._driver, self._path, self._lock)


@contextmanager
def translated() -> Iterator[None]:
    """The failures of the database as this project's errors, with the
    text of the driver: the one of SQLAlchemy holds the statement and its
    values. The driver's own errors, from the connection used directly,
    are translated by ``file``."""
    try:
        with file.translated():
            yield
    except sa.exc.IntegrityError as exc:
        raise ConflictError(f"conflicts with a stored record: {exc.orig}") from None
    except sa.exc.DBAPIError as exc:
        raise StorageError(f"the database failed: {exc.orig}") from None
