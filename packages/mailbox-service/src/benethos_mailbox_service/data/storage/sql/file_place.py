"""The file of SQLite as the place of a database: the one module under
``sql/`` that reaches into ``sqlite/``, where the file, its connection,
the old steps of its schema up to 26 and the files beside it live."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from benethos_mailbox_common.storage import dialect

from ....errors import StorageError, StorageUnavailableError
from ..sqlite import file
from .outage import Availability
from .place import Opened, translated_by


class FilePlace:
    """The database in the file at ``path``, readable by its owner alone,
    in memory without one. ``keep_copy``: a file of an older schema is
    copied before a step that asks for it."""

    def __init__(self, path: Path | None, *, keep_copy: bool = True) -> None:
        self.path = path
        self._keep_copy = keep_copy
        self._driver: file.Driver | None = None
        self._engine: sa.Engine | None = None
        self._newest = 0

    def open(self, schema: int, newest: int) -> Opened:
        self._newest = newest
        driver, migrated = file.open_file(
            self.path, keep_copy=self._keep_copy, schema=schema, newest=newest
        )
        self._driver = driver
        self._engine = sqlite_engine(lambda: driver)
        return Opened(self._engine.connect(), migrated)

    def undo(self) -> None:
        with suppress(Exception):
            if self._driver is not None and self._driver.in_transaction:
                self._driver.rollback()

    def keep_copy(self, held: int, before: int) -> str | None:
        if not self._keep_copy or self.path is None or self._driver is None:
            return None
        return file.keep_copy(self._driver, self.path, held, before)

    def shrink(self) -> None:
        if self._driver is not None:
            file.shrink(self._driver)

    def serving(self) -> AbstractContextManager[bool]:
        return file.serving(self.path)

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        if self._driver is None:
            raise StorageError("the database is not open")
        return file.snapshot(self._driver, self.path, lock)

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
                conn = snap.open(self._newest, self._newest).connection
                with conn, conn.begin():
                    yield conn
            finally:
                snap.close()

    def ready(self) -> None:
        """A file is there or fails on the call itself."""

    def watch(self, report: Callable[[Availability], None]) -> None:
        """A file is not away and back."""

    def unavailable(self) -> StorageUnavailableError | None:
        return None

    def translated(self) -> AbstractContextManager[None]:
        return translated()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        if self._driver is not None:
            self._driver.close()


@contextmanager
def translated() -> Iterator[None]:
    """The failures of the database as this project's errors, with the
    text of the driver, which names a table and a column, never a value.
    The driver's own errors, from the connection used directly, are
    translated by ``file``."""
    with translated_by(str, str), file.translated():
        yield


def sqlite_engine(connect: Callable[[], Any]) -> sa.Engine:
    """An engine on the one SQLite connection ``connect`` gives, for the
    whole process. A transaction begins as ``dialect.begin_at_once`` says. No value of a
    statement reaches the text of an error."""
    engine = sa.create_engine(
        f"{dialect.SQLITE}://",
        creator=connect,
        poolclass=StaticPool,
        hide_parameters=True,
    )
    sa.event.listen(engine, "begin", dialect.begin_at_once)
    return engine
