"""The state file opened to read alone, beside the writer, by ``report``,
``status``, ``health`` and the cockpit: a place of the storage of
mailbox-common that takes no lock, runs no step and writes nothing.

It reads a file of this version's schema only. One of a newer schema is
refused, and so is one of an older schema: the writer brings it forward
when the agent starts.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext, suppress
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from benethos_mailbox_common.storage import errors as storage_errors
from benethos_mailbox_common.storage import file_place, outage, place, sqlite_file

from ..errors import STATE_ERRORS, ConfigError
from .file import newer


def connect_reading(path: Path) -> sqlite3.Connection:
    """A connection that reads the file at ``path`` and never writes it.

    A reader in a folder it may not write, such as the volume of a
    stopped agent mounted read-only, cannot make the ``-shm`` file a
    file in WAL mode wants once the writer closed it cleanly and took
    ``-wal`` and ``-shm`` away. Then, and only while no ``-wal`` lies
    beside the file, it opens the file as immutable: SQLite takes no
    lock and reads no WAL. Should the writer start in that moment, a
    read may see an earlier state or fail. The file is never changed.
    """
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        connection = _read_only(uri)
        try:
            connection.execute("PRAGMA user_version").fetchone()
        except sqlite3.Error:
            connection.close()
            raise
        return connection
    except sqlite3.OperationalError:
        if path.with_name(path.name + "-wal").exists():
            raise
    return _read_only(f"{uri}&immutable=1")


def _read_only(uri: str) -> sqlite3.Connection:
    return sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)


def _schema_of(connection: sqlite3.Connection) -> int:
    """The schema the file is at: in ``meta`` from schema 5 on, before in
    its ``user_version``."""
    errors = STATE_ERRORS
    if sqlite_file.has_meta(connection, errors):
        return sqlite_file.schema_version(connection, errors)
    with sqlite_file.translated_sqlite(errors):
        found: int = connection.execute("PRAGMA user_version").fetchone()[0]
    return found


class ReadPlace:
    """The state file at ``path``, read alone."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._driver: sqlite3.Connection | None = None
        self._engine: sa.Engine | None = None

    def open(self, schema: int, newest: int) -> place.Opened:
        if not self.path.is_file():
            raise ConfigError(f"no state file {self.path.name}")
        with sqlite_file.translated_sqlite(STATE_ERRORS):
            driver = connect_reading(self.path)
        self._driver = driver
        with sqlite_file.translated_sqlite(STATE_ERRORS):
            driver.execute("PRAGMA busy_timeout = 5000")
        held = _schema_of(driver)
        if held > newest:
            raise newer(held, newest)
        if held < newest:
            raise ConfigError(
                f"the state file is at schema version {held}, this program reads"
                f" {newest}: start the agent once, which brings it forward"
            )
        # A plain BEGIN: a reader asks for no lock to write.
        self._engine = sa.create_engine(
            "sqlite://",
            creator=lambda: driver,
            poolclass=StaticPool,
            hide_parameters=True,
        )
        return place.Opened(self._engine.connect(), None)

    def undo(self) -> None:
        with suppress(Exception):
            if self._driver is not None and self._driver.in_transaction:
                self._driver.rollback()

    def keep_copy(self, held: int, before: int) -> str | None:
        return None

    def shrink(self) -> None:
        """A reader gives nothing back."""

    def serving(self) -> AbstractContextManager[bool]:
        return nullcontext(False)

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        raise STATE_ERRORS.failed("a reader of the state file makes no snapshot")

    def fixed(self, lock: threading.RLock) -> AbstractContextManager[sa.Connection]:
        raise STATE_ERRORS.failed("a reader of the state file holds no view")

    def ready(self) -> None:
        """A file is there or fails on the call itself."""

    def watch(self, report: Callable[[outage.Availability], None]) -> None:
        """A file is not away and back."""

    def unavailable(self) -> storage_errors.StorageUnavailableError | None:
        return None

    def translated(self) -> AbstractContextManager[None]:
        return file_place.translated_file(STATE_ERRORS)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        if self._driver is not None:
            self._driver.close()
