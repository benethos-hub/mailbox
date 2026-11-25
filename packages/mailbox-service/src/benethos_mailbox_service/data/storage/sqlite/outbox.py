"""The jobs of the outbox in SQLite."""

from __future__ import annotations

import builtins
import json
import sqlite3
from datetime import datetime

from ....common.clock import iso, parse_iso
from ....errors import missing
from ...models import OPEN_STATES, Before, OutboxJob, OutboxState
from .database import Database

_COLUMNS = (
    "id, account_id, user_id, credential_id, operation, draft_id, digest,"
    " message_id_header, recipients, state, attempts, due_at, expires_at,"
    " send_at, last_error, unclear_since, created_at, finished_at"
)
_OPEN = ", ".join(f"'{state}'" for state in OPEN_STATES)


class SqliteOutboxRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, job: OutboxJob) -> None:
        self._db.execute(
            f"INSERT INTO outbox ({_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _values(job),
        )

    def get(self, job_id: str) -> OutboxJob:
        found = self._db.one_as(_job, "SELECT * FROM outbox WHERE id = ?", (job_id,))
        if found is None:
            raise missing("outbox job", job_id)
        return found

    def update(self, job: OutboxJob, *, was: OutboxState) -> bool:
        values = _values(job)
        return bool(
            self._db.execute(
                "UPDATE outbox SET account_id = ?, user_id = ?, credential_id = ?,"
                " operation = ?, draft_id = ?, digest = ?, message_id_header = ?,"
                " recipients = ?, state = ?, attempts = ?, due_at = ?,"
                " expires_at = ?, send_at = ?, last_error = ?, unclear_since = ?,"
                " created_at = ?, finished_at = ? WHERE id = ? AND state = ?",
                (*values[1:], job.id, was),
            )
        )

    def open(self) -> builtins.list[OutboxJob]:
        return self._db.query_as(
            _job,
            f"SELECT * FROM outbox WHERE state IN ({_OPEN})"
            " ORDER BY due_at, created_at, id",
        )

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        user_id: str | None = None,
        state: OutboxState | None = None,
    ) -> builtins.list[OutboxJob]:
        where = ["account_id = ?"]
        params: list[object] = [account_id]
        if before is not None:
            where.append("(created_at, id) < (?, ?)")
            params += [iso(before.at), before.id]
        for column, value in (("user_id = ?", user_id), ("state = ?", state)):
            if value is not None:
                where.append(column)
                params.append(value)
        return self._db.query_as(
            _job,
            f"SELECT * FROM outbox WHERE {' AND '.join(where)}"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit),
        )

    def purge(self, before: datetime) -> int:
        removed = self._db.execute(
            f"DELETE FROM outbox WHERE state NOT IN ({_OPEN})"
            " AND finished_at IS NOT NULL AND finished_at < ?",
            (iso(before),),
        )
        if removed:
            self._db.shrink()
        return removed


def _values(job: OutboxJob) -> tuple[object, ...]:
    return (
        job.id,
        job.account_id,
        job.user_id,
        job.credential_id,
        job.operation,
        job.draft_id,
        job.digest,
        job.message_id_header,
        json.dumps(job.recipients),
        job.state,
        job.attempts,
        iso(job.due_at),
        iso(job.expires_at),
        iso(job.send_at),
        job.last_error,
        iso(job.unclear_since),
        iso(job.created_at),
        iso(job.finished_at),
    )


def _job(row: sqlite3.Row) -> OutboxJob:
    return OutboxJob(
        id=row["id"],
        account_id=row["account_id"],
        user_id=row["user_id"],
        credential_id=row["credential_id"],
        operation=row["operation"],
        draft_id=row["draft_id"],
        digest=row["digest"],
        message_id_header=row["message_id_header"],
        recipients=json.loads(row["recipients"]),
        state=row["state"],
        attempts=row["attempts"],
        due_at=parse_iso(row["due_at"]),
        expires_at=parse_iso(row["expires_at"]),
        send_at=parse_iso(row["send_at"]),
        last_error=row["last_error"],
        unclear_since=parse_iso(row["unclear_since"]),
        created_at=parse_iso(row["created_at"]),
        finished_at=parse_iso(row["finished_at"]),
    )
