"""The actions of the state file: what an agent asked, and whether it was done."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..records import MessageRef
from .rows import _Rows, _text


@dataclass(frozen=True, slots=True)
class ActionRow:
    ref: MessageRef
    action: str
    argument: str
    before: Any
    stage: str
    executed: bool
    at: datetime


class _Actions(_Rows):
    """The actions asked for a message, and whether each was done."""

    def add_action(
        self,
        ref: MessageRef,
        *,
        action: str,
        argument: str,
        before: Any,
        stage: str,
        executed: bool,
        now: datetime,
    ) -> int:
        """Record an action. Answers its id."""
        return self._insert(
            "INSERT INTO actions (account_id, message_id, action, argument, before, "
            "stage, executed, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ref.account_id,
            ref.message_id,
            action,
            argument,
            json.dumps(before, sort_keys=True, ensure_ascii=False),
            stage,
            int(executed),
            _text(now),
        )

    def mark_action_executed(self, action_id: int) -> None:
        """Note that the action recorded as ``action_id`` was taken."""
        self._write("UPDATE actions SET executed = 1 WHERE id = ?", action_id)

    def drop_action(self, action_id: int) -> None:
        """Remove an action recorded before it was taken that the mailbox
        service then refused."""
        self._write("DELETE FROM actions WHERE id = ?", action_id)

    def executed_since(self, action: str, since: datetime) -> int:
        """How many actions ``action`` were carried out from ``since`` on."""
        row = self._one(
            "SELECT COUNT(*) FROM actions WHERE action = ? AND executed = 1 "
            "AND at >= ?",
            action,
            _text(since),
        )
        return int(row[0])

    def actions(self, ref: MessageRef | None = None) -> list[ActionRow]:
        """The actions of a message, or of all, in the order they ran."""
        rows = (
            self._all(
                _ACTION_SQL + " WHERE account_id = ? AND message_id = ? ORDER BY id",
                ref.account_id,
                ref.message_id,
            )
            if ref
            else self._all(_ACTION_SQL + " ORDER BY id")
        )
        return [_action(row) for row in rows]


# The columns each kind of row is read with, in the order of its reader
# below.
_ACTION_SQL = (
    "SELECT account_id, message_id, action, argument, before, stage, "
    "executed, at FROM actions"
)


def _action(row: Any) -> ActionRow:
    return ActionRow(
        ref=MessageRef(account_id=row[0], message_id=row[1]),
        action=row[2],
        argument=row[3],
        before=json.loads(row[4]),
        stage=row[5],
        executed=bool(row[6]),
        at=datetime.fromisoformat(row[7]),
    )
