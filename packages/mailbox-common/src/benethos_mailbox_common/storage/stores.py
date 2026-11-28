"""The stores a tool opens on its own, outside a running program: a
backup, a restore, a move. Which place a database lies in, and how a
tool takes the lock a running program holds, is decided here, so the
tools name neither ``Database`` nor a place.

A file is locked by the lock file beside it, a schema on a server by
the locks of its session (``ServerPlace.claimed``). Either refuses with
the error of a database in use while a program runs on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import locks, sqlite_file
from .database import Database
from .errors import ConflictError, StorageError
from .server_place import Server, ServerPlace
from .shape import Shape


def file_store(
    shape: Shape,
    path: Path | None = None,
    *,
    schema: int | None = None,
    keep_copy: bool = True,
) -> Database:
    """The database of ``shape`` in the file at ``path``, in memory
    without one. ``schema``: a new database made at that schema and
    migrated no further, to take the records of an export. ``keep_copy``:
    a file of an older schema is copied before it is migrated."""
    return Database(shape, path, schema=schema, keep_copy=keep_copy)


def migrate_file(shape: Shape, path: Path) -> None:
    """Bring the database file at ``path`` to this version's schema, by
    the steps of its file and the revisions. It comes from a backup,
    which is its copy: none is kept beside it."""
    file_store(shape, path, keep_copy=False).close()


@contextmanager
def file_claimed(shape: Shape, path: Path) -> Iterator[None]:
    """The lock a running program of ``shape`` holds beside the file
    at ``path``, for a tool, for the time of the block."""
    try:
        with locks.exclusive_lock(sqlite_file.lock_file(path)):
            yield
    except locks.LockedError:
        raise shape.errors.in_use(
            f"the {shape.noun} is running on this database: stop it first"
        ) from None


class Claim:
    """A schema on a server a tool holds alone, with the locks a running
    program takes. A database opened on it closes with the claim."""

    def __init__(self, server: Server, place: ServerPlace, shape: Shape) -> None:
        self._server = server
        self._place = place
        self._shape = shape

    def tables(self) -> list[str]:
        """The tables of the schema, before a database on it is opened."""
        return self._place.tables()

    def held_schema(self) -> int:
        """The schema the database says it is in, 0 without one."""
        return self._place.held_schema()

    def store(self, schema: int | None = None) -> Database:
        """The database in the schema, made at ``schema`` when it is new,
        else at this version's."""
        return Database(self._shape, place=self._place, schema=schema)

    def drop_tables(self) -> None:
        """Every table of the schema dropped, the schema kept: what a
        restore made, when it fails. When that fails too, the error says
        how to set the schema aside."""
        try:
            self._place.drop_tables()
        except (StorageError, ConflictError):
            raise self._shape.errors.failed(
                "Tables of the restore may be left: how to set the schema"
                f" aside: {self._shape.set_aside}"
            ) from None


@contextmanager
def claimed(
    shape: Shape,
    server: Server,
    *,
    schema: int | None = None,
    empty: str | None = None,
) -> Iterator[Claim]:
    """The schema of ``server``, connected alone, without a revision, and
    the locks a running program takes on it. ``empty``: what goes into
    the schema, which then must hold no table yet, else the error of a
    schema not empty says how to set it aside. ``schema``: the one a new
    database there is made at, this version's without."""
    with ExitStack() as held:
        place = ServerPlace(server, shape)
        held.callback(place.close)
        place.open(shape.newest if schema is None else schema, shape.newest)
        held.enter_context(place.claimed())
        claim = Claim(server, place, shape)
        if empty is not None and claim.tables():
            raise shape.errors.not_empty(
                f"the schema {server.schema_name} holds tables: {empty} goes into"
                " an empty schema only. How to set the old one aside:"
                f" {shape.set_aside}"
            )
        yield claim
