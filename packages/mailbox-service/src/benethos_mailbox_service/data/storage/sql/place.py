"""Where a database lies: what ``Database`` needs of it beyond SQLAlchemy.
The file of SQLite is one place (``file_place``), a schema on a
PostgreSQL server another (``server_place``). Everything else of the
database, its transactions, the revisions of its schema and the rows of
an export, is SQLAlchemy's and the same on every place."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import sqlalchemy as sa

from ....errors import ConflictError, StorageError, StorageUnavailableError

if TYPE_CHECKING:
    import threading

    from benethos_mailbox_common.storage import migrated

    from .outage import Availability


@dataclass(frozen=True, slots=True)
class Opened:
    """What opening a place gives: its one connection, and what its own
    steps did to the schema, None when nothing."""

    connection: sa.Connection
    migrated: migrated.Migrated | None


class Place(Protocol):
    """A database the service opens once and keeps open."""

    def open(self, schema: int, newest: int) -> Opened:
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
        runs. A file yields False when another service marked it
        already, a server raises StorageInUseError."""
        ...

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        """A consistent copy of the whole database as a file, readable by
        its owner alone, gone when the block ends. ``lock`` keeps the
        connection for the time it takes."""
        ...

    def fixed(self, lock: threading.RLock) -> AbstractContextManager[sa.Connection]:
        """A connection in one transaction on the records at one moment,
        taken while the database is in use, for the time of the block."""
        ...

    def ready(self) -> None:
        """Before each call: raises at once when the database is known
        to be away, else lets the call go to it."""
        ...

    def watch(self, report: Callable[[Availability], None]) -> None:
        """``report`` hears of each change of whether the database can
        be reached, beside those that heard before."""
        ...

    def unavailable(self) -> StorageUnavailableError | None:
        """The error a call meets now, without asking the database: None
        unless it is known to be away."""
        ...

    def translated(self) -> AbstractContextManager[None]:
        """The failures of the database as this project's errors: a
        constraint as ConflictError, anything else as StorageError,
        never with a value of a row."""
        ...

    def close(self) -> None: ...


@contextmanager
def translated_by(
    conflict: Callable[[BaseException | None], str],
    failure: Callable[[BaseException | None], str],
) -> Iterator[None]:
    """The failures SQLAlchemy raises as this project's errors: a
    constraint as ConflictError, named as ``conflict`` gives what the
    driver said, anything else as StorageError, named as ``failure``
    gives it. Never the text of SQLAlchemy, which holds the statement
    and its values. A failure SQLAlchemy raises before the driver is
    named by its kind alone."""
    try:
        yield
    except sa.exc.IntegrityError as exc:
        raise ConflictError(
            f"conflicts with a stored record: {conflict(exc.orig)}"
        ) from None
    except sa.exc.DBAPIError as exc:
        raise StorageError(f"the database failed: {failure(exc.orig)}") from None
    except sa.exc.SQLAlchemyError as exc:
        # Refused before the driver saw it, such as a value that does not
        # fit its column. Its text, and the one of its cause, can hold the
        # statement and the value: only the kind is named.
        cause = getattr(exc, "orig", None) or exc
        raise StorageError(f"the database failed: {type(cause).__name__}") from None
