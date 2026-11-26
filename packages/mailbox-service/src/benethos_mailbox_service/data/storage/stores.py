"""The stores a tool opens on its own, outside a running service: a
backup, a restore, a move. Which place a database lies in, and how a
tool takes the lock a running service holds, is decided here, so the
tools name neither ``Database`` nor a place.

A file is locked by the lock file beside it, a schema on a server by
the locks of its session (``ServerPlace.claimed``). Either refuses with
``StorageInUseError`` while a service runs on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from benethos_mailbox_common.paths import locks

from ...errors import (
    MailboxServiceError,
    SchemaNotEmptyError,
    StorageError,
    StorageInUseError,
)
from .sql.database import Database
from .sql.revisions import SCHEMA_VERSION
from .sql.server_place import Server, ServerPlace
from .sqlite.file import service_lock

# Where an operator reads how to set a schema that holds tables aside.
SET_ASIDE = (
    "https://github.com/benethos-hub/mailbox/blob/main/containers/production/"
    "mailbox-service/README.md#set-a-schema-aside"
)


def file_store(
    path: Path | None = None, *, schema: int | None = None, keep_copy: bool = True
) -> Database:
    """The database in the file at ``path``, in memory without one.
    ``schema``: a new database made at that schema and migrated no
    further, to take the records of an export. ``keep_copy``: a file of
    an older schema is copied before it is migrated."""
    return Database(path, schema=schema, keep_copy=keep_copy)


def migrate_file(path: Path) -> None:
    """Bring the database file at ``path`` to this version's schema, by
    the old steps and the revisions. It comes from a backup, which is its
    copy: none is kept beside it."""
    file_store(path, keep_copy=False).close()


@contextmanager
def file_claimed(path: Path) -> Iterator[None]:
    """The lock a running service holds beside the file at ``path``, for
    a tool, for the time of the block."""
    try:
        with locks.exclusive_lock(service_lock(path)):
            yield
    except locks.LockedError:
        raise StorageInUseError(
            "the service is running on this database: stop it first"
        ) from None


class Claim:
    """A schema on a server a tool holds alone, with the locks a running
    service takes. A database opened on it closes with the claim."""

    def __init__(self, server: Server, place: ServerPlace) -> None:
        self._server = server
        self._place = place

    def tables(self) -> list[str]:
        """The tables of the schema, before a database on it is opened."""
        return self._place.tables()

    def held_schema(self) -> int:
        """The schema the database says it is in, 0 without one."""
        return self._place.held_schema()

    def store(self, schema: int | None = None) -> Database:
        """The database in the schema, made at ``schema`` when it is new,
        else at this version's."""
        return Database(place=self._place, schema=schema)

    def drop_tables(self) -> None:
        """Every table of the schema dropped, the schema kept: what a
        restore made, when it fails. When that fails too, the error says
        how to set the schema aside."""
        try:
            self._place.drop_tables()
        except MailboxServiceError:
            raise StorageError(
                "Tables of the restore may be left: how to set the schema"
                f" aside: {SET_ASIDE}"
            ) from None


@contextmanager
def claimed(
    server: Server, *, schema: int = SCHEMA_VERSION, empty: str | None = None
) -> Iterator[Claim]:
    """The schema of ``server``, connected alone, without a revision, and
    the locks a running service takes on it. ``empty``: what goes into
    the schema, which then must hold no table yet, else
    SchemaNotEmptyError says how to set it aside. ``schema``: the one a
    new database there is made at."""
    with ExitStack() as held:
        place = ServerPlace(server)
        held.callback(place.close)
        place.open(schema, SCHEMA_VERSION)
        held.enter_context(place.claimed())
        claim = Claim(server, place)
        if empty is not None and claim.tables():
            raise SchemaNotEmptyError(
                f"the schema {server.schema_name} holds tables: {empty} goes into"
                f" an empty schema only. How to set the old one aside: {SET_ASIDE}"
            )
        yield claim
