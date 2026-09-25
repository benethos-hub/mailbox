"""The wrapped data key and encrypted credentials in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..credentials import EncryptedCredential, WrappedKey
from .database import Database


class SqliteKeyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def active(self) -> WrappedKey | None:
        row = self._db.one("SELECT * FROM keys ORDER BY rowid DESC LIMIT 1")
        if row is None:
            return None
        return WrappedKey(row["key_id"], bytes(row["nonce"]), bytes(row["ciphertext"]))

    def add(self, key: WrappedKey) -> None:
        self._db.execute(
            "INSERT INTO keys (key_id, nonce, ciphertext) VALUES (?, ?, ?)",
            (key.key_id, key.nonce, key.ciphertext),
        )


class SqliteCredentialRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def put(self, credential: EncryptedCredential) -> None:
        self._db.execute(
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
        row = self._db.one(
            "SELECT * FROM credentials WHERE account_id = ? AND field = ?",
            (account_id, field),
        )
        return _credential(row) if row is not None else None

    def list_for_account(self, account_id: str) -> list[EncryptedCredential]:
        rows = self._db.query(
            "SELECT * FROM credentials WHERE account_id = ? ORDER BY field",
            (account_id,),
        )
        return [_credential(r) for r in rows]

    def delete_for_account(self, account_id: str) -> None:
        self._db.execute("DELETE FROM credentials WHERE account_id = ?", (account_id,))


def _credential(row: sqlite3.Row) -> EncryptedCredential:
    return EncryptedCredential(
        account_id=row["account_id"],
        field=row["field"],
        key_id=row["key_id"],
        nonce=bytes(row["nonce"]),
        ciphertext=bytes(row["ciphertext"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
