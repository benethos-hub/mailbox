"""The audit of sends in SQL."""

from __future__ import annotations

import builtins
import json
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from benethos_mailbox_common.storage import rows as table_rows

from ....common.clock import iso, parse_iso
from ...models import Before, SendFilter, SendOutcome, SendRecord
from .schema import sends

if TYPE_CHECKING:
    from .database import Database

_s = sends.c


class SqlSendLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, record: SendRecord) -> None:
        table_rows.rows_changed(
            self._db,
            sa.insert(sends).values(
                id=record.id,
                created_at=iso(record.created_at),
                user_id=record.user_id,
                credential_id=record.credential_id,
                account_id=record.account_id,
                operation=record.operation,
                recipients=json.dumps(record.recipients),
                outcome=record.outcome,
                error=record.error,
                refused=json.dumps(record.refused),
                message_id_header=record.message_id_header,
                outbox_job_id=record.outbox_job_id,
                recipients_folded=folded(record.recipients),
            ),
        )

    def sent_since(
        self, user_id: str, account_id: str, since: datetime, *, outcome: SendOutcome
    ) -> list[datetime]:
        with self._db.connected() as conn:
            found = conn.execute(
                sa.select(_s.created_at)
                .where(
                    _s.user_id == user_id,
                    _s.account_id == account_id,
                    _s.outcome == outcome,
                    _s.created_at > iso(since),
                )
                .order_by(_s.created_at)
            ).scalars()
            return [parse_iso(at) for at in found]

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        matching: SendFilter | None = None,
    ) -> list[SendRecord]:
        where: list[sa.ColumnElement[bool]] = [_s.account_id == account_id]
        if before is not None:
            where.append(
                sa.tuple_(_s.created_at, _s.id) < sa.tuple_(iso(before.at), before.id)
            )
        if matching is not None:
            where += _matching(matching)
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(sends)
                .where(*where)
                .order_by(_s.created_at.desc(), _s.id.desc())
                .limit(limit)
            ).mappings()
            return [_send(row) for row in rows]

    def account_ids(self) -> builtins.list[str]:
        with self._db.connected() as conn:
            found = conn.execute(
                sa.select(_s.account_id).distinct().order_by(_s.account_id)
            ).scalars()
            return list(found)

    def purge(self, before: datetime) -> int:
        return self._db.purge(sends, "created_at", before)


def _matching(matching: SendFilter) -> builtins.list[sa.ColumnElement[bool]]:
    where: builtins.list[sa.ColumnElement[bool]] = []
    if matching.user_id is not None:
        where.append(_s.user_id == matching.user_id)
    if matching.outcome is not None:
        where.append(_s.outcome == matching.outcome)
    if matching.after is not None:
        where.append(_s.created_at >= iso(matching.after))
    if matching.before is not None:
        where.append(_s.created_at < iso(matching.before))
    if matching.recipient:
        # One address per line: a part with a line break would reach
        # across two, and no address holds one.
        where.append(
            _s.recipients_folded.like(
                _within(matching.recipient.casefold()), escape="\\"
            )
        )
    return where


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


def _send(row: sa.RowMapping) -> SendRecord:
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
