"""TOTP devices of users in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ....common.clock import iso, parse_iso
from ..totp import StoredTotpDevice
from ..webhooks import Sealed
from .database import Database


class SqliteTotpRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def devices(self, user_id: str) -> list[StoredTotpDevice]:
        rows = self._db.query(
            "SELECT * FROM totp_devices WHERE user_id = ? ORDER BY created_at, id",
            (user_id,),
        )
        return [_device(row) for row in rows]

    def add(self, user_id: str, device: StoredTotpDevice) -> None:
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

    def remove_all(self, user_id: str) -> bool:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        return bool(
            self._db.execute("DELETE FROM totp_devices WHERE user_id = ?", (user_id,))
        )


def _device(row: sqlite3.Row) -> StoredTotpDevice:
    return StoredTotpDevice(
        id=row["id"],
        name=row["name"],
        secret=Sealed(row["key_id"], row["nonce"], row["ciphertext"]),
        created_at=parse_iso(row["created_at"]),
        last_step=row["last_step"],
        last_used_at=parse_iso(row["last_used_at"]),
    )
