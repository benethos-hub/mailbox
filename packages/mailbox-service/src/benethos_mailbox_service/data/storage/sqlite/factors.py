"""Second factors of users in SQLite."""

from __future__ import annotations

from datetime import datetime

from ....common.clock import iso, parse_iso
from ..factors import StoredFactor
from ..webhooks import Sealed
from .database import Database


class SqliteSecondFactorRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, user_id: str) -> StoredFactor | None:
        row = self._db.one("SELECT * FROM totp WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        return StoredFactor(
            secret=Sealed(row["key_id"], row["nonce"], row["ciphertext"]),
            confirmed_at=parse_iso(row["confirmed_at"]),
            last_step=row["last_step"],
        )

    def set(self, user_id: str, factor: StoredFactor, codes: list[str]) -> None:
        with self._db.transaction() as db:
            db.execute(
                "INSERT INTO totp"
                " (user_id, key_id, nonce, ciphertext, confirmed_at, last_step)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET key_id = excluded.key_id,"
                " nonce = excluded.nonce, ciphertext = excluded.ciphertext,"
                " confirmed_at = excluded.confirmed_at,"
                " last_step = excluded.last_step",
                (
                    user_id,
                    factor.secret.key_id,
                    factor.secret.nonce,
                    factor.secret.ciphertext,
                    iso(factor.confirmed_at),
                    factor.last_step,
                ),
            )
            self.replace_codes(user_id, codes)

    def took(self, user_id: str, step: int) -> bool:
        # One statement compares and sets, so two requests with the same
        # code cannot both pass.
        return bool(
            self._db.execute(
                "UPDATE totp SET last_step = ?"
                " WHERE user_id = ? AND (last_step IS NULL OR last_step < ?)",
                (step, user_id, step),
            )
        )

    def replace_codes(self, user_id: str, codes: list[str]) -> None:
        with self._db.transaction() as db:
            db.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
            db.executemany(
                "INSERT INTO recovery_codes (user_id, hash) VALUES (?, ?)",
                [(user_id, code) for code in codes],
            )

    def use_code(self, user_id: str, code: str, at: datetime) -> bool:
        return bool(
            self._db.execute(
                "UPDATE recovery_codes SET used_at = ?"
                " WHERE user_id = ? AND hash = ? AND used_at IS NULL",
                (iso(at), user_id, code),
            )
        )

    def codes_left(self, user_id: str) -> int:
        row = self._db.one(
            "SELECT count(*) AS left FROM recovery_codes"
            " WHERE user_id = ? AND used_at IS NULL",
            (user_id,),
        )
        return int(row["left"]) if row is not None else 0

    def delete(self, user_id: str) -> bool:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        with self._db.transaction() as db:
            db.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
            return bool(
                db.execute("DELETE FROM totp WHERE user_id = ?", (user_id,)).rowcount
            )
