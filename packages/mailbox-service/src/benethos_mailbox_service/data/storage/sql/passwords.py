"""Password hashes of users in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ..passwords import StoredPassword
from .dialect import insert_or_update
from .rows import changed
from .schema import passwords

if TYPE_CHECKING:
    from .database import Database


class SqlPasswordRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, user_id: str) -> StoredPassword | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(sa.select(passwords).where(passwords.c.user_id == user_id))
                .mappings()
                .first()
            )
        if row is None:
            return None
        return StoredPassword(
            hash=row["hash"],
            must_change=bool(row["must_change"]),
            updated_at=parse_iso(row["updated_at"]),
            last_sign_in_at=parse_iso(row["last_sign_in_at"]),
        )

    def set(self, user_id: str, stored: StoredPassword) -> None:
        with self._db.connected() as conn:
            conn.execute(
                insert_or_update(passwords, ["user_id"], None, conn.dialect).values(
                    user_id=user_id,
                    hash=stored.hash,
                    must_change=int(stored.must_change),
                    updated_at=iso(stored.updated_at),
                    last_sign_in_at=iso(stored.last_sign_in_at),
                )
            )

    def signed_in(self, user_id: str, at: datetime) -> None:
        changed(
            self._db,
            sa.update(passwords)
            .where(passwords.c.user_id == user_id)
            .values(last_sign_in_at=iso(at)),
        )

    def delete(self, user_id: str) -> None:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        changed(self._db, sa.delete(passwords).where(passwords.c.user_id == user_id))
