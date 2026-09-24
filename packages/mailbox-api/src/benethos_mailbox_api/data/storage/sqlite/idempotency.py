"""Results of requests with an Idempotency-Key in SQLite."""

from __future__ import annotations

from datetime import datetime

from ..idempotency import StoredResult
from .database import Database


class SqliteIdempotencyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, account_id: str, key: str) -> StoredResult | None:
        rows = self._db.query(
            "SELECT * FROM idempotency WHERE account_id = ? AND key = ?",
            (account_id, key),
        )
        if not rows:
            return None
        row = rows[0]
        return StoredResult(
            operation=row["operation"],
            request_hash=row["request_hash"],
            result=row["result"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def put(self, account_id: str, key: str, stored: StoredResult) -> None:
        with self._db.transaction() as db:
            db.execute(
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
        with self._db.transaction() as db:
            db.execute(
                "DELETE FROM idempotency WHERE created_at < ?", (before.isoformat(),)
            )
