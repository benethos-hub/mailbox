"""The audit of administration in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ...models import ActivityFilter, ActivityRecord, Before
from .rows import changed
from .schema import activity

if TYPE_CHECKING:
    from .database import Database

_a = activity.c


class SqlAuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, record: ActivityRecord) -> None:
        changed(
            self._db,
            sa.insert(activity).values(
                id=record.id,
                at=iso(record.at),
                activity=record.activity,
                user_id=record.user_id,
                user_name=record.user_name,
                credential=record.credential,
                record=record.record,
                source=record.source,
                outcome=record.outcome,
                detail=record.detail,
            ),
        )

    def list(
        self,
        *,
        limit: int,
        before: Before | None,
        matching: ActivityFilter | None = None,
    ) -> list[ActivityRecord]:
        where: list[sa.ColumnElement[bool]] = []
        if before is not None:
            where.append(sa.tuple_(_a.at, _a.id) < sa.tuple_(iso(before.at), before.id))
        if matching is not None:
            where += _matching(matching)
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(activity)
                .where(*where)
                .order_by(_a.at.desc(), _a.id.desc())
                .limit(limit)
            ).mappings()
            return [_activity(row) for row in rows]

    def purge(self, before: datetime) -> int:
        return self._db.purge("activity", "at", before)


def _matching(matching: ActivityFilter) -> list[sa.ColumnElement[bool]]:
    where: list[sa.ColumnElement[bool]] = []
    if matching.user_id is not None:
        where.append(_a.user_id == matching.user_id)
    if matching.record is not None:
        where.append(_a.record == matching.record)
    if matching.after is not None:
        where.append(_a.at >= iso(matching.after))
    if matching.before is not None:
        where.append(_a.at < iso(matching.before))
    if matching.activity is not None:
        # The name itself, or every name of its area.
        area = f"{matching.activity}."
        where.append(
            sa.or_(
                _a.activity == matching.activity,
                sa.func.substr(_a.activity, 1, len(area)) == area,
            )
        )
    return where


def _activity(row: sa.RowMapping) -> ActivityRecord:
    return ActivityRecord(
        id=row["id"],
        at=parse_iso(row["at"]),
        activity=row["activity"],
        user_id=row["user_id"],
        user_name=row["user_name"],
        credential=row["credential"],
        record=row["record"],
        source=row["source"],
        outcome=row["outcome"],
        detail=row["detail"],
    )
