"""The jobs of the outbox in SQL."""

from __future__ import annotations

import builtins
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from benethos_mailbox_common.storage import rows as table_rows

from ....common.clock import iso, parse_iso
from ....errors import missing
from ...models import OPEN_STATES, Before, OutboxJob, OutboxState
from .schema import outbox

if TYPE_CHECKING:
    from .database import Database

_o = outbox.c


class SqlOutboxRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, job: OutboxJob) -> None:
        table_rows.rows_changed(
            self._db, sa.insert(outbox).values(id=job.id, **_values(job))
        )

    def get(self, job_id: str) -> OutboxJob:
        with self._db.connected() as conn:
            row = (
                conn.execute(sa.select(outbox).where(_o.id == job_id))
                .mappings()
                .first()
            )
        if row is None:
            raise missing("outbox job", job_id)
        return _job(row)

    def update(self, job: OutboxJob, *, was: OutboxState) -> bool:
        # Only while the job is still in the state ``was``: so a job is
        # never sent twice.
        return bool(
            table_rows.rows_changed(
                self._db,
                sa.update(outbox)
                .where(_o.id == job.id, _o.state == was)
                .values(**_values(job)),
            )
        )

    def open(self) -> builtins.list[OutboxJob]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(outbox)
                .where(_o.state.in_(OPEN_STATES))
                .order_by(_o.due_at, _o.created_at, _o.id)
            ).mappings()
            return [_job(row) for row in rows]

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        user_id: str | None = None,
        state: OutboxState | None = None,
    ) -> builtins.list[OutboxJob]:
        where: builtins.list[sa.ColumnElement[bool]] = [_o.account_id == account_id]
        if before is not None:
            where.append(
                sa.tuple_(_o.created_at, _o.id) < sa.tuple_(iso(before.at), before.id)
            )
        if user_id is not None:
            where.append(_o.user_id == user_id)
        if state is not None:
            where.append(_o.state == state)
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(outbox)
                .where(*where)
                .order_by(_o.created_at.desc(), _o.id.desc())
                .limit(limit)
            ).mappings()
            return [_job(row) for row in rows]

    def count(
        self, account_id: str, state: OutboxState, *, since: datetime | None = None
    ) -> int:
        where = [_o.account_id == account_id, _o.state == state]
        if since is not None:
            where.append(_o.finished_at >= iso(since))
        with self._db.connected() as conn:
            counted: int = conn.execute(
                sa.select(sa.func.count()).select_from(outbox).where(*where)
            ).scalar_one()
            return counted

    def purge(self, before: datetime) -> int:
        removed = table_rows.rows_changed(
            self._db,
            sa.delete(outbox).where(
                _o.state.not_in(OPEN_STATES),
                _o.finished_at.is_not(None),
                _o.finished_at < iso(before),
            ),
        )
        if removed:
            self._db.shrink()
        return removed


def _values(job: OutboxJob) -> dict[str, Any]:
    """Every column but the key."""
    return {
        "account_id": job.account_id,
        "user_id": job.user_id,
        "credential_id": job.credential_id,
        "operation": job.operation,
        "draft_id": job.draft_id,
        "digest": job.digest,
        "message_id_header": job.message_id_header,
        "recipients": json.dumps(job.recipients),
        "state": job.state,
        "attempts": job.attempts,
        "due_at": iso(job.due_at),
        "expires_at": iso(job.expires_at),
        "send_at": iso(job.send_at),
        "last_error": job.last_error,
        "unclear_since": iso(job.unclear_since),
        "created_at": iso(job.created_at),
        "finished_at": iso(job.finished_at),
    }


def _job(row: sa.RowMapping) -> OutboxJob:
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
