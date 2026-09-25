"""Results of requests with an Idempotency-Key in SQLite."""

from __future__ import annotations

from datetime import datetime

from ..idempotency import StoredResult
from .database import Database


class SqliteIdempotencyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, account_id: str, key: str) -> StoredResult | None:
        row = self._db.one(
            "SELECT * FROM idempotency WHERE account_id = ? AND key = ?",
            (account_id, key),
        )
        if row is None:
            return None
        return StoredResult(
            operation=row["operation"],
            request_hash=row["request_hash"],
            result=row["result"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def put(self, account_id: str, key: str, stored: StoredResult) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO idempotency (account_id, key, operation,"
            " request_hash, result, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                account_id,
                key,
                stored.operation,
                stored.request_hash,
                stored.result,
                stored.created_at.isoformat(),
            ),
        )

    def purge(self, before: datetime) -> None:
        self._db.execute(
            "DELETE FROM idempotency WHERE created_at < ?", (before.isoformat(),)
        )

    def forget_account(self, account_id: str) -> None:
        # ON DELETE CASCADE does this as well. Said here, so both stores agree.
        self._db.execute("DELETE FROM idempotency WHERE account_id = ?", (account_id,))
