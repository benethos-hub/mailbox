"""The database the repositories use: an engine of SQLAlchemy on the one
connection of the process, guarded by a lock, since every call is short.

The file, its schema up to 26 and the connection itself come from
``sqlite/file``, the one place under ``sql/`` that reaches into
``sqlite/``. From schema 26 on the revisions of ``revisions/`` make and
move the schema. Transactions
are SQLAlchemy's: one begins as ``dialect.begin`` says, and one inside
another is a savepoint. A failure of the database leaves this module as a
MailboxServiceError, a constraint as ConflictError, anything else as
StorageError, with the text of the driver and never one of SQLAlchemy,
which would hold the statement and its values.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from ....common.clock import iso
from ....errors import ConflictError, StorageError
from ..sqlite import file
from ..sqlite.file import Migrated
from . import revisions
from .dialect import sqlite_engine
from .revisions import SCHEMA_VERSION
from .schema import meta
from .tables import (
    Table,
    align_changes,
    fill_table,
    key_of,
    read_chunk,
    read_tables,
)

# The rows of a table read or written at once by an export.
ROWS_CHUNK = 500


class Database:
    """The database at ``path``, readable by its owner alone. Without a
    path it lives in memory, for tests. ``keep_copy``: a file of a schema
    before ``COPY_BEFORE`` is copied before it is migrated. ``schema``: a
    new database is made at that schema and migrated no further, to take
    the records of an export of it. A database whose schema and mark of
    the revisions disagree is refused."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        keep_copy: bool = True,
        schema: int | None = None,
    ) -> None:
        self._path = path
        upto = SCHEMA_VERSION if schema is None else schema
        self._driver, migrated = file.open_file(
            path, keep_copy=keep_copy, schema=upto, newest=SCHEMA_VERSION
        )
        self._lock = threading.RLock()
        try:
            driver = self._driver
            self._engine = sqlite_engine(lambda: driver)
            self._connection = self._engine.connect()
            with translated():
                migrated = self._revised(upto, migrated)
        except BaseException:
            self.close()
            raise
        # Set when opening migrated the schema. The data layer logs
        # nothing: the service logs it at start.
        self.migrated: Migrated | None = migrated

    def _revised(self, upto: int, migrated: Migrated | None) -> Migrated | None:
        """The revisions from schema 26 on, after the old steps. A new
        database is made by them. One the old steps brought to 26 is
        marked as there. What the opening did, with ``migrated``, what the
        old steps did."""
        if upto < revisions.BASELINE:
            return migrated
        conn = self._connection
        with conn.begin():
            held = 0
            if sa.inspect(conn).has_table(meta.name):
                stored = conn.execute(
                    sa.select(meta.c.value).where(meta.c.key == "schema_version")
                ).scalar()
                held = 0 if stored is None else int(stored)
        marked = revisions.mark(conn)
        if marked is None and held == 0:
            revisions.upgrade(conn, upto)
            return Migrated(0, upto)
        if marked is None:
            revisions.stamp(conn, held)
            marked = held
        if marked != held:
            raise StorageError(
                f"the database says schema {held} and its revisions {marked}:"
                " restore a backup"
            )
        if held >= upto:
            return migrated
        revisions.upgrade(conn, upto)
        before = held if migrated is None else migrated.before
        notes = () if migrated is None else migrated.notes
        return Migrated(before, upto, notes)

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
    def transaction(self) -> Iterator[None]:
        """One transaction, as ``connected``, around calls that succeed
        or fail together."""
        with self.connected():
            yield

    def purge(self, table: sa.Table, column: str, before: datetime) -> int:
        """The rows of ``table`` whose time in ``column`` lies before
        ``before``, deleted, and the file shrunk after. Answers how many.
        ``column`` is a name in code, never a caller's."""
        with self.connected() as conn:
            removed: int = conn.execute(
                sa.delete(table).where(table.c[column] < iso(before))
            ).rowcount
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
            if hasattr(self, "_connection"):
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
    values. A failure SQLAlchemy raises before the driver is named by its
    kind alone. The driver's own errors, from the connection used
    directly, are translated by ``file``."""
    try:
        with file.translated():
            yield
    except sa.exc.IntegrityError as exc:
        raise ConflictError(f"conflicts with a stored record: {exc.orig}") from None
    except sa.exc.DBAPIError as exc:
        raise StorageError(f"the database failed: {exc.orig}") from None
    except sa.exc.SQLAlchemyError as exc:
        # Refused before the driver saw it, such as a value that does not
        # fit its column. Its text, and the one of its cause, can hold the
        # statement and the value: only the kind is named.
        cause = getattr(exc, "orig", None) or exc
        raise StorageError(f"the database failed: {type(cause).__name__}") from None


def migrate_file(path: Path) -> None:
    """Bring the database file at ``path`` to this version's schema, by
    the old steps and the revisions. It comes from a backup, which is its
    copy: none is kept beside it."""
    Database(path, keep_copy=False).close()
