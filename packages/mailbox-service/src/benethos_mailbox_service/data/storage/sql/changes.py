"""The change log in SQL. The sequence is the table's counting key, which
never hands out a number twice, not even after a purge. The last number
handed out is kept in ``meta``, beside the horizon."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ...models import ChangeRecord
from ..changes import LoggedChange
from .dialect import greater, in_chunks, insert_or_set
from .rows import changed
from .schema import changes, meta
from .tables import CHANGES_LAST

if TYPE_CHECKING:
    from .database import Database

_HORIZON = "changes_horizon"
_LAST = CHANGES_LAST
_c = changes.c


class SqlChangeLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, records: Iterable[ChangeRecord]) -> None:
        rows = [
            {
                "account_id": e.account_id,
                "message_id": e.id,
                "type": e.type,
                "at": iso(e.at),
                "folder_id": e.folder_id,
            }
            for e in records
        ]
        with self._db.connected() as conn:
            if rows:
                conn.execute(sa.insert(changes), rows)
            highest = sa.select(sa.func.coalesce(sa.func.max(_c.seq), 0))
            conn.execute(_never_less(_LAST, highest.scalar_subquery(), conn.dialect))

    def after(
        self,
        account_ids: Iterable[str],
        seq: int,
        *,
        limit: int,
        types: Collection[str] | None = None,
    ) -> list[LoggedChange]:
        kinds = sorted(types) if types is not None else []
        if types is not None and not kinds:
            return []
        found: list[LoggedChange] = []
        for chunk in in_chunks(account_ids):
            where = [_c.seq > seq, _c.account_id.in_(chunk)]
            if kinds:
                where.append(_c.type.in_(kinds))
            with self._db.connected() as conn:
                rows = conn.execute(
                    sa.select(changes).where(*where).order_by(_c.seq).limit(limit)
                ).mappings()
                found += map(_logged, rows)
        # The chunks each come in order: the whole is sorted once more.
        return sorted(found, key=lambda e: e.seq)[:limit]

    def last(self) -> int:
        return self._number(_LAST)

    def horizon(self) -> int:
        return self._number(_HORIZON)

    def _number(self, key: str) -> int:
        with self._db.connected() as conn:
            value = conn.execute(
                sa.select(meta.c.value).where(meta.c.key == key)
            ).scalar()
        return 0 if value is None else int(value)

    def purge(self, before: datetime) -> int:
        removed = self._purge(before)
        if removed:
            self._db.shrink()
        return removed

    def _purge(self, before: datetime) -> int:
        """Delete and move the horizon in one transaction."""
        with self._db.connected() as conn:
            seq = conn.execute(
                sa.select(sa.func.max(_c.seq)).where(_c.at < iso(before))
            ).scalar()
            if seq is None:
                return 0
            removed: int = conn.execute(
                sa.delete(changes).where(_c.at < iso(before))
            ).rowcount
            conn.execute(_never_less(_HORIZON, str(seq), conn.dialect))
            return removed

    def forget_account(self, account_id: str) -> None:
        # ON DELETE CASCADE does this as well. Said here, so both stores agree.
        changed(self._db, sa.delete(changes).where(_c.account_id == account_id))


def _never_less(key: str, value: Any, dialect: sa.Dialect) -> sa.Executable:
    """``meta`` at ``key`` set to ``value``, a number, but never to less
    than it holds."""

    def kept(excluded: Any) -> dict[str, Any]:
        return {
            "value": greater(
                sa.cast(meta.c.value, sa.BigInteger),
                sa.cast(excluded.value, sa.BigInteger),
                dialect,
            )
        }

    return insert_or_set(meta, ["key"], kept, dialect).values(key=key, value=value)


def _logged(row: sa.RowMapping) -> LoggedChange:
    return LoggedChange(
        seq=row["seq"],
        record=ChangeRecord(
            type=row["type"],
            id=row["message_id"],
            account_id=row["account_id"],
            at=parse_iso(row["at"]),
            folder_id=row["folder_id"],
        ),
    )
