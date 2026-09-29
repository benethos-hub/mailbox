"""The connection, and the schema migrated forward on open.

One connection per process, guarded by a lock, since every call is short.
The schema is versioned in ``meta``, its migrations are in ``migrations/``. Every
failure of sqlite3 leaves this module as a MailboxServiceError: a
constraint as ConflictError, anything else as StorageError.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....common.chunks import batched
from ....errors import ConflictError, StorageError, missing
from ...files import LockedError, create_private, exclusive_lock
from .migrations import MIGRATIONS, SCHEMA_VERSION

# Stays below SQLite's limit of host parameters in one statement.
IN_CHUNK = 500
_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"


@dataclass(frozen=True)
class Migrated:
    """What opening the database did to its schema, for the log: the
    versions before and after, and what the migrations had to say."""

    before: int
    after: int
    notes: tuple[str, ...] = ()


# PRAGMA auto_vacuum: 0 none, 1 full, 2 incremental.
_INCREMENTAL = 2


class Database:
    """The database at ``path``, readable by its owner alone. Without a
    path it lives in memory, for tests."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _owner_only(path)
        self._connection = sqlite3.connect(
            str(path) if path is not None else ":memory:",
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0  # of savepoints inside the open transaction
        # Set when opening migrated the schema. The data layer logs
        # nothing: the service logs it at start.
        self.migrated: Migrated | None = None
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            # Freed pages are overwritten, so deleted secrets do not linger.
            self._connection.execute("PRAGMA secure_delete = ON")
            # Case folded as Python folds it, beyond ASCII too.
            self._connection.create_function(
                "casefold", 1, _casefold, deterministic=True
            )
        try:
            rewritten = self._shrinkable()
            self._migrate(rewritten)
        except BaseException:
            self._connection.close()
            raise

    def _shrinkable(self) -> bool:
        """Freed pages are handed back to the file system by ``shrink``,
        which needs ``auto_vacuum`` in its incremental mode. A new database
        takes the mode as it is. One made without it is rewritten once,
        which VACUUM does outside any transaction: then True."""
        with self._lock, translated():
            mode = self._connection.execute("PRAGMA auto_vacuum").fetchone()[0]
            if mode == _INCREMENTAL:
                return False
            self._connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
            has_tables = self._connection.execute(
                "SELECT 1 FROM sqlite_master LIMIT 1"
            ).fetchone()
            if has_tables is None:
                return False
            self._connection.execute("VACUUM")
            return True

    def shrink(self) -> None:
        """Give the pages a deletion freed back to the file system, so the
        file follows what it holds. Cheap when there is nothing to give
        back. Inside a transaction it waits for the next call."""
        with self._lock:
            if self._connection.in_transaction:
                return
            with translated():
                # The pragma gives one page back per step. ``executescript``
                # steps until it is done. ``execute`` stops after the first
                # step on Python 3.11, and nothing to speak of happens.
                self._connection.executescript("PRAGMA incremental_vacuum;")

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
        try:
            self._connection.execute(statement)
        except sqlite3.Error:
            pass

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

    @contextmanager
    def serving(self) -> Iterator[bool]:
        """Mark the database as used by a running service, for as long as
        the block runs, so that a restore refuses to replace it. Yields
        False when another service marked it already."""
        with ExitStack() as held:
            if self._path is not None:
                try:
                    held.enter_context(exclusive_lock(service_lock(self._path)))
                except LockedError:
                    yield False
                    return
            yield True

    def schema_version(self) -> int:
        row = self.one(_SCHEMA_VERSION)
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def snapshot(self) -> bytes:
        """A consistent copy of the whole database, taken while it is in use."""
        with self._lock, translated():
            copy = sqlite3.connect(":memory:")
            try:
                self._connection.backup(copy)
                return copy.serialize()
            finally:
                copy.close()

    def _migrate(self, rewritten: bool = False) -> None:
        """``rewritten``: the file was rewritten to shrink from now on,
        said with the notes of the schema."""
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
            )
        current = self.schema_version()
        if current > SCHEMA_VERSION:
            raise StorageError(
                f"database schema {current} is newer than this version supports "
                f"({SCHEMA_VERSION}): run a newer version of the service"
            )
        notes: list[str] = []
        for version, migration in enumerate(MIGRATIONS[current:], current + 1):
            with self.transaction() as db:
                said = migration.before(db) if migration.before else []
                for statement in migration.statements:
                    db.execute(statement)
                db.execute(
                    "INSERT OR REPLACE INTO meta (key, value)"
                    " VALUES ('schema_version', ?)",
                    (str(version),),
                )
            notes += [f"schema {version}: {note}" for note in said]
        if rewritten:
            notes.append(
                "the file was rewritten once: from now on it shrinks after deletions"
            )
        if current < SCHEMA_VERSION or rewritten:
            self.migrated = Migrated(current, SCHEMA_VERSION, tuple(notes))


@contextmanager
def translated() -> Iterator[None]:
    """sqlite3's failures as this project's errors. A violated constraint
    is a conflict with what is stored, the rest is the storage failing."""
    try:
        yield
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"conflicts with a stored record: {exc}") from None
    except sqlite3.Error as exc:
        raise StorageError(f"the database failed: {exc}") from None


def _casefold(value: str | None) -> str | None:
    return value.casefold() if isinstance(value, str) else value


def migrate_file(path: Path) -> None:
    """Bring the database file at ``path`` to this version's schema."""
    Database(path).close()


def service_lock(path: Path) -> Path:
    """The lock file a running service holds beside its database."""
    return path.with_name(path.name + ".lock")


def _owner_only(path: Path) -> None:
    """The file readable by its owner alone (0600): it holds the encrypted
    credentials and the token hashes. Created so when missing. An existing
    one that others may read is narrowed. SQLite gives its journal files
    the mode of the database. Windows has no such modes."""
    if not path.exists():
        create_private(path)
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        path.chmod(0o600)


def inspect_snapshot(data: bytes) -> int:
    """Check a snapshot's integrity and return its schema version."""
    copy = sqlite3.connect(":memory:")
    try:
        copy.deserialize(data)
        result = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"database integrity check failed: {result}")
        row = copy.execute(_SCHEMA_VERSION).fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"not a database: {exc}") from None
    finally:
        copy.close()
    if row is None:
        raise ValueError("not a database of this service")
    return int(row[0])
