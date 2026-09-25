"""The audit of sends in SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ...models import SendRecord
from .database import Database


class SqliteSendLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, record: SendRecord) -> None:
        self._db.execute(
            "INSERT INTO sends (id, created_at, user_id, credential_id,"
            " account_id, operation, recipients, outcome, error, refused,"
            " message_id_header) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.created_at.isoformat(),
                record.user_id,
                record.credential_id,
                record.account_id,
                record.operation,
                json.dumps(record.recipients),
                record.outcome,
                record.error,
                json.dumps(record.refused),
                record.message_id_header,
            ),
        )

    def sent_since(
        self, user_id: str, account_id: str, since: datetime
    ) -> list[datetime]:
        rows = self._db.query(
            "SELECT created_at FROM sends WHERE user_id = ? AND account_id = ?"
            " AND outcome = 'sent' AND created_at > ? ORDER BY created_at",
            (user_id, account_id, since.isoformat()),
        )
        return [datetime.fromisoformat(row["created_at"]) for row in rows]

    def list(
        self, account_id: str, *, limit: int, before: tuple[datetime, str] | None
    ) -> list[SendRecord]:
        if before is None:
            rows = self._db.query(
                "SELECT * FROM sends WHERE account_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (account_id, limit),
            )
        else:
            rows = self._db.query(
                "SELECT * FROM sends WHERE account_id = ?"
                " AND (created_at, id) < (?, ?)"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (account_id, before[0].isoformat(), before[1], limit),
            )
        return [_record(row) for row in rows]


def _record(row: sqlite3.Row) -> SendRecord:
    return SendRecord(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        user_id=row["user_id"],
        credential_id=row["credential_id"],
        account_id=row["account_id"],
        operation=row["operation"],
        recipients=json.loads(row["recipients"]),
        outcome=row["outcome"],
        error=row["error"],
        refused=json.loads(row["refused"]),
        message_id_header=row["message_id_header"],
    )
