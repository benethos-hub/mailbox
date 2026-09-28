"""Password hashes of users in SQLite."""

from __future__ import annotations

from datetime import datetime

from ....common.clock import iso, parse_iso
from ..passwords import StoredPassword
from .database import Database


class SqlitePasswordRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, user_id: str) -> StoredPassword | None:
        row = self._db.one("SELECT * FROM passwords WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        return StoredPassword(
            hash=row["hash"],
            must_change=bool(row["must_change"]),
            updated_at=parse_iso(row["updated_at"]),
            last_sign_in_at=parse_iso(row["last_sign_in_at"]),
        )

    def set(self, user_id: str, stored: StoredPassword) -> None:
        self._db.execute(
            "INSERT INTO passwords"
            " (user_id, hash, must_change, updated_at, last_sign_in_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET hash = excluded.hash,"
            " must_change = excluded.must_change, updated_at = excluded.updated_at,"
            " last_sign_in_at = excluded.last_sign_in_at",
            (
                user_id,
                stored.hash,
                int(stored.must_change),
                iso(stored.updated_at),
                iso(stored.last_sign_in_at),
            ),
        )

    def signed_in(self, user_id: str, at: datetime) -> None:
        self._db.execute(
            "UPDATE passwords SET last_sign_in_at = ? WHERE user_id = ?",
            (iso(at), user_id),
        )

    def delete(self, user_id: str) -> None:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        self._db.execute("DELETE FROM passwords WHERE user_id = ?", (user_id,))
