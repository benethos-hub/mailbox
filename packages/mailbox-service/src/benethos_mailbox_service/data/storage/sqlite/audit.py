"""The audit of administration in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ....common.clock import iso, parse_iso
from ...models import ActivityFilter, ActivityRecord, Before
from .database import Database


class SqliteAuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, record: ActivityRecord) -> None:
        self._db.execute(
            "INSERT INTO activity (id, at, activity, user_id, user_name,"
            " credential, record, source, outcome, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                iso(record.at),
                record.activity,
                record.user_id,
                record.user_name,
                record.credential,
                record.record,
                record.source,
                record.outcome,
                record.detail,
            ),
        )

    def list(
        self,
        *,
        limit: int,
        before: Before | None,
        matching: ActivityFilter | None = None,
    ) -> list[ActivityRecord]:
        where = ["1"]
        params: list[object] = []
        if before is not None:
            where.append("(at, id) < (?, ?)")
            params += [iso(before.at), before.id]
        if matching is not None:
            for column, value in (
                ("user_id = ?", matching.user_id),
                ("record = ?", matching.record),
                ("at >= ?", iso(matching.after)),
                ("at < ?", iso(matching.before)),
            ):
                if value is not None:
                    where.append(column)
                    params.append(value)
            if matching.activity is not None:
                # The name itself, or every name of its area.
                area = f"{matching.activity}."
                where.append("(activity = ? OR substr(activity, 1, ?) = ?)")
                params += [matching.activity, len(area), area]
        rows = self._db.query(
            f"SELECT * FROM activity WHERE {' AND '.join(where)}"
            " ORDER BY at DESC, id DESC LIMIT ?",
            (*params, limit),
        )
        return [_activity(row) for row in rows]

    def purge(self, before: datetime) -> int:
        return self._db.purge("activity", "at", before)


def _activity(row: sqlite3.Row) -> ActivityRecord:
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
