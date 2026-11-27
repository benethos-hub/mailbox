"""The database a program's repositories use: an engine of SQLAlchemy on
the one connection of the process, guarded by a lock, since every call
is short.

Where the database lies, and what hangs on that, comes from its place
(``place``): the connection itself, for a file of SQLite also the steps
of its schema before the revisions (``file_place``). From the baseline
of the shape on the revisions make and move the schema. Transactions
are SQLAlchemy's: one begins as ``dialect.begin_at_once`` says, and one
inside another is a savepoint. A failure of the database leaves this
module as its place translates it, an error of the shape: a constraint
as a conflict, anything else as a failure, never with the text of
SQLAlchemy, which would hold the statement and its values.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from . import tables
from .clock import iso
from .errors import Errors, StorageUnavailableError
from .file_place import FilePlace
from .migrated import Migrated
from .outage import Availability
from .place import Place
from .revisions import Revisions
from .shape import Shape
from .tables import Fixed, Table


class Database:
    """The database of ``shape`` at ``path``, a file readable by its owner
    alone. Without a path it lives in memory, for tests and to check a
    backup. Or the one at ``place``, where ``path`` and ``keep_copy``
    mean nothing. ``keep_copy``: a file of a schema before the
    revisions is copied before a step that rebuilds tables, and before a
    revision that asks for a copy.
    ``schema``: a new database is made at that schema and migrated no
    further, to take the records of an export of it. A database whose
    schema and mark of the revisions disagree is refused."""

    def __init__(
        self,
        shape: Shape,
        path: Path | None = None,
        *,
        keep_copy: bool = True,
        schema: int | None = None,
        place: Place | None = None,
    ) -> None:
        self.shape = shape
        self._revisions = Revisions(shape.versions)
        self._place: Place = (
            FilePlace(path, shape, keep_copy=keep_copy) if place is None else place
        )
        upto = shape.newest if schema is None else schema
        self._lock = threading.RLock()
        try:
            opened = self._place.open(upto, shape.newest)
            self._connection = opened.connection
            migrated = opened.migrated
            with self._place.translated():
                migrated = self._revised(upto, migrated)
        except BaseException:
            self.close()
            raise
        # Set when opening migrated the schema. The storage logs nothing:
        # the program logs it at start.
        self.migrated: Migrated | None = migrated

    @property
    def errors(self) -> Errors:
        """What the database raises."""
        return self.shape.errors

    def _revised(self, upto: int, migrated: Migrated | None) -> Migrated | None:
        """The revisions from the baseline on, after the steps of a file. A
        new database is made by them. One the steps of its file brought
        to the baseline is marked as there. What the opening did, with
        ``migrated``, what the steps of its file did."""
        shape = self.shape
        if upto < shape.baseline:
            return migrated
        conn = self._connection
        with conn.begin():
            held = tables.stored_schema(conn, shape)
            if sa.inspect(conn).has_table(shape.meta.name) and tables.move_begun(
                conn, shape
            ):
                raise shape.errors.failed(
                    "a move or restore into this database did not"
                    " finish: empty it and try again"
                )
        if held > shape.newest:
            # On SQLite the steps of the file refuse it first, in the same
            # words.
            raise shape.errors.failed(
                f"database schema {held} is newer than this version supports "
                f"({shape.newest}): run a newer version of the {shape.noun}"
            )
        marked = self._revisions.mark(conn)
        if marked is None and held == 0:
            return Migrated(0, upto, tuple(self._revisions.upgrade(conn, upto)))
        if marked is None:
            self._revisions.stamp(conn, held)
            marked = held
        if marked != held:
            raise shape.errors.failed(
                f"the database says schema {held} and its revisions {marked}:"
                " restore a backup"
            )
        if held >= upto:
            return migrated
        notes = list(() if migrated is None else migrated.notes)
        notes += self._copy_before(held, upto)
        notes += self._revisions.upgrade(conn, upto)
        before = held if migrated is None else migrated.before
        return Migrated(before, upto, tuple(notes))

    def _copy_before(self, held: int, upto: int) -> list[str]:
        """A copy of the database at schema ``held`` when a revision on
        the way to ``upto`` asks for one, named after the first that does,
        where the place keeps copies."""
        asking = [s for s in self._revisions.pending(held, upto) if s.keeps_copy]
        if not asking:
            return []
        kept = self._place.keep_copy(held, asking[0].version)
        if kept is None:
            return []
        return [f"a copy of the database at schema {held} is kept: {kept}"]

    @contextmanager
    def connected(self) -> Iterator[sa.Connection]:
        """The connection of SQLAlchemy in one transaction, for reading as
        for writing: a read too ends its transaction, or the next could not
        begin. Inside another one, a savepoint: it is released into the
        outer transaction, or rolled back alone."""
        with self._lock, self._place.translated():
            if self._connection.in_transaction():
                with self._connection.begin_nested():
                    yield self._connection
                return
            self._place.ready()
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
        self._place.undo()

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
            self._place.shrink()

    def unavailable(self) -> StorageUnavailableError | None:
        """The error a call meets now, without asking the database: None
        unless it is known to be away."""
        return self._place.unavailable()

    def watch(self, report: Callable[[Availability], None]) -> None:
        """``report`` hears of each change of whether the database can be
        reached, from the thread of the call that noticed it."""
        self._place.watch(report)

    def serving(self) -> AbstractContextManager[bool]:
        """Mark the database as used by a running program, for as long as
        the block runs, so that a restore refuses to replace it. A file
        yields False when another program marked it already, a server
        raises the error of a database in use."""
        return self._place.serving()

    def tables(self) -> list[Table]:
        """Every table of the schema with its columns and key, each after
        the tables it refers to."""
        with self.connected() as conn:
            return tables.read_tables(conn, self.shape)

    def rows(self, table: str) -> Iterator[tuple[Any, ...]]:
        """The rows of ``table``, a table of ``tables``, as tuples of its
        columns in the order of its key. Read in chunks, each under the
        lock, so the whole table is never in memory."""

        def part(
            shape: Table, after: Sequence[Any] | None, size: int
        ) -> list[tuple[Any, ...]]:
            with self.connected() as conn:
                return tables.read_chunk(
                    conn, shape, after, size, meta=self.shape.meta.name
                )

        yield from tables.chunked_rows(self._table(table), part)

    def fill(
        self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
    ) -> int:
        """Write ``rows`` into ``table``, which holds none yet, in one
        transaction. A counting key then counts on after the numbers the
        rows hold, and what the shape says follows a fill. Answers how
        many rows."""
        shape = self._table(table)
        with self.connected() as conn:
            count = tables.fill_table(conn, shape, columns, rows, self.shape)
            tables.align_counter(conn, shape, self.shape)
            if self.shape.filled is not None:
                self.shape.filled(conn)
        return count

    def mark_move(self, started: str | None) -> None:
        """Mark the database as the target of a move that began at
        ``started``, or, with None, as one that ended. Opening a database
        with the mark is refused."""
        with self.connected() as conn:
            tables.mark_moving(conn, self.shape, started)

    def _table(self, name: str) -> Table:
        return tables.table_named(self.tables(), name, self.shape)

    def schema_version(self) -> int:
        """The schema the database is in, 0 before the first step."""
        with self.connected() as conn:
            return tables.stored_schema(conn, self.shape)

    @contextmanager
    def view(self) -> Iterator[Fixed]:
        """The records at one moment, for the time of the block, taken
        while the database is in use: its schema, its tables and their
        rows, as one transaction sees them."""
        with self._place.fixed(self._lock) as conn, self._place.translated():
            yield Fixed(conn, self.shape)

    def close(self) -> None:
        with self._lock:
            if hasattr(self, "_connection"):
                self._connection.close()
            self._place.close()

    def snapshot_file(self) -> AbstractContextManager[Path]:
        """A consistent copy of the whole database file, taken while it is
        in use, as a file beside it, readable by its owner alone. It is
        gone when the block ends. A copy left by a crash is replaced.
        Another process making one at the same time is refused. A
        database that is not a file has none."""
        return self._place.snapshot_file(self._lock)
