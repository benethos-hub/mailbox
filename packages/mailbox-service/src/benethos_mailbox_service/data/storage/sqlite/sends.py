"""The audit of sends in SQLite."""

from __future__ import annotations

import builtins
import json
import sqlite3
from datetime import datetime

from ...models import SendFilter, SendOutcome, SendRecord
from .database import Database, iso, parse_iso


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
                iso(record.created_at),
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
        self, user_id: str, account_id: str, since: datetime, *, outcome: SendOutcome
    ) -> list[datetime]:
        rows = self._db.query(
            "SELECT created_at FROM sends WHERE user_id = ? AND account_id = ?"
            " AND outcome = ? AND created_at > ? ORDER BY created_at",
            (user_id, account_id, outcome, iso(since)),
        )
        return [parse_iso(row["created_at"]) for row in rows]

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: tuple[datetime, str] | None,
        matching: SendFilter | None = None,
    ) -> list[SendRecord]:
        where = ["account_id = ?"]
        params: list[object] = [account_id]
        if before is not None:
            where.append("(created_at, id) < (?, ?)")
            params += [iso(before[0]), before[1]]
        if matching is not None:
            for column, value in (
                ("user_id = ?", matching.user_id),
                ("outcome = ?", matching.outcome),
                ("created_at >= ?", iso(matching.after)),
                ("created_at < ?", iso(matching.before)),
            ):
                if value is not None:
                    where.append(column)
                    params.append(value)
            if matching.recipient:
                # In the JSON of the recipients a LIKE would also match
                # quotes and commas: the part is looked for in each address.
                where.append(
                    "EXISTS (SELECT 1 FROM json_each(recipients)"
                    " WHERE instr(casefold(value), ?) > 0)"
                )
                params.append(matching.recipient.casefold())
        rows = self._db.query(
            f"SELECT * FROM sends WHERE {' AND '.join(where)}"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit),
        )
        return [_record(row) for row in rows]

    def account_ids(self) -> builtins.list[str]:
        rows = self._db.query("SELECT DISTINCT account_id FROM sends ORDER BY 1")
        return [row[0] for row in rows]


def _record(row: sqlite3.Row) -> SendRecord:
    return SendRecord(
        id=row["id"],
        created_at=parse_iso(row["created_at"]),
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
