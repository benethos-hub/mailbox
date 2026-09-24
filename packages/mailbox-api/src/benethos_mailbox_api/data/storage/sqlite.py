"""SQLite persistence. The only module that imports ``sqlite3``.

One connection per process, guarded by a lock, since every call is short.
The schema is versioned in ``meta`` and migrated forward on open.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from ...errors import NotFoundError
from ..models import Account, AccountStatus, ApiToken, Grant, Role, User
from .credentials import EncryptedCredential, WrappedKey
from .index import IndexChanges, IndexEntry

SettingsDict = dict[str, str | int | bool]

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
]

SCHEMA_VERSION = len(MIGRATIONS)


class Database:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
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
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            self._connection.execute("COMMIT")

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(sql, params).fetchall()

    def schema_version(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def snapshot(self) -> bytes:
        """A consistent copy of the whole database, taken while it is in use."""
        with self._lock:
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


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SqliteAccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[Account]:
        return [
            _account(r) for r in self._db.query("SELECT * FROM accounts ORDER BY rowid")
        ]

    def get(self, account_id: str) -> Account:
        rows = self._db.query("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not rows:
            raise NotFoundError(f"account {account_id} not found")
        return _account(rows[0])

    def add(self, account: Account, settings: SettingsDict | None = None) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO accounts"
                " (id, provider, email, display_name, status, settings)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    account.id,
                    account.provider.value,
                    account.email,
                    account.display_name,
                    account.status.value,
                    json.dumps(settings or {}),
                ),
            )

    def settings(self, account_id: str) -> SettingsDict:
        rows = self._db.query(
            "SELECT settings FROM accounts WHERE id = ?", (account_id,)
        )
        if not rows:
            raise NotFoundError(f"account {account_id} not found")
        result: SettingsDict = json.loads(rows[0]["settings"])
        return result

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        with self._db.transaction() as db:
            updated = db.execute(
                "UPDATE accounts SET status = ? WHERE id = ?",
                (status.value, account_id),
            ).rowcount
            if updated == 0:
                raise NotFoundError(f"account {account_id} not found")

    def delete(self, account_id: str) -> None:
        with self._db.transaction() as db:
            if (
                db.execute("DELETE FROM accounts WHERE id = ?", (account_id,)).rowcount
                == 0
            ):
                raise NotFoundError(f"account {account_id} not found")


def _account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        provider=row["provider"],
        email=row["email"],
        display_name=row["display_name"],
        status=row["status"],
    )


class SqliteUserRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[User]:
        return [_user(r) for r in self._db.query("SELECT * FROM users ORDER BY rowid")]

    def get(self, user_id: str) -> User:
        rows = self._db.query("SELECT * FROM users WHERE id = ?", (user_id,))
        if not rows:
            raise NotFoundError(f"user {user_id} not found")
        return _user(rows[0])

    def save(self, user: User) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO users (id, name, roles, grants, disabled)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
                " roles = excluded.roles, grants = excluded.grants,"
                " disabled = excluded.disabled",
                (
                    user.id,
                    user.name,
                    json.dumps(user.roles),
                    _grants_json(user.grants),
                    int(user.disabled),
                ),
            )

    def delete(self, user_id: str) -> None:
        with self._db.transaction() as db:
            if db.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount == 0:
                raise NotFoundError(f"user {user_id} not found")

    def count(self) -> int:
        return int(self._db.query("SELECT COUNT(*) FROM users")[0][0])


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        roles=json.loads(row["roles"]),
        grants=_grants(row["grants"]),
        disabled=bool(row["disabled"]),
    )


class SqliteRoleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[Role]:
        return [_role(r) for r in self._db.query("SELECT * FROM roles ORDER BY rowid")]

    def get(self, role_id: str) -> Role:
        rows = self._db.query("SELECT * FROM roles WHERE id = ?", (role_id,))
        if not rows:
            raise NotFoundError(f"role {role_id} not found")
        return _role(rows[0])

    def save(self, role: Role) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO roles (id, grants) VALUES (?, ?)"
                " ON CONFLICT(id) DO UPDATE SET grants = excluded.grants",
                (role.id, _grants_json(role.grants)),
            )

    def delete(self, role_id: str) -> None:
        with self._db.transaction() as db:
            if db.execute("DELETE FROM roles WHERE id = ?", (role_id,)).rowcount == 0:
                raise NotFoundError(f"role {role_id} not found")


def _role(row: sqlite3.Row) -> Role:
    return Role(id=row["id"], grants=_grants(row["grants"]))


class SqliteTokenRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        rows = self._db.query(
            "SELECT * FROM tokens WHERE user_id = ? ORDER BY rowid", (user_id,)
        )
        return [_token(r) for r in rows]

    def get(self, token_id: str) -> ApiToken:
        rows = self._db.query("SELECT * FROM tokens WHERE id = ?", (token_id,))
        if not rows:
            raise NotFoundError(f"token {token_id} not found")
        return _token(rows[0])

    def find_by_hash(self, token_hash: str) -> ApiToken | None:
        rows = self._db.query(
            "SELECT * FROM tokens WHERE token_hash = ?", (token_hash,)
        )
        return _token(rows[0]) if rows else None

    def save(self, token: ApiToken) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO tokens (id, user_id, name, token_hash, created_at,"
                " expires_at, last_used_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
                " expires_at = excluded.expires_at,"
                " last_used_at = excluded.last_used_at,"
                " revoked_at = excluded.revoked_at",
                (
                    token.id,
                    token.user_id,
                    token.name,
                    token.token_hash,
                    _dt(token.created_at),
                    _dt(token.expires_at),
                    _dt(token.last_used_at),
                    _dt(token.revoked_at),
                ),
            )

    def delete_for_user(self, user_id: str) -> None:
        with self._db.transaction() as db:
            db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))


def _token(row: sqlite3.Row) -> ApiToken:
    return ApiToken(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        token_hash=row["token_hash"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=_parse_dt(row["expires_at"]),
        last_used_at=_parse_dt(row["last_used_at"]),
        revoked_at=_parse_dt(row["revoked_at"]),
    )


def _grants_json(grants: list[Grant]) -> str:
    return json.dumps([g.model_dump() for g in grants])


def _grants(raw: str) -> list[Grant]:
    return [Grant.model_validate(g) for g in json.loads(raw)]


class SqliteKeyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def active(self) -> WrappedKey | None:
        rows = self._db.query("SELECT * FROM keys ORDER BY rowid DESC LIMIT 1")
        if not rows:
            return None
        row = rows[0]
        return WrappedKey(row["key_id"], bytes(row["nonce"]), bytes(row["ciphertext"]))

    def add(self, key: WrappedKey) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO keys (key_id, nonce, ciphertext) VALUES (?, ?, ?)",
                (key.key_id, key.nonce, key.ciphertext),
            )


class SqliteCredentialRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def put(self, credential: EncryptedCredential) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO credentials"
                " (account_id, field, key_id, nonce, ciphertext, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(account_id, field) DO UPDATE SET"
                " key_id = excluded.key_id, nonce = excluded.nonce,"
                " ciphertext = excluded.ciphertext, updated_at = excluded.updated_at",
                (
                    credential.account_id,
                    credential.field,
                    credential.key_id,
                    credential.nonce,
                    credential.ciphertext,
                    credential.updated_at.isoformat(),
                ),
            )

    def get(self, account_id: str, field: str) -> EncryptedCredential | None:
        rows = self._db.query(
            "SELECT * FROM credentials WHERE account_id = ? AND field = ?",
            (account_id, field),
        )
        return _credential(rows[0]) if rows else None

    def list_for_account(self, account_id: str) -> list[EncryptedCredential]:
        rows = self._db.query(
            "SELECT * FROM credentials WHERE account_id = ? ORDER BY field",
            (account_id,),
        )
        return [_credential(r) for r in rows]

    def delete_for_account(self, account_id: str) -> None:
        with self._db.transaction() as db:
            db.execute("DELETE FROM credentials WHERE account_id = ?", (account_id,))


def _credential(row: sqlite3.Row) -> EncryptedCredential:
    return EncryptedCredential(
        account_id=row["account_id"],
        field=row["field"],
        key_id=row["key_id"],
        nonce=bytes(row["nonce"]),
        ciphertext=bytes(row["ciphertext"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# Stays below SQLite's limit of host parameters in one statement.
_CHUNK = 500


def _chunks(values: list[str]) -> Iterator[list[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


class SqliteMessageIndexRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, account_id: str, message_id: str) -> IndexEntry | None:
        rows = self._db.query(
            "SELECT * FROM message_index WHERE account_id = ? AND id = ?",
            (account_id, message_id),
        )
        return _entry(rows[0]) if rows else None

    def by_native(
        self, account_id: str, native_ids: Iterable[str]
    ) -> dict[str, IndexEntry]:
        found: dict[str, IndexEntry] = {}
        for chunk in _chunks(list(dict.fromkeys(native_ids))):
            marks = ", ".join("?" * len(chunk))
            for row in self._db.query(
                "SELECT * FROM message_index WHERE account_id = ?"
                f" AND native_id IN ({marks})",
                (account_id, *chunk),
            ):
                found[row["native_id"]] = _entry(row)
        return found

    def in_folders(
        self, account_id: str, folder_ids: Iterable[str]
    ) -> list[IndexEntry]:
        found: list[IndexEntry] = []
        for chunk in _chunks(list(dict.fromkeys(folder_ids))):
            marks = ", ".join("?" * len(chunk))
            found += [
                _entry(row)
                for row in self._db.query(
                    "SELECT * FROM message_index WHERE account_id = ?"
                    f" AND folder_id IN ({marks}) ORDER BY rowid",
                    (account_id, *chunk),
                )
            ]
        return found

    def add(self, account_id: str, entries: Iterable[IndexEntry]) -> None:
        with self._db.transaction() as db:
            _insert(db, account_id, entries)

    def apply(self, account_id: str, changes: IndexChanges) -> None:
        with self._db.transaction() as db:
            db.executemany(
                "DELETE FROM message_index WHERE account_id = ? AND id = ?",
                [(account_id, message_id) for message_id in changes.removed],
            )
            for entry in changes.updated:
                _update(db, account_id, entry)
            _insert(db, account_id, changes.added)
            db.execute("DELETE FROM folder_states WHERE account_id = ?", (account_id,))
            db.executemany(
                "INSERT INTO folder_states (account_id, folder_id, state)"
                " VALUES (?, ?, ?)",
                [(account_id, f, s) for f, s in changes.states.items()],
            )

    def relocate(self, account_id: str, entry: IndexEntry) -> None:
        with self._db.transaction() as db:
            _update(db, account_id, entry)

    def folder_states(self, account_id: str) -> dict[str, str]:
        rows = self._db.query(
            "SELECT folder_id, state FROM folder_states WHERE account_id = ?",
            (account_id,),
        )
        return {row["folder_id"]: row["state"] for row in rows}

    def forget_account(self, account_id: str) -> None:
        with self._db.transaction() as db:
            db.execute("DELETE FROM message_index WHERE account_id = ?", (account_id,))
            db.execute("DELETE FROM folder_states WHERE account_id = ?", (account_id,))


def _update(db: sqlite3.Connection, account_id: str, entry: IndexEntry) -> None:
    """The entry's new place; another entry holding that place gives it up."""
    db.execute(
        "DELETE FROM message_index WHERE account_id = ? AND native_id = ? AND id <> ?",
        (account_id, entry.native_id, entry.id),
    )
    db.execute(
        "UPDATE message_index SET native_id = ?, folder_id = ?, header = ?"
        " WHERE account_id = ? AND id = ?",
        (entry.native_id, entry.folder_id, entry.header, account_id, entry.id),
    )


def _insert(
    db: sqlite3.Connection, account_id: str, entries: Iterable[IndexEntry]
) -> None:
    db.executemany(
        "INSERT OR IGNORE INTO message_index"
        " (id, account_id, native_id, folder_id, header) VALUES (?, ?, ?, ?, ?)",
        [(e.id, account_id, e.native_id, e.folder_id, e.header) for e in entries],
    )


def _entry(row: sqlite3.Row) -> IndexEntry:
    return IndexEntry(
        id=row["id"],
        native_id=row["native_id"],
        folder_id=row["folder_id"],
        header=row["header"],
    )
