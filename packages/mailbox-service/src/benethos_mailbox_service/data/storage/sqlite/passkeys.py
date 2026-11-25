"""Passkeys of users in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from ....common.clock import iso, parse_iso
from ....errors import ConflictError
from ..passkeys import StoredPasskey

if TYPE_CHECKING:
    from ..sql.database import Database


class SqlitePasskeyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def passkeys(self, user_id: str) -> list[StoredPasskey]:
        return self._db.query_as(
            _passkey,
            "SELECT * FROM passkeys WHERE user_id = ? ORDER BY created_at, id",
            (user_id,),
        )

    def add(self, user_id: str, passkey: StoredPasskey) -> None:
        try:
            self._db.execute(
                "INSERT INTO passkeys (id, user_id, name, credential_id,"
                " credential, sign_count, created_at, last_used_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    passkey.id,
                    user_id,
                    passkey.name,
                    passkey.credential_id,
                    passkey.credential,
                    passkey.sign_count,
                    iso(passkey.created_at),
                    iso(passkey.last_used_at),
                ),
            )
        except ConflictError:
            raise ConflictError("this passkey is stored already") from None

    def rename(self, user_id: str, passkey_id: str, name: str) -> None:
        self._db.must_change(
            "UPDATE passkeys SET name = ? WHERE user_id = ? AND id = ?",
            (name, user_id, passkey_id),
            "passkey",
            passkey_id,
        )

    def used(
        self, user_id: str, passkey_id: str, sign_count: int, at: datetime
    ) -> bool:
        # One statement compares and sets, so two requests with the same
        # signature cannot both pass. The rule is storage.passkeys.counted.
        return bool(
            self._db.execute(
                "UPDATE passkeys SET sign_count = ?, last_used_at = ?"
                " WHERE user_id = ? AND id = ?"
                " AND (sign_count < ? OR (sign_count = 0 AND ? = 0))",
                (sign_count, iso(at), user_id, passkey_id, sign_count, sign_count),
            )
        )

    def remove(self, user_id: str, passkey_id: str) -> bool:
        return bool(
            self._db.execute(
                "DELETE FROM passkeys WHERE user_id = ? AND id = ?",
                (user_id, passkey_id),
            )
        )

    def remove_all(self, user_id: str) -> bool:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        return bool(
            self._db.execute("DELETE FROM passkeys WHERE user_id = ?", (user_id,))
        )


def _passkey(row: sqlite3.Row) -> StoredPasskey:
    return StoredPasskey(
        id=row["id"],
        name=row["name"],
        credential_id=row["credential_id"],
        credential=row["credential"],
        created_at=parse_iso(row["created_at"]),
        sign_count=row["sign_count"],
        last_used_at=parse_iso(row["last_used_at"]),
    )
