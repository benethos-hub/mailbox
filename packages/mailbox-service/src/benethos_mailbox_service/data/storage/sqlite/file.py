"""The database file and what hangs on ``sqlite3``: the connection and its
PRAGMAs, the file readable by its owner alone, the files SQLite keeps
beside it, the file rewritten once to shrink, the schema migrated
forward on open by the steps of ``migrations/`` with a copy kept before
schema ``COPY_BEFORE``, a snapshot of the file, the lock of a running
service. Every failure of sqlite3 leaves as a MailboxServiceError: a
constraint as ConflictError, anything else as StorageError.
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

from benethos_mailbox_common.paths import locks

from ....common.clock import utc_now
from ....errors import ConflictError, StorageError
from ...files import create_private, free_path
from .migrations import MIGRATIONS, SCHEMA_VERSION

# What SQLite keeps beside a database: its rollback journal, its write
# ahead log and the index of the shared memory.
SIDECARS = ("-journal", "-wal", "-shm")

# Opening a database of an older schema keeps a copy of it first: the
# step to this schema rebuilds tables (docs/mailbox-service/concept/security.md 7.8).
COPY_BEFORE = 26

# PRAGMA auto_vacuum: 0 none, 1 full, 2 incremental.
_INCREMENTAL = 2


@dataclass(frozen=True, slots=True)
class Migrated:
    """What opening the database did to its schema, for the log: the
    versions before and after, and what the migrations had to say."""

    before: int
    after: int
    notes: tuple[str, ...] = ()


def open_file(
    path: Path | None, *, keep_copy: bool, schema: int
) -> tuple[sqlite3.Connection, Migrated | None]:
    """The connection to the database at ``path``, readable by its owner
    alone, in memory without a path, its schema migrated to ``schema``.
    What opening did to the schema, None when nothing. ``keep_copy``: a
    file before ``COPY_BEFORE`` is copied before it is migrated."""
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
        rewritten = _shrinkable(connection)
        migrated = _migrate(connection, path, schema, keep_copy, rewritten)
    except BaseException:
        connection.close()
        raise
    return connection, migrated


def _shrinkable(connection: sqlite3.Connection) -> bool:
    """Freed pages are handed back to the file system by ``shrink``,
    which needs ``auto_vacuum`` in its incremental mode. A new database
    takes the mode as it is. One made without it is rewritten once,
    which VACUUM does outside any transaction: then True."""
    with translated():
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


def shrink(connection: sqlite3.Connection) -> None:
    """Give the pages a deletion freed back to the file system, so the
    file follows what it holds. Cheap when there is nothing to give
    back. Not inside a transaction: the caller waits for the next call."""
    with translated():
        # The pragma gives one page back per step. ``executescript``
        # steps until it is done. ``execute`` stops after the first
        # step on Python 3.11, and nothing to speak of happens.
        connection.executescript("PRAGMA incremental_vacuum;")


@contextmanager
def _step(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One transaction of a step of the schema."""
    with translated():
        connection.execute("BEGIN IMMEDIATE")
    try:
        with translated():
            yield connection
            connection.execute("COMMIT")
    except BaseException:
        # Undo as far as possible. A failure here would only hide the
        # one being raised.
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")
        raise


def _migrate(
    connection: sqlite3.Connection,
    path: Path | None,
    upto: int,
    keep: bool,
    rewritten: bool,
) -> Migrated | None:
    """``rewritten``: the file was rewritten to shrink from now on,
    said with the notes of the schema."""
    with _step(connection) as db:
        MIGRATIONS.prepare(db)
    current = schema_version(connection)
    if current > SCHEMA_VERSION:
        raise StorageError(
            f"database schema {current} is newer than this version supports "
            f"({SCHEMA_VERSION}): run a newer version of the service"
        )
    if not current <= upto <= SCHEMA_VERSION:
        raise StorageError(f"there is no way from schema {current} to {upto}")
    kept = None
    if keep and path is not None and 0 < current < COPY_BEFORE:
        kept = _keep_copy(connection, path, current)
    notes: list[str] = []
    for migration in MIGRATIONS.pending(current)[: upto - current]:
        with _step(connection) as db:
            notes += MIGRATIONS.apply(db, migration)
    if kept is not None:
        notes.append(f"a copy of the database at schema {current} is kept: {kept}")
    if rewritten:
        notes.append(
            "the file was rewritten once: from now on it shrinks after deletions"
        )
    if current < upto or rewritten:
        return Migrated(current, upto, tuple(notes))
    return None


def _keep_copy(connection: sqlite3.Connection, path: Path, current: int) -> str:
    """A copy of the database beside ``path``, readable by its owner
    alone, before the steps to schema ``COPY_BEFORE`` change it. It is
    never removed by the service. Answers its name. StorageError when
    it cannot be written, and then nothing is migrated."""
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    kept = free_path(path.with_name(f"{path.name}.before-schema-{COPY_BEFORE}-{stamp}"))
    try:
        create_private(kept)
    except OSError as exc:
        raise _not_copied(current, exc) from None
    try:
        with translated():
            _copy(connection, kept)
    except (OSError, StorageError) as exc:
        remove_database_file(kept)
        raise _not_copied(current, exc) from None
    return kept.name


def _not_copied(current: int, exc: Exception) -> StorageError:
    return StorageError(
        f"the database at schema {current} was not migrated: its copy"
        f" before schema {COPY_BEFORE} could not be written: {exc}"
    )


def _copy(connection: sqlite3.Connection, target: Path) -> None:
    copy = sqlite3.connect(str(target))
    try:
        connection.backup(copy)
    finally:
        copy.close()


def schema_version(connection: sqlite3.Connection) -> int:
    with translated():
        return MIGRATIONS.version_of(connection)


@contextmanager
def snapshot(
    connection: sqlite3.Connection, path: Path | None, lock: threading.RLock
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
            create_private(target)
            try:
                with lock, translated():
                    _copy(connection, target)
                yield target
            finally:
                remove_database_file(target)
    except locks.LockedError:
        raise StorageError("another backup of this database is running") from None
    finally:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)


@contextmanager
def serving(path: Path | None) -> Iterator[bool]:
    """Mark the database at ``path`` as used by a running service, for as
    long as the block runs, so that a restore refuses to replace it.
    Yields False when another service marked it already."""
    with ExitStack() as held:
        if path is not None:
            try:
                held.enter_context(locks.exclusive_lock(service_lock(path)))
            except locks.LockedError:
                yield False
                return
        yield True


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


def migrate_file(path: Path) -> None:
    """Bring the database file at ``path`` to this version's schema. It
    comes from a backup, which is its copy: none is kept beside it."""
    connection, _ = open_file(path, keep_copy=False, schema=SCHEMA_VERSION)
    connection.close()


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


def inspect_file(path: Path) -> int:
    """Check the integrity of the database file at ``path``, opened to
    read only, and return its schema version."""
    try:
        copy = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"not a database: {exc}") from None
    try:
        result = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"database integrity check failed: {result}")
        version = MIGRATIONS.version_of(copy)
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"not a database: {exc}") from None
    finally:
        copy.close()
    if not version:
        raise ValueError("not a database of this service")
    return version
