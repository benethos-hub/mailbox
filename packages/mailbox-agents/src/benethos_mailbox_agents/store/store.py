"""One agent's state file: SQLite in WAL mode.

One process writes a file, the agent's own. Any other process may read it
at the same time, opened with ``read_only``: ``report``, ``status``, the
health check, and later an overview of what every agent did. Calls are
short and made from the one event loop of the process, so they run
synchronously. What is stored is ids, decisions, evidence quotes, counts
and times, never the text of a mail. See docs/mailbox-agents/concept/state.md.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import IO, TypeVar

from ..errors import ConfigError, StateFileError
from .actions import _Actions
from .calls import _Calls
from .items import _Items
from .messages import _Messages
from .migrations import MIGRATIONS, SCHEMA_VERSION
from .rows import _sqlite, _text, _time
from .steps import _Steps

T = TypeVar("T")

__all__ = ["Migrated", "Store", "earlier_file", "path_for"]


def path_for(data_dir: Path, agent: str) -> Path:
    """Where the state file of ``agent`` lives."""
    return data_dir / f"{agent}.db"


# Where the state files lay before they had a folder of their own: data/
# below the working directory, unless a setting named another.
EARLIER_DATA_DIR = Path("data")


def earlier_file(data_dir: Path, agent: str) -> Path | None:
    """The state file of ``agent`` at the place before, when there is
    one and none at ``data_dir``: a writer does not start anew beside
    it, as the cursor and every decision are in it."""
    found = path_for(EARLIER_DATA_DIR, agent)
    now = path_for(data_dir, agent)
    if now.is_file() or not found.is_file():
        return None
    return None if found.resolve() == now.resolve() else found


@dataclass(frozen=True, slots=True)
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


class Store(_Messages, _Steps, _Actions, _Items, _Calls):
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
