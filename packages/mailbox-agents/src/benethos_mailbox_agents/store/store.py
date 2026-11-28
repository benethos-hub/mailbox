"""One agent's state file: a database of the storage of mailbox-common,
by default a file of SQLite in WAL mode.

One process writes a file, the agent's own. Any other process may read it
at the same time, opened with ``read_only``: ``report``, ``status``, the
health check and the cockpit. Calls are short and made from the one
event loop of the process, so they run synchronously. What is stored is
ids, decisions, evidence quotes, counts and times, never the text of a
mail. See docs/mailbox-agents/concept/state.md.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TypeVar

import sqlalchemy as sa

from benethos_mailbox_common.storage import (
    database,
    dialect,
    locks,
    migrated,
    server_place,
    server_rights,
    sqlite_file,
)

from ..errors import ConfigError, StateFileError
from .actions import _Actions
from .calls import _Calls
from .items import _Items
from .messages import _Messages
from .profile import _Profile
from .reader import ReadPlace
from .rows import _named, _text, _time
from .schema import cursor, passes
from .shape import SHAPE
from .steps import _Steps

T = TypeVar("T")

__all__ = ["Migrated", "Store", "earlier_file", "path_for"]


def path_for(data_dir: Path, agent: str) -> Path:
    """Where the state file of ``agent`` lives, ``agent`` its state name,
    with its instance when it has one."""
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


# What opening a state file did to its schema, for the caller to log:
# from ``before`` to ``after``, 0 for a new file, with the notes of the
# steps that had any.
Migrated = migrated.Migrated


def _lock(path: Path) -> ExitStack:
    """An exclusive lock on ``<path>.lock``, held until the stack is
    closed: one writer per state file. Another writer is refused at once."""
    held = ExitStack()
    lock = locks.exclusive_lock(sqlite_file.lock_file(path))
    try:
        _made(path, lambda: held.enter_context(lock))
    except locks.LockedError:
        raise ConfigError(
            f"{path.stem} is already running: one writer per state file"
        ) from None
    return held


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


def _unlock(held: ExitStack) -> None:
    held.close()


def _at_this_schema(held: int) -> None:
    """A reader takes the state at the schema of this version alone."""
    newest = SHAPE.newest
    if held > newest:
        raise ConfigError(
            f"the state is at schema version {held}, this program knows {newest}"
        )
    if held < newest:
        raise ConfigError(
            f"the state is at schema version {held}, this program reads {newest}:"
            " start the agent once, which brings it forward"
        )


class Store(_Messages, _Steps, _Actions, _Items, _Calls, _Profile):
    """The state file of one agent."""

    def __init__(
        self,
        db: database.Database,
        read_only: bool,
        lock: ExitStack | None = None,
        name: str = "",
    ) -> None:
        self._db = db
        self._name = name
        self.read_only = read_only
        self._lock = lock
        # What opening did to the file, None when it was current.
        self.migrated: Migrated | None = db.migrated
        # On a server: what the start did to the rights of the database.
        self.rights: server_rights.Rights | None = None

    # -- opening ----------------------------------------------------------------

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> Store:
        """Open the file at ``path``. A writer creates it and brings it to
        the schema of this version. A reader needs it to exist at that
        schema: one older or newer is refused. A writer holds a lock
        beside the file until it is closed, so a second writer, such as
        ``run`` beside a running ``worker``, is refused."""
        if read_only:
            with _named(path.name):
                db = database.Database(SHAPE, place=ReadPlace(path))
            return cls(db, True, None, path.name)
        _made(path, lambda: path.parent.mkdir(parents=True, exist_ok=True))
        lock = _lock(path)
        try:
            with _named(path.name):
                db = database.Database(SHAPE, path)
        except BaseException:
            _unlock(lock)
            raise
        return cls(db, False, lock, path.name)

    @classmethod
    def open_server(
        cls,
        server: server_place.Server,
        *,
        readers: tuple[str, ...] = (),
        setting: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> Store:
        """Open the state in the schema of the role of ``server``, in a
        database of its own, as its writer: make the schema where it is
        missing, bring it to the schema of this version, take the lock
        of a running agent, so a second writer is refused, and give the
        database to ``readers`` alone, ``setting`` naming them in an
        error. A reader opens it with :meth:`read_server`. A server
        that is away is kept so by ``clock`` in seconds: every call fails
        at once with ``StateUnavailableError`` until the next attempt is
        due."""
        name = f"{server.database}/{server.schema_name}"
        place = server_place.ServerPlace(server, SHAPE, clock, make_schema=True)
        try:
            with _named(name):
                db = database.Database(SHAPE, place=place)
        except BaseException:
            place.close()
            raise
        lock = ExitStack()
        rights = None
        try:
            with _named(name):
                lock.enter_context(db.serving())
                rights = place.secured(readers, setting)
        except BaseException:
            lock.close()
            db.close()
            raise
        store = cls(db, False, lock, name)
        store.rights = rights
        return store

    @classmethod
    def read_server(cls, server: server_place.Server) -> Store | None:
        """The state in the schema of the role of ``server`` for a reader
        beside the running agent, at the schema of this version. None
        while it holds nothing: no agent has started on it yet."""
        name = f"{server.database}/{server.schema_name}"
        place = server_place.ServerPlace(server, SHAPE, read_only=True)
        try:
            with _named(name):
                place.open(SHAPE.newest, SHAPE.newest)
                held = place.held_schema()
                if not held:
                    place.close()
                    return None
                _at_this_schema(held)
                db = database.Database(SHAPE, place=place)
        except BaseException:
            place.close()
            raise
        return cls(db, True, None, name)

    def close(self) -> None:
        # The lock first: on a server it is let go on the connection.
        if self._lock is not None:
            _unlock(self._lock)
            self._lock = None
        self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    # -- cursor and passes --------------------------------------------------------

    def cursor(self) -> str | None:
        with self._conn() as conn:
            found: str | None = conn.execute(
                sa.select(cursor.c.state).where(cursor.c.id == 1)
            ).scalar()
        return found

    def set_cursor(self, state: str, now: datetime) -> None:
        with self._conn() as conn:
            conn.execute(
                dialect.insert_or_update(cursor, ["id"], None, conn.dialect).values(
                    id=1, state=state, updated=_text(now)
                )
            )

    def progress(self) -> datetime | None:
        """When the loop last showed progress: after a message it ran, a
        pass it finished, or a slice of a wait. The health check reads it."""
        with self._conn() as conn:
            found = conn.execute(
                sa.select(passes.c.finished).where(passes.c.id == 1)
            ).scalar()
        return _time(found)

    def set_progress(self, now: datetime) -> None:
        """Note progress of the loop at ``now``. The table and its column
        keep the names of migration 1."""
        with self._conn() as conn:
            conn.execute(
                dialect.insert_or_update(passes, ["id"], None, conn.dialect).values(
                    id=1, finished=_text(now)
                )
            )
