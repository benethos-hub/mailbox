"""Where a database lies: what ``Database`` needs of it beyond SQLAlchemy.
The file of SQLite is one place (``file_place``). Everything else of the
database, its transactions, the revisions of its schema and the rows of
an export, is SQLAlchemy's and the same on every place."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import threading

    import sqlalchemy as sa

    from ..migrated import Migrated


class Place(Protocol):
    """A database the service opens once and keeps open."""

    def open(self, schema: int, newest: int) -> tuple[sa.Connection, Migrated | None]:
        """The one connection of the process. A place with steps of its
        own before the revisions brings the schema by them towards
        ``schema``, and says what it did, None when nothing. ``newest``:
        the schema of this version, a database beyond it is refused."""
        ...

    def undo(self) -> None:
        """No transaction left open after one failed, also not after a
        failed COMMIT. Raises nothing."""
        ...

    def keep_copy(self, held: int, before: int) -> str | None:
        """A copy of the database at schema ``held`` before the revision
        ``before`` changes it. Its name, None when the place keeps none."""
        ...

    def shrink(self) -> None:
        """Give back what deletions freed. Called outside a transaction."""
        ...

    def serving(self) -> AbstractContextManager[bool]:
        """Mark the database as used by a running service while the block
        runs. False when another service marked it already."""
        ...

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        """A consistent copy of the whole database as a file, readable by
        its owner alone, gone when the block ends. ``lock`` keeps the
        connection for the time it takes."""
        ...

    def translated(self) -> AbstractContextManager[None]:
        """The failures of the database as this project's errors: a
        constraint as ConflictError, anything else as StorageError,
        never with a value of a row."""
        ...

    def close(self) -> None: ...
