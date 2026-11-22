"""The open items of the state file: what an agent keeps an eye on."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ..records import KEYWORD_REMOVED, MessageRef, OpenItem
from .rows import _Rows, _text, _time


class _Items(_Rows):
    """The open items an agent keeps an eye on, and how each closed."""

    def open_item(
        self, ref: MessageRef, thread_id: str | None, due: datetime, now: datetime
    ) -> None:
        """Open an item for a message that has none. An item there already,
        open or closed, stays as it is, so taking a message up again opens
        nothing that a reply or a person closed."""
        self._write(
            "INSERT INTO open_items (account_id, message_id, thread_id, opened, due) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (account_id, message_id) DO NOTHING",
            ref.account_id,
            ref.message_id,
            thread_id,
            _text(now),
            _text(due),
        )

    def restart_item(self, ref: MessageRef, due: datetime, now: datetime) -> None:
        """Start an item again with a new deadline, its keyword off, unless a
        person closed it by taking the keyword off."""
        self._write(
            "UPDATE open_items SET opened = ?, due = ?, keyword_set = 0, "
            "keyword_recorded_stage = NULL, closed = NULL, reason = NULL "
            "WHERE account_id = ? AND message_id = ? "
            "AND (reason IS NULL OR reason != ?)",
            _text(now),
            _text(due),
            ref.account_id,
            ref.message_id,
            KEYWORD_REMOVED,
        )

    def item(self, ref: MessageRef) -> OpenItem | None:
        row = self._one(
            _ITEM_SQL + " WHERE account_id = ? AND message_id = ?",
            ref.account_id,
            ref.message_id,
        )
        return _item(row) if row else None

    def items_in_thread(self, account_id: str, thread_id: str) -> list[OpenItem]:
        """The open items of a thread, closed ones left out."""
        rows = self._all(
            _ITEM_SQL + " WHERE account_id = ? AND thread_id = ? AND closed IS NULL "
            "ORDER BY opened",
            account_id,
            thread_id,
        )
        return [_item(row) for row in rows]

    def open_items(self) -> list[OpenItem]:
        """The items not closed, the oldest first."""
        rows = self._all(_ITEM_SQL + " WHERE closed IS NULL ORDER BY opened")
        return [_item(row) for row in rows]

    def due_items(self, now: datetime, stage: str | None = None) -> list[OpenItem]:
        """Open items past their deadline that do not carry the keyword yet,
        those already recorded in ``stage`` left out."""
        rows = self._all(
            _ITEM_SQL + " WHERE closed IS NULL AND keyword_set = 0 AND due <= ? "
            "AND (keyword_recorded_stage IS NULL OR keyword_recorded_stage IS NOT ?) "
            "ORDER BY due",
            _text(now),
            stage,
        )
        return [_item(row) for row in rows]

    def marked_closed_items(self, reasons: Sequence[str]) -> list[OpenItem]:
        """Closed items whose keyword is still noted as set, closed for one
        of ``reasons``."""
        if not reasons:
            return []
        marks = ", ".join("?" for _ in reasons)
        rows = self._all(
            _ITEM_SQL + " WHERE closed IS NOT NULL AND keyword_set = 1 "
            f"AND reason IN ({marks}) ORDER BY closed",
            *reasons,
        )
        return [_item(row) for row in rows]

    def mark_keyword(self, ref: MessageRef, keyword_set: bool) -> None:
        self._write(
            "UPDATE open_items SET keyword_set = ? WHERE account_id = ? "
            "AND message_id = ?",
            int(keyword_set),
            ref.account_id,
            ref.message_id,
        )

    def record_keyword_stage(self, ref: MessageRef, stage: str) -> None:
        """Note that the keyword of an item was recorded in ``stage`` and not
        set."""
        self._write(
            "UPDATE open_items SET keyword_recorded_stage = ? WHERE account_id = ? "
            "AND message_id = ?",
            stage,
            ref.account_id,
            ref.message_id,
        )

    def close_item(self, ref: MessageRef, reason: str, now: datetime) -> bool:
        """Close an open item. Answers whether one was open."""
        return (
            self._write(
                "UPDATE open_items SET closed = ?, reason = ? WHERE account_id = ? "
                "AND message_id = ? AND closed IS NULL",
                _text(now),
                reason,
                ref.account_id,
                ref.message_id,
            )
            > 0
        )


# The columns each kind of row is read with, in the order of its reader
# below.
_ITEM_SQL = (
    "SELECT account_id, message_id, thread_id, opened, due, keyword_set, closed, "
    "reason FROM open_items"
)


def _item(row: Any) -> OpenItem:
    return OpenItem(
        ref=MessageRef(account_id=row[0], message_id=row[1]),
        thread_id=row[2],
        opened=datetime.fromisoformat(row[3]),
        due=datetime.fromisoformat(row[4]),
        keyword_set=bool(row[5]),
        closed=_time(row[6]),
        reason=row[7],
    )
