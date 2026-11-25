"""Results of requests with an Idempotency-Key in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ..idempotency import StoredResult
from .dialect import insert_or_update
from .rows import changed
from .schema import idempotency

if TYPE_CHECKING:
    from .database import Database

_i = idempotency.c
_KEY = ["account_id", "user_id", "key"]


class SqlIdempotencyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, account_id: str, user_id: str, key: str) -> StoredResult | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(
                    sa.select(idempotency).where(
                        _i.account_id == account_id,
                        _i.user_id == user_id,
                        _i.key == key,
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return StoredResult(
            operation=row["operation"],
            request_hash=row["request_hash"],
            result=row["result"],
            created_at=parse_iso(row["created_at"]),
        )

    def put(
        self, account_id: str, user_id: str, key: str, stored: StoredResult
    ) -> None:
        # A result stored again under the same key replaces the one before.
        with self._db.connected() as conn:
            conn.execute(
                insert_or_update(idempotency, _KEY, None, conn.dialect).values(
                    account_id=account_id,
                    user_id=user_id,
                    key=key,
                    operation=stored.operation,
                    request_hash=stored.request_hash,
                    result=stored.result,
                    created_at=iso(stored.created_at),
                )
            )

    def purge(self, before: datetime) -> None:
        self._db.purge("idempotency", "created_at", before)

    def forget_account(self, account_id: str) -> None:
        # ON DELETE CASCADE does this as well. Said here, so both stores agree.
        changed(self._db, sa.delete(idempotency).where(_i.account_id == account_id))
