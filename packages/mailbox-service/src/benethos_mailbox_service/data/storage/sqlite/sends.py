"""The audit of sends in SQLite."""

from __future__ import annotations

import builtins
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from ....common.clock import iso, parse_iso
from ...models import Before, SendFilter, SendOutcome, SendRecord
from .database import Database


class SqliteSendLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, record: SendRecord) -> None:
        self._db.execute(
            "INSERT INTO sends (id, created_at, user_id, credential_id,"
            " account_id, operation, recipients, outcome, error, refused,"
            " message_id_header, outbox_job_id, recipients_folded)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                record.outbox_job_id,
                folded(record.recipients),
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
        before: Before | None,
        matching: SendFilter | None = None,
    ) -> list[SendRecord]:
        where = ["account_id = ?"]
        params: list[object] = [account_id]
        if before is not None:
            where.append("(created_at, id) < (?, ?)")
            params += [iso(before.at), before.id]
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
                # One address per line: a part with a line break would
                # reach across two, and no address holds one.
                where.append("recipients_folded LIKE ? ESCAPE '\\'")
                params.append(_within(matching.recipient.casefold()))
        return self._db.query_as(
            _send,
            f"SELECT * FROM sends WHERE {' AND '.join(where)}"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit),
        )

    def account_ids(self) -> builtins.list[str]:
        rows = self._db.query("SELECT DISTINCT account_id FROM sends ORDER BY 1")
        return [row[0] for row in rows]

    def purge(self, before: datetime) -> int:
        return self._db.purge("sends", "created_at", before)


def folded(recipients: Iterable[str]) -> str:
    """The addresses as the search finds them: each folded by
    ``str.casefold()``, one per line."""
    return "\n".join(address.casefold() for address in recipients)


def _within(part: str) -> str:
    """The pattern of LIKE that finds ``part`` as it is, inside one line.
    A part with a line break gets one that finds nothing."""
    if "\n" in part:
        return ""
    for special in ("\\", "%", "_"):
        part = part.replace(special, "\\" + special)
    return f"%{part}%"


def _send(row: sqlite3.Row) -> SendRecord:
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
        outbox_job_id=row["outbox_job_id"],
    )
