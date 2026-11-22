"""One agent's state file: SQLite in WAL mode.

One process writes a file, the agent's own. Any other process may read it
at the same time, opened with ``read_only``: ``report``, ``status``, the
health check, and later an overview of what every agent did. Calls are
short and made from the one event loop of the process, so they run
synchronously. What is stored is ids, decisions, evidence quotes, counts
and times, never the text of a mail. See docs/mailbox-agents/concept/state.md.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Any, TypeVar

from ..errors import ConfigError, StateFileError
from ..records import KEYWORD_REMOVED, MessageRef, OpenItem, Step, StepResult
from .migrations import MIGRATIONS, SCHEMA_VERSION

T = TypeVar("T")

__all__ = [
    "STATES",
    "Migrated",
    "ActionRow",
    "MessageRow",
    "Store",
    "path_for",
]

STATES = ("pending", "skipped", "decided", "done", "failed")


def path_for(data_dir: Path, agent: str) -> Path:
    """Where the state file of ``agent`` lives."""
    return data_dir / f"{agent}.db"


@dataclass(frozen=True)
class Migrated:
    """What opening a state file did to its schema, for the caller to log:
    from ``before`` to ``after``, 0 for a new file, with the notes of the
    steps that had any."""

    before: int
    after: int
    notes: tuple[str, ...] = ()


def _lock(path: Path) -> IO[bytes]:
    """An exclusive lock on ``<path>.lock``, held while the handle is open:
    one writer per state file. Another writer is refused at once."""
    handle = _made(path, lambda: path.with_name(path.name + ".lock").open("a+b"))
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ConfigError(
            f"{path.stem} is already running: one writer per state file"
        ) from None
    return handle


def _made(path: Path, make: Callable[[], T]) -> T:
    """What ``make`` answers, the folder of the state file or its lock. A
    folder that is a file or a volume without the right to write is a
    :class:`StateFileError` naming the file and the kind of error."""
    try:
        return make()
    except OSError as exc:
        raise StateFileError(
            f"the state file {path.name}: its folder or lock cannot be made "
            f"({type(exc).__name__})"
        ) from None


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    handle.close()


def _text(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("a time stored must carry its zone")
    return moment.astimezone(UTC).isoformat()


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


@dataclass(frozen=True)
class MessageRow:
    ref: MessageRef
    state: str
    attempts: int
    next_attempt: datetime
    created: datetime
    updated: datetime


@dataclass(frozen=True)
class ActionRow:
    ref: MessageRef
    action: str
    argument: str
    before: Any
    stage: str
    executed: bool
    at: datetime


@contextmanager
def _sqlite(name: str) -> Iterator[None]:
    """A :class:`StateFileError` for any error of sqlite, naming the file
    and what sqlite said: the store is the one home of sqlite3, and no
    caller knows its errors."""
    try:
        yield
    except sqlite3.Error as exc:
        raise StateFileError(f"the state file {name or ''}: {exc}") from None


class Store:
    """The state file of one agent."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        read_only: bool,
        lock: IO[bytes] | None = None,
        name: str = "",
    ) -> None:
        self._db = connection
        self._name = name
        self.read_only = read_only
        self._lock = lock
        # What the last migrate did to the file, None when it was current.
        self.migrated: Migrated | None = None

    # -- opening ----------------------------------------------------------------

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> Store:
        """Open the file at ``path``. A writer creates it and runs the
        migrations it lacks. A reader needs it to exist and to be current.
        A writer holds a lock beside the file until it is closed, so a
        second writer, such as ``run`` beside a running ``worker``, is
        refused."""
        if read_only:
            if not path.is_file():
                raise ConfigError(f"no state file {path.name}")
            with _sqlite(path.name):
                connection = sqlite3.connect(
                    f"{path.resolve().as_uri()}?mode=ro",
                    uri=True,
                    isolation_level=None,
                )
            lock = None
        else:
            _made(path, lambda: path.parent.mkdir(parents=True, exist_ok=True))
            lock = _lock(path)
            try:
                with _sqlite(path.name):
                    connection = sqlite3.connect(path, isolation_level=None)
            except BaseException:
                _unlock(lock)
                raise
        store = cls(connection, read_only, lock, path.name)
        try:
            with _sqlite(path.name):
                connection.execute("PRAGMA busy_timeout = 5000")
                if read_only:
                    store._check_version()
                else:
                    # A deleted row is overwritten, so a kept call purged
                    # after its time leaves no text of a mail in the file.
                    connection.execute("PRAGMA secure_delete = ON")
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("PRAGMA synchronous = NORMAL")
                    store.migrate()
        except BaseException:
            store.close()
            raise
        return store

    def close(self) -> None:
        self._db.close()
        if self._lock is not None:
            _unlock(self._lock)
            self._lock = None

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def version(self) -> int:
        with _sqlite(self._name):
            found: int = self._db.execute("PRAGMA user_version").fetchone()[0]
        return found

    def _check_version(self) -> None:
        if self.version > SCHEMA_VERSION:
            raise ConfigError(
                f"the state file is at schema version {self.version}, "
                f"this program knows {SCHEMA_VERSION}"
            )

    def migrate(self) -> int:
        """Run the steps the file lacks, each in a transaction of its own
        with its version, and keep what they did in ``migrated``. Answers
        the version reached. The store logs nothing: the caller does."""
        self._check_version()
        before = self.version
        notes: list[str] = []
        for step in MIGRATIONS.pending(before):
            with _sqlite(self._name), self._transaction():
                self._db.execute("BEGIN IMMEDIATE")
                said = step.apply(self._db)
                self._db.execute(f"PRAGMA user_version = {step.version}")
                self._db.execute("COMMIT")
            notes += [f"schema {step.version}: {note}" for note in said]
        if self.version > before:
            self.migrated = Migrated(before, self.version, tuple(notes))
        return self.version

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _one(self, sql: str, *args: Any) -> Any:
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as rows:
            return rows.fetchone()

    def _all(self, sql: str, *args: Any) -> list[Any]:
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as rows:
            return rows.fetchall()

    def _write(self, sql: str, *args: Any) -> int:
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as done:
            return done.rowcount

    def _insert(self, sql: str, *args: Any) -> int:
        """Insert one row. Answers its id."""
        with _sqlite(self._name), closing(self._db.execute(sql, args)) as done:
            if done.lastrowid is None:
                raise RuntimeError("an insert answered no row id")
            return done.lastrowid

    # -- cursor and passes --------------------------------------------------------

    def cursor(self) -> str | None:
        row = self._one("SELECT state FROM cursor WHERE id = 1")
        return row[0] if row else None

    def set_cursor(self, state: str, now: datetime) -> None:
        self._write(
            "INSERT INTO cursor (id, state, updated) VALUES (1, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET state = excluded.state, "
            "updated = excluded.updated",
            state,
            _text(now),
        )

    def progress(self) -> datetime | None:
        """When the loop last showed progress: after a message it ran, a
        pass it finished, or a slice of a wait. The health check reads it."""
        row = self._one("SELECT finished FROM passes WHERE id = 1")
        return _time(row[0]) if row else None

    def set_progress(self, now: datetime) -> None:
        """Note progress of the loop at ``now``. The table and its column
        keep the names of migration 1."""
        self._write(
            "INSERT INTO passes (id, finished) VALUES (1, ?) "
            "ON CONFLICT (id) DO UPDATE SET finished = excluded.finished",
            _text(now),
        )

    # -- messages -------------------------------------------------------------------

    def enqueue(self, ref: MessageRef, now: datetime, *, again: bool = False) -> bool:
        """Record ``ref`` as ``pending``. A message already known is left
        as it is, unless ``again``, which makes it ``pending`` anew for a
        backfill under a new prompt or model. Answers whether it is now
        pending because of this call."""
        stamp = _text(now)
        if again:
            changed = self._write(
                "INSERT INTO messages (account_id, message_id, state, attempts, "
                "next_attempt, created, updated) VALUES (?, ?, 'pending', 0, ?, ?, ?) "
                "ON CONFLICT (account_id, message_id) DO UPDATE SET "
                "state = 'pending', attempts = 0, "
                "next_attempt = excluded.next_attempt, "
                "updated = excluded.updated WHERE state != 'pending'",
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
        state: str,
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
        found = dict.fromkeys(STATES, 0)
        for state, count in self._all(
            "SELECT state, COUNT(*) FROM messages GROUP BY state"
        ):
            found[state] = count
        return found

    def oldest_pending(self) -> datetime | None:
        row = self._one("SELECT MIN(created) FROM messages WHERE state = 'pending'")
        return _time(row[0]) if row else None

    # -- steps ------------------------------------------------------------------

    def add_step(self, ref: MessageRef, result: StepResult, model_alias: str) -> None:
        self._write(
            "INSERT INTO steps (account_id, message_id, step, prompt_version, "
            "model_alias, model, result, tokens_in, tokens_out, duration_ms, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ref.account_id,
            ref.message_id,
            result.step,
            result.prompt_version,
            model_alias,
            result.model,
            json.dumps(result.result, sort_keys=True, ensure_ascii=False),
            result.tokens_in,
            result.tokens_out,
            result.duration_ms,
            _text(result.at),
        )

    def step(
        self, ref: MessageRef, step: Step, prompt_version: str, model_alias: str
    ) -> StepResult | None:
        """The latest result of ``step`` for this message under this prompt
        version and model alias, the key of idempotency."""
        row = self._one(
            _STEP_SQL + " WHERE account_id = ? AND message_id = ? "
            "AND step = ? AND prompt_version = ? AND model_alias = ? "
            "ORDER BY id DESC LIMIT 1",
            ref.account_id,
            ref.message_id,
            step,
            prompt_version,
            model_alias,
        )
        return _step(row) if row else None

    def steps(self, ref: MessageRef) -> list[StepResult]:
        """Every step of a message, in the order they ran."""
        rows = self._all(
            _STEP_SQL + " WHERE account_id = ? AND message_id = ? ORDER BY id",
            ref.account_id,
            ref.message_id,
        )
        return [_step(row) for row in rows]

    def model_calls_since(self, since: datetime) -> int:
        row = self._one(
            "SELECT COUNT(*) FROM steps WHERE step = ? AND at >= ?",
            "model",
            _text(since),
        )
        return int(row[0])

    # -- actions ---------------------------------------------------------------

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

    # -- open items --------------------------------------------------------------

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

    # -- kept model calls, docs/mailbox-agents/concept/state.md ------------------------

    def add_call(
        self, ref: MessageRef, request: Any, answer: Any, now: datetime
    ) -> None:
        self._write(
            "INSERT INTO calls (account_id, message_id, request, answer, at) "
            "VALUES (?, ?, ?, ?, ?)",
            ref.account_id,
            ref.message_id,
            # Escaped, so a lone surrogate in what the gateway answered
            # cannot end the write.
            json.dumps(request),
            json.dumps(answer),
            _text(now),
        )

    def purge_calls(self, before: datetime) -> int:
        """Delete the kept calls older than ``before``. Answers how many.
        After a deletion the write-ahead log is written back and emptied, so
        the deleted text is gone from it as well."""
        purged = self._write("DELETE FROM calls WHERE at < ?", _text(before))
        if purged:
            self._one("PRAGMA wal_checkpoint(TRUNCATE)")
        return purged

    def count_calls(self) -> int:
        return int(self._one("SELECT COUNT(*) FROM calls")[0])


# The columns each kind of row is read with, in the order of its reader
# below.
_MESSAGE_SQL = (
    "SELECT account_id, message_id, state, attempts, next_attempt, created, "
    "updated FROM messages"
)
_STEP_SQL = (
    "SELECT step, prompt_version, model, result, tokens_in, tokens_out, "
    "duration_ms, at FROM steps"
)
_ACTION_SQL = (
    "SELECT account_id, message_id, action, argument, before, stage, "
    "executed, at FROM actions"
)
_ITEM_SQL = (
    "SELECT account_id, message_id, thread_id, opened, due, keyword_set, closed, "
    "reason FROM open_items"
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


def _step(row: Any) -> StepResult:
    return StepResult(
        step=row[0],
        prompt_version=row[1],
        model=row[2],
        result=json.loads(row[3]),
        tokens_in=row[4],
        tokens_out=row[5],
        duration_ms=row[6],
        at=datetime.fromisoformat(row[7]),
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
