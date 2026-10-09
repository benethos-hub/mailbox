"""Recovery codes of users' second factors in SQLite."""

from __future__ import annotations

from datetime import datetime

from ....common.clock import iso
from .database import Database


class SqliteRecoveryCodeRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def replace(self, user_id: str, codes: list[str]) -> None:
        with self._db.transaction() as db:
            db.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
            db.executemany(
                "INSERT INTO recovery_codes (user_id, hash) VALUES (?, ?)",
                [(user_id, code) for code in codes],
            )

    def use(self, user_id: str, code: str, at: datetime) -> bool:
        return bool(
            self._db.execute(
                "UPDATE recovery_codes SET used_at = ?"
                " WHERE user_id = ? AND hash = ? AND used_at IS NULL",
                (iso(at), user_id, code),
            )
        )

    def left(self, user_id: str) -> int:
        row = self._db.one(
            "SELECT count(*) AS left FROM recovery_codes"
            " WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        return int(row["left"]) if row is not None else 0

    def delete(self, user_id: str) -> None:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        self._db.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
