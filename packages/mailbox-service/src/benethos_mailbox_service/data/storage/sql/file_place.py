"""The file of SQLite as the place of a database: the one module under
``sql/`` that reaches into ``sqlite/``, where the file, its connection,
the old steps of its schema up to 26 and the files beside it live."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path

import sqlalchemy as sa

from ....errors import ConflictError, StorageError
from ..migrated import Migrated
from ..sqlite import file
from .dialect import sqlite_engine


class FilePlace:
    """The database in the file at ``path``, readable by its owner alone,
    in memory without one. ``keep_copy``: a file of an older schema is
    copied before a step that asks for it."""

    def __init__(self, path: Path | None, *, keep_copy: bool = True) -> None:
        self.path = path
        self._keep_copy = keep_copy
        self.driver: file.Driver | None = None
        self._engine: sa.Engine | None = None
        self._newest = 0

    def open(self, schema: int, newest: int) -> tuple[sa.Connection, Migrated | None]:
        self._newest = newest
        driver, migrated = file.open_file(
            self.path, keep_copy=self._keep_copy, schema=schema, newest=newest
        )
        self.driver = driver
        self._engine = sqlite_engine(lambda: driver)
        return self._engine.connect(), migrated

    def undo(self) -> None:
        with suppress(Exception):
            if self.driver is not None and self.driver.in_transaction:
                self.driver.rollback()

    def keep_copy(self, held: int, before: int) -> str | None:
        if not self._keep_copy or self.path is None or self.driver is None:
            return None
        return file.keep_copy(self.driver, self.path, held, before)

    def shrink(self) -> None:
        if self.driver is not None:
            file.shrink(self.driver)

    def serving(self) -> AbstractContextManager[bool]:
        return file.serving(self.path)

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        if self.driver is None:
            raise StorageError("the database is not open")
        return file.snapshot(self.driver, self.path, lock)

    @contextmanager
    def fixed(self, lock: threading.RLock) -> Iterator[sa.Connection]:
        """The snapshot of the file, checked whole, opened on its own."""
        with self.snapshot_file(lock) as snapshot:
            try:
                file.inspect_file(snapshot)
            except ValueError as exc:
                raise StorageError(
                    f"the copy of the database is unsound: {exc}"
                ) from None
            snap = FilePlace(snapshot, keep_copy=False)
            try:
                conn, _ = snap.open(self._newest, self._newest)
                with conn, conn.begin():
                    yield conn
            finally:
                snap.close()

    def translated(self) -> AbstractContextManager[None]:
        return translated()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        if self.driver is not None:
            self.driver.close()


@contextmanager
def translated() -> Iterator[None]:
    """The failures of the database as this project's errors, with the
    text of the driver, which names a table and a column, never a value:
    the one of SQLAlchemy holds the statement and its values. A failure
    SQLAlchemy raises before the driver is named by its kind alone. The
    driver's own errors, from the connection used directly, are
    translated by ``file``."""
    try:
        with file.translated():
            yield
    except sa.exc.IntegrityError as exc:
        raise ConflictError(f"conflicts with a stored record: {exc.orig}") from None
    except sa.exc.DBAPIError as exc:
        raise StorageError(f"the database failed: {exc.orig}") from None
    except sa.exc.SQLAlchemyError as exc:
        # Refused before the driver saw it, such as a value that does not
        # fit its column. Its text, and the one of its cause, can hold the
        # statement and the value: only the kind is named.
        cause = getattr(exc, "orig", None) or exc
        raise StorageError(f"the database failed: {type(cause).__name__}") from None
