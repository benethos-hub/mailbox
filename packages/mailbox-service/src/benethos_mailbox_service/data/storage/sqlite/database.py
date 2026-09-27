"""The connection, the schema and its migrations.

One connection per process, guarded by a lock, since every call is short.
The schema is versioned in ``meta`` and migrated forward on open. Every
failure of sqlite3 leaves this module as a MailboxServiceError: a
constraint as ConflictError, anything else as StorageError.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, overload

from ....errors import ConflictError, StorageError
from ...files import LockedError, create_private, exclusive_lock
from ..table import missing

MIGRATIONS: list[str] = [
    # 1: accounts, users, roles, tokens
    """
    CREATE TABLE accounts (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        email TEXT NOT NULL,
        display_name TEXT,
        status TEXT NOT NULL,
        settings TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        roles TEXT NOT NULL DEFAULT '[]',
        grants TEXT NOT NULL DEFAULT '[]',
        disabled INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE roles (
        id TEXT PRIMARY KEY,
        grants TEXT NOT NULL DEFAULT '[]'
    );
    CREATE TABLE tokens (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        last_used_at TEXT,
        revoked_at TEXT
    );
    """,
    # 2: the wrapped data key and encrypted credentials
    """
    CREATE TABLE keys (
        key_id TEXT PRIMARY KEY,
        nonce BLOB NOT NULL,
        ciphertext BLOB NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE credentials (
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        field TEXT NOT NULL,
        key_id TEXT NOT NULL REFERENCES keys(key_id),
        nonce BLOB NOT NULL,
        ciphertext BLOB NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (account_id, field)
    );
    """,
    # 3: the id mapping and the state of each folder
    """
    CREATE TABLE message_index (
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        id TEXT NOT NULL,
        native_id TEXT NOT NULL,
        folder_id TEXT NOT NULL,
        header TEXT,
        PRIMARY KEY (account_id, id),
        UNIQUE (account_id, native_id)
    );
    CREATE INDEX message_index_folder ON message_index (account_id, folder_id);
    CREATE TABLE folder_states (
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        folder_id TEXT NOT NULL,
        state TEXT NOT NULL,
        PRIMARY KEY (account_id, folder_id)
    );
    """,
    # 4: results of requests with an Idempotency-Key
    """
    CREATE TABLE idempotency (
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        operation TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        result TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (account_id, key)
    );
    CREATE INDEX idempotency_created ON idempotency (created_at);
    """,
    # 5: the audit of sends. It outlives its account and user, so no references
    """
    CREATE TABLE sends (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        user_id TEXT NOT NULL,
        credential_id TEXT,
        account_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        recipients TEXT NOT NULL,
        outcome TEXT NOT NULL,
        error TEXT,
        refused TEXT NOT NULL,
        message_id_header TEXT
    );
    CREATE INDEX sends_account ON sends (account_id, created_at);
    CREATE INDEX sends_user ON sends (user_id, account_id, created_at);
    """,
    # 6: the change log behind the change feed
    """
    CREATE TABLE changes (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        message_id TEXT NOT NULL,
        type TEXT NOT NULL,
        at TEXT NOT NULL
    );
    CREATE INDEX changes_account ON changes (account_id, seq);
    CREATE INDEX changes_at ON changes (at);
    """,
    # 7: webhooks, their sealed secret and where their delivery stands
    """
    CREATE TABLE webhooks (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        url TEXT NOT NULL,
        events TEXT NOT NULL,
        accounts TEXT,
        created_at TEXT NOT NULL,
        key_id TEXT NOT NULL REFERENCES keys(key_id),
        nonce BLOB NOT NULL,
        ciphertext BLOB NOT NULL,
        cursor INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        last_delivery_at TEXT,
        last_error TEXT
    );
    """,
    # 8: an Idempotency-Key counts per account and user. The results kept
    # are a cache of 24 hours, so the old ones are dropped
    """
    DROP TABLE idempotency;
    CREATE TABLE idempotency (
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL,
        key TEXT NOT NULL,
        operation TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        result TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (account_id, user_id, key)
    );
    CREATE INDEX idempotency_created ON idempotency (created_at);
    """,
    # 9: passwords, and user names that are unique regardless of case, the
    # name being what a person signs in with. A name taken twice before
    # gets part of its id, so the index can be made
    """
    UPDATE users SET name = name || '-' || substr(id, 5, 8)
        WHERE rowid NOT IN (SELECT MIN(rowid) FROM users GROUP BY lower(name));
    CREATE UNIQUE INDEX users_name ON users (name COLLATE NOCASE);
    CREATE TABLE passwords (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        hash TEXT NOT NULL,
        must_change INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );
    """,
    # 10: when a user last signed in to the UI
    """
    ALTER TABLE passwords ADD COLUMN last_sign_in_at TEXT;
    """,
    # 11: the last posts to each webhook, for its delivery log
    """
    CREATE TABLE webhook_attempts (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
        delivery_id TEXT NOT NULL,
        at TEXT NOT NULL,
        events INTEGER NOT NULL,
        status INTEGER,
        error TEXT
    );
    CREATE INDEX webhook_attempts_webhook ON webhook_attempts (webhook_id, seq);
    """,
    # 12: whether a user may sign in to the UI. Those with a password so
    # far keep it, those without are API users
    """
    ALTER TABLE users ADD COLUMN ui_sign_in INTEGER NOT NULL DEFAULT 0;
    UPDATE users SET ui_sign_in = 1 WHERE id IN (SELECT user_id FROM passwords);
    """,
    # 13: webhooks go with the user who made them. Those of users deleted
    # before were posted to by nobody's rights, and nobody could remove them
    """
    DELETE FROM webhooks WHERE user_id NOT IN (SELECT id FROM users);
    """,
]


SCHEMA_VERSION = len(MIGRATIONS)


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
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            # Freed pages are overwritten, so deleted secrets do not linger.
            self._connection.execute("PRAGMA secure_delete = ON")
        try:
            self._migrate()
        except BaseException:
            self._connection.close()
            raise

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

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """The first row, or None."""
        with self._lock, translated():
            row: sqlite3.Row | None = self._connection.execute(sql, params).fetchone()
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
        row = self.one("SELECT value FROM meta WHERE key = 'schema_version'")
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

    def _migrate(self) -> None:
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
            )
        current = self.schema_version()
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {current} is newer than this version supports "
                f"({SCHEMA_VERSION})"
            )
        for version in range(current, SCHEMA_VERSION):
            with self.transaction() as db:
                for statement in _statements(MIGRATIONS[version]):
                    db.execute(statement)
                db.execute(
                    "INSERT OR REPLACE INTO meta (key, value)"
                    " VALUES ('schema_version', ?)",
                    (str(version + 1),),
                )


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


def iso(value: datetime | None) -> str | None:
    """A time as the TEXT columns hold it."""
    return value.isoformat() if value else None


@overload
def parse_iso(value: str) -> datetime: ...
@overload
def parse_iso(value: None) -> None: ...
@overload
def parse_iso(value: str | None) -> datetime | None: ...
def parse_iso(value: str | None) -> datetime | None:
    """The time a TEXT column holds, None for NULL."""
    return datetime.fromisoformat(value) if value else None


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
        row = copy.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"not a database: {exc}") from None
    finally:
        copy.close()
    if row is None:
        raise ValueError("not a database of this service")
    return int(row[0])


def _statements(script: str) -> list[str]:
    return [part.strip() for part in script.split(";") if part.strip()]
