"""Second factors of users in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ....common.clock import iso, parse_iso
from ..factors import StoredDevice
from ..webhooks import Sealed
from .database import Database


class SqliteSecondFactorRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def devices(self, user_id: str) -> list[StoredDevice]:
        rows = self._db.query(
            "SELECT * FROM totp_devices WHERE user_id = ? ORDER BY created_at, id",
            (user_id,),
        )
        return [_device(row) for row in rows]

    def add(self, user_id: str, device: StoredDevice) -> None:
        self._db.execute(
            "INSERT INTO totp_devices (id, user_id, name, key_id, nonce,"
            " ciphertext, created_at, last_step, last_used_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                device.id,
                user_id,
                device.name,
                device.secret.key_id,
                device.secret.nonce,
                device.secret.ciphertext,
                iso(device.created_at),
                device.last_step,
                iso(device.last_used_at),
            ),
        )

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        self._db.must_change(
            "UPDATE totp_devices SET name = ? WHERE user_id = ? AND id = ?",
            (name, user_id, device_id),
            "device",
            device_id,
        )

    def took(self, user_id: str, device_id: str, step: int, at: datetime) -> bool:
        # One statement compares and sets, so two requests with the same
        # code cannot both pass.
        return bool(
            self._db.execute(
                "UPDATE totp_devices SET last_step = ?, last_used_at = ?"
                " WHERE user_id = ? AND id = ?"
                " AND (last_step IS NULL OR last_step < ?)",
                (step, iso(at), user_id, device_id, step),
            )
        )

    def remove(self, user_id: str, device_id: str) -> bool:
        return bool(
            self._db.execute(
                "DELETE FROM totp_devices WHERE user_id = ? AND id = ?",
                (user_id, device_id),
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
            removed = db.execute(
                "DELETE FROM totp_devices WHERE user_id = ?", (user_id,)
            ).rowcount
        return bool(removed)


def _device(row: sqlite3.Row) -> StoredDevice:
    return StoredDevice(
        id=row["id"],
        name=row["name"],
        secret=Sealed(row["key_id"], row["nonce"], row["ciphertext"]),
        created_at=parse_iso(row["created_at"]),
        last_step=row["last_step"],
        last_used_at=parse_iso(row["last_used_at"]),
    )
