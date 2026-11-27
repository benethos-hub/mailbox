"""The actions of the state file: what an agent asked, and whether it was done."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from ..records import MessageRef
from .rows import _Rows, _text
from .schema import actions

_a = actions.c


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
        statement = (
            sa.insert(actions)
            .values(
                account_id=ref.account_id,
                message_id=ref.message_id,
                action=action,
                argument=argument,
                before=json.dumps(before, sort_keys=True, ensure_ascii=False),
                stage=stage,
                executed=int(executed),
                at=_text(now),
            )
            .returning(_a.id)
        )
        with self._conn() as conn:
            return int(conn.execute(statement).scalar_one())

    def mark_action_executed(self, action_id: int) -> None:
        """Note that the action recorded as ``action_id`` was taken."""
        with self._conn() as conn:
            conn.execute(
                sa.update(actions).where(_a.id == action_id).values(executed=1)
            )

    def mark_taken(self, ref: MessageRef, action: str) -> None:
        """Note that the actions ``action`` of a message, recorded and not
        taken, were taken after all: their answer did not come."""
        with self._conn() as conn:
            conn.execute(
                sa.update(actions)
                .where(*_of(ref), _a.action == action, _a.executed == 0)
                .values(executed=1)
            )

    def drop_action(self, action_id: int) -> None:
        """Remove an action recorded before it was taken that the mailbox
        service then refused."""
        with self._conn() as conn:
            conn.execute(sa.delete(actions).where(_a.id == action_id))

    def executed_since(self, action: str, since: datetime) -> int:
        """How many actions ``action`` were carried out from ``since`` on."""
        query = sa.select(sa.func.count()).where(
            _a.action == action, _a.executed == 1, _a.at >= _text(since)
        )
        with self._conn() as conn:
            return int(conn.execute(query).scalar_one())

    def actions(self, ref: MessageRef | None = None) -> list[ActionRow]:
        """The actions of a message, or of all, in the order they ran."""
        query = sa.select(
            _a.account_id,
            _a.message_id,
            _a.action,
            _a.argument,
            _a.before,
            _a.stage,
            _a.executed,
            _a.at,
        ).order_by(_a.id)
        if ref:
            query = query.where(*_of(ref))
        with self._conn() as conn:
            return [_action(row) for row in conn.execute(query)]


def _of(ref: MessageRef) -> tuple[sa.ColumnElement[bool], ...]:
    return (_a.account_id == ref.account_id, _a.message_id == ref.message_id)


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
