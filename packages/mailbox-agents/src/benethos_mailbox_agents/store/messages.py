"""The messages of the state file: queued, their state and its counts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args

from ..records import MessageRef
from .rows import _Rows, _text, _time

# The states of a message in the state file.
State = Literal["pending", "skipped", "decided", "done", "failed"]
STATES: tuple[State, ...] = get_args(State)


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
        if again or again_skipped:
            changed = self._write(
                "INSERT INTO messages (account_id, message_id, state, attempts, "
                "next_attempt, created, updated) VALUES (?, ?, 'pending', 0, ?, ?, ?) "
                "ON CONFLICT (account_id, message_id) DO UPDATE SET "
                "state = 'pending', attempts = 0, "
                "next_attempt = excluded.next_attempt, "
                "updated = excluded.updated WHERE "
                + ("state != 'pending'" if again else "state = 'skipped'"),
                ref.account_id,
                ref.message_id,
                stamp,
                stamp,
                stamp,
            )
        else:
            changed = self._write(
                "INSERT OR IGNORE INTO messages (account_id, message_id, state, "
                "attempts, next_attempt, created, updated) "
                "VALUES (?, ?, 'pending', 0, ?, ?, ?)",
                ref.account_id,
                ref.message_id,
                stamp,
                stamp,
                stamp,
            )
        return changed > 0

    def message(self, ref: MessageRef) -> MessageRow | None:
        row = self._one(
            _MESSAGE_SQL + " WHERE account_id = ? AND message_id = ?",
            ref.account_id,
            ref.message_id,
        )
        return _message_row(row) if row else None

    def due(self, now: datetime, limit: int) -> list[MessageRow]:
        """The ``pending`` messages whose next attempt has come, oldest first."""
        rows = self._all(
            _MESSAGE_SQL + " WHERE state = 'pending' AND next_attempt <= ? "
            "ORDER BY created LIMIT ?",
            _text(now),
            limit,
        )
        return [_message_row(row) for row in rows]

    def messages(
        self, state: str | None = None, limit: int | None = None
    ) -> list[MessageRow]:
        """Every message, or those in ``state``, newest first, at most
        ``limit`` of them when it is given."""
        where = " WHERE state = ?" if state else ""
        args: tuple[Any, ...] = (state,) if state else ()
        sql = _MESSAGE_SQL + where + " ORDER BY created DESC"
        rows = (
            self._all(sql + " LIMIT ?", *args, limit)
            if limit is not None
            else self._all(sql, *args)
        )
        return [_message_row(row) for row in rows]

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
        self._write(
            "UPDATE messages SET state = ?, updated = ?, "
            "attempts = COALESCE(?, attempts), "
            "next_attempt = COALESCE(?, next_attempt) "
            "WHERE account_id = ? AND message_id = ?",
            state,
            _text(now),
            attempts,
            _text(next_attempt) if next_attempt else None,
            ref.account_id,
            ref.message_id,
        )

    def counts(self) -> dict[str, int]:
        """How many messages are in each state, every state named."""
        found: dict[str, int] = dict.fromkeys(STATES, 0)
        for state, count in self._all(
            "SELECT state, COUNT(*) FROM messages GROUP BY state"
        ):
            found[state] = count
        return found

    def oldest_pending(self) -> datetime | None:
        row = self._one("SELECT MIN(created) FROM messages WHERE state = 'pending'")
        return _time(row[0]) if row else None


# The columns each kind of row is read with, in the order of its reader
# below.
_MESSAGE_SQL = (
    "SELECT account_id, message_id, state, attempts, next_attempt, created, "
    "updated FROM messages"
)


def _message_row(row: Any) -> MessageRow:
    return MessageRow(
        ref=MessageRef(account_id=row[0], message_id=row[1]),
        state=row[2],
        attempts=row[3],
        next_attempt=datetime.fromisoformat(row[4]),
        created=datetime.fromisoformat(row[5]),
        updated=datetime.fromisoformat(row[6]),
    )
