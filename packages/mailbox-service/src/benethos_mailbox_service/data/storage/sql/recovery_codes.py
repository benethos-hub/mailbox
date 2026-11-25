"""Recovery codes of users' second factors in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso
from .rows import changed
from .schema import recovery_codes

if TYPE_CHECKING:
    from .database import Database

_r = recovery_codes.c


class SqlRecoveryCodeRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def replace(self, user_id: str, key_id: str, codes: list[str]) -> None:
        with self._db.connected() as conn:
            conn.execute(sa.delete(recovery_codes).where(_r.user_id == user_id))
            if codes:
                conn.execute(
                    sa.insert(recovery_codes),
                    [
                        {"user_id": user_id, "key_id": key_id, "hash": code}
                        for code in codes
                    ],
                )

    def use(self, user_id: str, key_id: str, code: str, at: datetime) -> bool:
        return bool(
            changed(
                self._db,
                sa.update(recovery_codes)
                .where(
                    _r.user_id == user_id,
                    _r.key_id == key_id,
                    _r.hash == code,
                    _r.used_at.is_(None),
                )
                .values(used_at=iso(at)),
            )
        )

    def left(self, user_id: str) -> int:
        with self._db.connected() as conn:
            counted: int = conn.execute(
                sa.select(sa.func.count())
                .select_from(recovery_codes)
                .where(_r.user_id == user_id, _r.used_at.is_(None))
            ).scalar_one()
            return counted

    def delete(self, user_id: str) -> None:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        changed(self._db, sa.delete(recovery_codes).where(_r.user_id == user_id))
