"""Passkeys of users in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ....errors import ConflictError, missing
from ..passkeys import StoredPasskey
from .rows import changed
from .schema import passkeys

if TYPE_CHECKING:
    from .database import Database

_p = passkeys.c


class SqlPasskeyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def passkeys(self, user_id: str) -> list[StoredPasskey]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(passkeys)
                .where(_p.user_id == user_id)
                .order_by(_p.created_at, _p.id)
            ).mappings()
            return [_passkey(row) for row in rows]

    def add(self, user_id: str, passkey: StoredPasskey) -> None:
        try:
            changed(
                self._db,
                sa.insert(passkeys).values(
                    id=passkey.id,
                    user_id=user_id,
                    name=passkey.name,
                    credential_id=passkey.credential_id,
                    credential=passkey.credential,
                    sign_count=passkey.sign_count,
                    created_at=iso(passkey.created_at),
                    last_used_at=iso(passkey.last_used_at),
                ),
            )
        except ConflictError:
            raise ConflictError("this passkey is stored already") from None

    def rename(self, user_id: str, passkey_id: str, name: str) -> None:
        if not changed(
            self._db,
            sa.update(passkeys)
            .where(_p.user_id == user_id, _p.id == passkey_id)
            .values(name=name),
        ):
            raise missing("passkey", passkey_id)

    def used(
        self, user_id: str, passkey_id: str, sign_count: int, at: datetime
    ) -> bool:
        # One statement compares and sets, so two requests with the same
        # signature cannot both pass. The rule is storage.passkeys.counted.
        counted = _p.sign_count < sign_count
        if sign_count == 0:
            counted = sa.or_(counted, _p.sign_count == 0)
        return bool(
            changed(
                self._db,
                sa.update(passkeys)
                .where(_p.user_id == user_id, _p.id == passkey_id, counted)
                .values(sign_count=sign_count, last_used_at=iso(at)),
            )
        )

    def remove(self, user_id: str, passkey_id: str) -> bool:
        return bool(
            changed(
                self._db,
                sa.delete(passkeys).where(_p.user_id == user_id, _p.id == passkey_id),
            )
        )

    def remove_all(self, user_id: str) -> bool:
        # ON DELETE CASCADE does this with the user. Said here, so both
        # stores agree.
        return bool(changed(self._db, sa.delete(passkeys).where(_p.user_id == user_id)))


def _passkey(row: sa.RowMapping) -> StoredPasskey:
    return StoredPasskey(
        id=row["id"],
        name=row["name"],
        credential_id=row["credential_id"],
        credential=row["credential"],
        created_at=parse_iso(row["created_at"]),
        sign_count=row["sign_count"],
        last_used_at=parse_iso(row["last_used_at"]),
    )
