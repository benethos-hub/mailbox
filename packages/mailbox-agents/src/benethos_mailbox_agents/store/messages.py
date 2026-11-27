"""The messages of the state file: queued, their state and its counts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

from ..records import MessageRef
from .rows import _Rows, _text, _time
from .schema import messages

# The states of a message in the state file.
State = Literal["pending", "skipped", "decided", "done", "failed"]
STATES: tuple[State, ...] = get_args(State)

_m = messages.c


@dataclass(frozen=True, slots=True)
class MessageRow:
    ref: MessageRef
    state: str
    attempts: int
    next_attempt: datetime
    created: datetime
    updated: datetime


class _Messages(_Rows):
    """The messages an agent takes up, and their state."""

    def enqueue(
        self,
        ref: MessageRef,
        now: datetime,
        *,
        again: bool = False,
        again_skipped: bool = False,
    ) -> bool:
        """Record ``ref`` as ``pending``. A message already known is left
        as it is, unless ``again``, which makes it ``pending`` anew for a
        backfill under a new prompt or model, or ``again_skipped``, which
        does so for a message ``skipped`` alone. Answers whether it is now
        pending because of this call."""
        stamp = _text(now)
        row = {
            "account_id": ref.account_id,
            "message_id": ref.message_id,
            "state": "pending",
            "attempts": 0,
            "next_attempt": stamp,
            "created": stamp,
            "updated": stamp,
        }
        with self._conn() as conn:
            if not (again or again_skipped):
                skipping = dialect.insert_or_skip(messages, conn.dialect)
                return _taken(conn, skipping.values(row))
            statement = dialect.insert_or_set(
                messages,
                ["account_id", "message_id"],
                lambda excluded: {
                    "state": "pending",
                    "attempts": 0,
                    "next_attempt": excluded.next_attempt,
                    "updated": excluded.updated,
                },
                conn.dialect,
                where=_m.state != "pending" if again else _m.state == "skipped",
            )
            return _taken(conn, statement.values(row))

    def message(self, ref: MessageRef) -> MessageRow | None:
        with self._conn() as conn:
            row = conn.execute(_select().where(*_of(ref))).first()
        return _message_row(row) if row else None

    def due(self, now: datetime, limit: int) -> list[MessageRow]:
        """The ``pending`` messages whose next attempt has come, oldest first."""
        query = (
            _select()
            .where(_m.state == "pending", _m.next_attempt <= _text(now))
            .order_by(_m.created)
            .limit(limit)
        )
        with self._conn() as conn:
            return [_message_row(row) for row in conn.execute(query)]

    def messages(
        self, state: str | None = None, limit: int | None = None
    ) -> list[MessageRow]:
        """Every message, or those in ``state``, newest first, at most
        ``limit`` of them when it is given."""
        query = _select().order_by(_m.created.desc())
        if state:
            query = query.where(_m.state == state)
        if limit is not None:
            query = query.limit(limit)
        with self._conn() as conn:
            return [_message_row(row) for row in conn.execute(query)]

    def set_state(
        self,
        ref: MessageRef,
        state: State,
        now: datetime,
        *,
        attempts: int | None = None,
        next_attempt: datetime | None = None,
    ) -> None:
        if state not in STATES:
            raise ValueError(f"no message state {state!r}")
        values: dict[str, object] = {"state": state, "updated": _text(now)}
        if attempts is not None:
            values["attempts"] = attempts
        if next_attempt is not None:
            values["next_attempt"] = _text(next_attempt)
        with self._conn() as conn:
            conn.execute(sa.update(messages).where(*_of(ref)).values(values))

    def counts(self) -> dict[str, int]:
        """How many messages are in each state, every state named."""
        found: dict[str, int] = dict.fromkeys(STATES, 0)
        query = sa.select(_m.state, sa.func.count()).group_by(_m.state)
        with self._conn() as conn:
            for state, count in conn.execute(query):
                found[state] = count
        return found

    def oldest_pending(self) -> datetime | None:
        query = sa.select(sa.func.min(_m.created)).where(_m.state == "pending")
        with self._conn() as conn:
            return _time(conn.execute(query).scalar())


def _taken(conn: sa.Connection, statement: dialect.Insert) -> bool:
    """Whether ``statement`` wrote the row: the row it gives back, as each
    database tells it alike, where the count of rows does not."""
    return conn.execute(statement.returning(_m.message_id)).first() is not None


def _select() -> sa.Select[Any]:
    return sa.select(
        _m.account_id,
        _m.message_id,
        _m.state,
        _m.attempts,
        _m.next_attempt,
        _m.created,
        _m.updated,
    )


def _of(ref: MessageRef) -> tuple[sa.ColumnElement[bool], ...]:
    return (_m.account_id == ref.account_id, _m.message_id == ref.message_id)


def _message_row(row: Any) -> MessageRow:
    return MessageRow(
        ref=MessageRef(account_id=row[0], message_id=row[1]),
        state=row[2],
        attempts=row[3],
        next_attempt=datetime.fromisoformat(row[4]),
        created=datetime.fromisoformat(row[5]),
        updated=datetime.fromisoformat(row[6]),
    )
