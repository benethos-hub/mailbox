"""The database file and what hangs on ``sqlite3``: the connection and its
PRAGMAs, the file readable by its owner alone, the files SQLite keeps
beside it, the file rewritten once to shrink, the steps a file of the
program took before the revisions (``Shape.file_steps``), a copy before
a step, a snapshot of the file, the lock of a running program. A new
database is left to the revisions the caller runs after. Every failure
of sqlite3 leaves as an error of the shape: a constraint as a conflict,
anything else as a failure.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import tempfile
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from . import files, locks
from .clock import utc_now
from .errors import Errors, StorageError
from .migrated import Migrated
from .shape import Shape

# What SQLite keeps beside a database: its rollback journal, its write
# ahead log and the index of the shared memory.
SIDECARS = ("-journal", "-wal", "-shm")

# PRAGMA auto_vacuum: 0 none, 1 full, 2 incremental.
_INCREMENTAL = 2

# The schema a database says it is in, as the revisions write it.
_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"


@dataclass(frozen=True, slots=True)
class OpenedFile:
    """The connection to a database file, and what its steps did to its
    schema, None when nothing."""

    connection: sqlite3.Connection
    migrated: Migrated | None


def open_file(
    path: Path | None, shape: Shape, *, keep_copy: bool, schema: int, newest: int
) -> OpenedFile:
    """The connection to the database of ``shape`` at ``path``, readable
    by its owner alone, in memory without a path, its schema brought by
    the steps of its file to ``schema``, or to their last when ``schema``
    lies beyond. A new database for such a schema stays empty.
    ``keep_copy``: a copy of the file before a step that rebuilds tables.
    ``newest``: the schema of this version, a file beyond it is refused."""
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _owner_only(path)
    connection = sqlite3.connect(
        str(path) if path is not None else ":memory:",
        check_same_thread=False,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    # Freed pages are overwritten, so deleted secrets do not linger.
    connection.execute("PRAGMA secure_delete = ON")
    try:
        rewritten = _shrinkable(connection, shape.errors)
        if shape.file_steps is not None:
            migrated = shape.file_steps.run(
                connection, path, schema, newest, keep_copy, rewritten
            )
        else:
            migrated = _no_steps(connection, shape, schema, newest, rewritten)
    except BaseException:
        connection.close()
        raise
    return OpenedFile(connection, migrated)


def _no_steps(
    connection: sqlite3.Connection,
    shape: Shape,
    upto: int,
    newest: int,
    rewritten: bool,
) -> Migrated | None:
    """A file of a program without steps before its revisions: a new one
    is left to them, one beyond ``newest`` refused."""
    current = schema_version(connection, shape.errors)
    if current > newest:
        raise shape.errors.failed(
            f"database schema {current} is newer than this version supports "
            f"({newest}): run a newer version of the {shape.noun}"
        )
    if not current and upto > newest:
        raise shape.errors.failed(f"there is no way from schema 0 to {upto}")
    if rewritten:
        return Migrated(
            current,
            current,
            ("the file was rewritten once: from now on it shrinks after deletions",),
        )
    return None


def _shrinkable(connection: sqlite3.Connection, errors: Errors) -> bool:
    """Freed pages are handed back to the file system by ``shrink``,
    which needs ``auto_vacuum`` in its incremental mode. A new database
    takes the mode as it is. One made without it is rewritten once,
    which VACUUM does outside any transaction: then True."""
    with translated_sqlite(errors):
        mode = connection.execute("PRAGMA auto_vacuum").fetchone()[0]
        if mode == _INCREMENTAL:
            return False
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        has_tables = connection.execute(
            "SELECT 1 FROM sqlite_master LIMIT 1"
        ).fetchone()
        if has_tables is None:
            return False
        connection.execute("VACUUM")
        return True


def shrink(connection: sqlite3.Connection, errors: Errors) -> None:
    """Give the pages a deletion freed back to the file system, so the
    file follows what it holds, and empty the write-ahead log of a file
    in WAL mode. Cheap when there is nothing to give back. Not inside a
    transaction: the caller waits for the next call."""
    with translated_sqlite(errors):
        # The pragma gives one page back per step. ``executescript``
        # steps until it is done. ``execute`` stops after the first
        # step on Python 3.11, and nothing to speak of happens.
        connection.executescript("PRAGMA incremental_vacuum;")
        # A file in WAL mode keeps the freed pages in its log until it is
        # written back: then they are gone from both. Nothing for another
        # mode.
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()


@contextmanager
def in_step(
    connection: sqlite3.Connection, errors: Errors
) -> Iterator[sqlite3.Connection]:
    """One transaction of a step of the schema of a file."""
    with translated_sqlite(errors):
        connection.execute("BEGIN IMMEDIATE")
    try:
        with translated_sqlite(errors):
            yield connection
            connection.execute("COMMIT")
    except BaseException:
        # Undo as far as possible. A failure here would only hide the
        # one being raised.
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")
        raise


def has_meta(connection: sqlite3.Connection, errors: Errors) -> bool:
    """Whether the file holds the table ``meta``."""
    with translated_sqlite(errors):
        found = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
    return found is not None


def keep_copy(
    connection: sqlite3.Connection,
    path: Path,
    current: int,
    before: int,
    errors: Errors,
) -> str:
    """A copy of the database at schema ``current`` beside ``path``,
    readable by its owner alone, before the step to schema ``before``
    changes it. It is never removed by the program. Answers its name.
    A failure when it cannot be written, and then nothing is migrated."""
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    kept = files.free_path(
        path.with_name(f"{path.name}.before-schema-{before}-{stamp}")
    )
    try:
        files.create_private(kept)
    except OSError as exc:
        raise _not_copied(current, before, exc, errors) from None
    try:
        with translated_sqlite(errors):
            _copy(connection, kept)
    except (OSError, StorageError) as exc:
        remove_database_file(kept)
        raise _not_copied(current, before, exc, errors) from None
    return kept.name


def _not_copied(
    current: int, before: int, exc: Exception, errors: Errors
) -> StorageError:
    return errors.failed(
        f"the database at schema {current} was not migrated: its copy"
        f" before schema {before} could not be written: {exc}"
    )


def _copy(connection: sqlite3.Connection, target: Path) -> None:
    copy = sqlite3.connect(str(target))
    try:
        connection.backup(copy)
    finally:
        copy.close()


def schema_version(connection: sqlite3.Connection, errors: Errors) -> int:
    """The schema the file says it is in, 0 without the table ``meta``."""
    if not has_meta(connection, errors):
        return 0
    with translated_sqlite(errors):
        row = connection.execute(_VERSION).fetchone()
    return int(row[0]) if row else 0


@contextmanager
def snapshot(
    connection: sqlite3.Connection,
    path: Path | None,
    lock: threading.RLock,
    errors: Errors,
) -> Iterator[Path]:
    """A consistent copy of the whole database at ``path``, taken while it
    is in use, as a file beside it, readable by its owner alone. It is
    gone when the block ends. A copy left by a crash is replaced. Another
    process making one at the same time is refused. ``lock`` keeps the
    connection to the copy for the time it takes."""
    if path is None:
        folder = Path(tempfile.mkdtemp())
        target = folder / "snapshot.db"
    else:
        folder = None
        target = path.with_name(path.name + ".snapshot")
    try:
        with locks.exclusive_lock(target.with_name(target.name + ".lock")):
            remove_database_file(target)
            files.create_private(target)
            try:
                with lock, translated_sqlite(errors):
                    _copy(connection, target)
                yield target
            finally:
                remove_database_file(target)
    except locks.LockedError:
        raise errors.failed("another backup of this database is running") from None
    finally:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)


@contextmanager
def file_serving(path: Path | None) -> Iterator[bool]:
    """Mark the database at ``path`` as used by a running program, for as
    long as the block runs, so that a restore refuses to replace it.
    Yields False when another one marked it already."""
    with ExitStack() as held:
        if path is not None:
            try:
                held.enter_context(locks.exclusive_lock(lock_file(path)))
            except locks.LockedError:
                yield False
                return
        yield True


@contextmanager
def translated_sqlite(errors: Errors) -> Iterator[None]:
    """sqlite3's failures as ``errors`` names them. A violated constraint
    is a conflict with what is stored, the rest is the storage failing."""
    try:
        yield
    except sqlite3.IntegrityError as exc:
        raise errors.conflict(f"conflicts with a stored record: {exc}") from None
    except sqlite3.Error as exc:
        raise errors.failed(f"the database failed: {exc}") from None


def remove_database_file(path: Path) -> None:
    """Remove a database file and its ``-journal``, where they exist."""
    for leftover in (path, path.with_name(path.name + SIDECARS[0])):
        leftover.unlink(missing_ok=True)


def move_sidecars(target: Path, kept: Path) -> None:
    """Move what SQLite left beside the database at ``target`` to beside
    ``kept``, a copy of it: a journal left by a crash belongs to the old
    file, and beside a new one SQLite would roll it into that."""
    for suffix in SIDECARS:
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            sidecar.replace(kept.with_name(kept.name + suffix))


def lock_file(path: Path) -> Path:
    """The lock file a running program holds beside its database."""
    return path.with_name(path.name + ".lock")


def _owner_only(path: Path) -> None:
    """The file readable by its owner alone (0600): it may hold secrets
    and their hashes. Created so when missing. An existing one that
    others may read is narrowed. SQLite gives its journal files the mode
    of the database. Windows has no such modes."""
    if not path.exists():
        files.create_private(path)
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        path.chmod(0o600)


def inspect_file(path: Path, noun: str) -> int:
    """Check the integrity of the database file at ``path``, opened to
    read only, and return its schema version. ``noun``: the program a
    database of none is said not to be of."""
    try:
        copy = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"not a database: {exc}") from None
    return _inspected(copy, noun)


def inspect_bytes(data: bytes, noun: str) -> int:
    """As ``inspect_file``, for the bytes of a database file held in
    memory: nothing of it is written to a disk."""
    copy = sqlite3.connect(":memory:")
    try:
        copy.deserialize(data)
    except sqlite3.Error as exc:
        copy.close()
        raise ValueError(f"not a database: {exc}") from None
    return _inspected(copy, noun)


def _inspected(copy: sqlite3.Connection, noun: str) -> int:
    """The integrity of the database ``copy`` checked, its schema version,
    and ``copy`` closed."""
    try:
        result = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"database integrity check failed: {result}")
        found = copy.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
        row = copy.execute(_VERSION).fetchone() if found else None
        version = int(row[0]) if row else 0
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"not a database: {exc}") from None
    finally:
        copy.close()
    if not version:
        raise ValueError(f"not a database of this {noun}")
    return version
