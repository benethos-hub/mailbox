"""The open items of the state file: what an agent keeps an eye on."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

from ..records import KEYWORD_REMOVED, MessageRef, OpenItem
from .rows import _Rows, _text, _time
from .schema import open_items

_i = open_items.c


class _Items(_Rows):
    """The open items an agent keeps an eye on, and how each closed."""

    def open_item(
        self, ref: MessageRef, thread_id: str | None, due: datetime, now: datetime
    ) -> None:
        """Open an item for a message that has none. An item there already,
        open or closed, stays as it is, so taking a message up again opens
        nothing that a reply or a person closed."""
        with self._conn() as conn:
            conn.execute(
                dialect.insert_or_skip(open_items, conn.dialect).values(
                    account_id=ref.account_id,
                    message_id=ref.message_id,
                    thread_id=thread_id,
                    opened=_text(now),
                    due=_text(due),
                )
            )

    def restart_item(self, ref: MessageRef, due: datetime, now: datetime) -> None:
        """Start an item again with a new deadline, its keyword off, unless a
        person closed it by taking the keyword off."""
        with self._conn() as conn:
            conn.execute(
                sa.update(open_items)
                .where(
                    *_of(ref),
                    sa.or_(_i.reason.is_(None), _i.reason != KEYWORD_REMOVED),
                )
                .values(
                    opened=_text(now),
                    due=_text(due),
                    keyword_set=0,
                    keyword_recorded_stage=None,
                    closed=None,
                    reason=None,
                )
            )

    def item(self, ref: MessageRef) -> OpenItem | None:
        with self._conn() as conn:
            row = conn.execute(_select().where(*_of(ref))).first()
        return _item(row) if row else None

    def items_in_thread(self, account_id: str, thread_id: str) -> list[OpenItem]:
        """The open items of a thread, closed ones left out."""
        query = (
            _select()
            .where(
                _i.account_id == account_id,
                _i.thread_id == thread_id,
                _i.closed.is_(None),
            )
            .order_by(_i.opened)
        )
        return self._items(query)

    def open_items(self) -> list[OpenItem]:
        """The items not closed, the oldest first."""
        return self._items(_select().where(_i.closed.is_(None)).order_by(_i.opened))

    def due_items(self, now: datetime, stage: str | None = None) -> list[OpenItem]:
        """Open items past their deadline that do not carry the keyword yet,
        those already recorded in ``stage`` left out."""
        query = (
            _select()
            .where(
                _i.closed.is_(None),
                _i.keyword_set == 0,
                _i.due <= _text(now),
                sa.or_(
                    _i.keyword_recorded_stage.is_(None),
                    _i.keyword_recorded_stage.is_distinct_from(stage),
                ),
            )
            .order_by(_i.due)
        )
        return self._items(query)

    def marked_closed_items(self, reasons: Sequence[str]) -> list[OpenItem]:
        """Closed items whose keyword is still noted as set, closed for one
        of ``reasons``."""
        if not reasons:
            return []
        query = (
            _select()
            .where(
                _i.closed.is_not(None),
                _i.keyword_set == 1,
                _i.reason.in_(list(reasons)),
            )
            .order_by(_i.closed)
        )
        return self._items(query)

    def mark_keyword(self, ref: MessageRef, keyword_set: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                sa.update(open_items)
                .where(*_of(ref))
                .values(keyword_set=int(keyword_set))
            )

    def record_keyword_stage(self, ref: MessageRef, stage: str) -> None:
        """Note that the keyword of an item was recorded in ``stage`` and not
        set."""
        with self._conn() as conn:
            conn.execute(
                sa.update(open_items)
                .where(*_of(ref))
                .values(keyword_recorded_stage=stage)
            )

    def close_item(self, ref: MessageRef, reason: str, now: datetime) -> bool:
        """Close an open item. Answers whether one was open."""
        with self._conn() as conn:
            closed = conn.execute(
                sa.update(open_items)
                .where(*_of(ref), _i.closed.is_(None))
                .values(closed=_text(now), reason=reason)
            ).rowcount
        return closed > 0

    def _items(self, query: sa.Select[Any]) -> list[OpenItem]:
        with self._conn() as conn:
            return [_item(row) for row in conn.execute(query)]


def _select() -> sa.Select[Any]:
    return sa.select(
        _i.account_id,
        _i.message_id,
        _i.thread_id,
        _i.opened,
        _i.due,
        _i.keyword_set,
        _i.closed,
        _i.reason,
    )


def _of(ref: MessageRef) -> tuple[sa.ColumnElement[bool], ...]:
    return (_i.account_id == ref.account_id, _i.message_id == ref.message_id)


def _item(row: Any) -> OpenItem:
    return OpenItem(
        ref=MessageRef(account_id=row[0], message_id=row[1]),
        thread_id=row[2],
        opened=_time(row[3]),
        due=_time(row[4]),
        keyword_set=bool(row[5]),
        closed=_time(row[6]),
        reason=row[7],
    )
