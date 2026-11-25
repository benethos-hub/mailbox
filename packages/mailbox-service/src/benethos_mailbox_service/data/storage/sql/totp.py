"""TOTP devices of users in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ....errors import missing
from ..totp import StoredTotpDevice
from ..webhooks import Sealed
from .rows import changed
from .schema import totp_devices

if TYPE_CHECKING:
    from .database import Database

_t = totp_devices.c


class SqlTotpRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def devices(self, user_id: str) -> list[StoredTotpDevice]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(totp_devices)
                .where(_t.user_id == user_id)
                .order_by(_t.created_at, _t.id)
            ).mappings()
            return [_device(row) for row in rows]

    def add(self, user_id: str, device: StoredTotpDevice) -> None:
        changed(
            self._db,
            sa.insert(totp_devices).values(
                id=device.id,
                user_id=user_id,
                name=device.name,
                key_id=device.secret.key_id,
                nonce=device.secret.nonce,
                ciphertext=device.secret.ciphertext,
                created_at=iso(device.created_at),
                last_step=device.last_step,
                last_used_at=iso(device.last_used_at),
            ),
        )

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        if not changed(
            self._db,
            sa.update(totp_devices)
            .where(_t.user_id == user_id, _t.id == device_id)
            .values(name=name),
        ):
            raise missing("device", device_id)

    def took(self, user_id: str, device_id: str, step: int, at: datetime) -> bool:
        # One statement compares and sets, so two requests with the same
        # code cannot both pass.
        return bool(
            changed(
                self._db,
                sa.update(totp_devices)
                .where(
                    _t.user_id == user_id,
                    _t.id == device_id,
                    sa.or_(_t.last_step.is_(None), _t.last_step < step),
                )
                .values(last_step=step, last_used_at=iso(at)),
            )
        )

    def remove(self, user_id: str, device_id: str) -> bool:
        return bool(
            changed(
                self._db,
                sa.delete(totp_devices).where(
                    _t.user_id == user_id, _t.id == device_id
                ),
            )
        )

    def remove_all(self, user_id: str) -> bool:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        return bool(
            changed(self._db, sa.delete(totp_devices).where(_t.user_id == user_id))
        )


def _device(row: sa.RowMapping) -> StoredTotpDevice:
    return StoredTotpDevice(
        id=row["id"],
        name=row["name"],
        secret=Sealed(row["key_id"], row["nonce"], row["ciphertext"]),
        created_at=parse_iso(row["created_at"]),
        last_step=row["last_step"],
        last_used_at=parse_iso(row["last_used_at"]),
    )
