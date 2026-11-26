"""A database server as the place of a database: one schema of it, owned
by the role the service signs in as, reached through SQLAlchemy alone.

The schema begins at 26, where the revisions begin: the old steps of
SQLite have no counterpart here. There is no file, so no copy before a
revision, no shrinking and no snapshot of a file. A view of one moment
is a second connection in one transaction of REPEATABLE READ, which
reads a fixed state and holds no writer up.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from ....errors import StorageError
from ..migrated import Migrated
from . import revisions
from .dialect import reading_fixed, server_engine
from .place import translated_by

# A name the server takes without quoting, so it can stand in the
# search path the connection sets.
_PLAIN_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
# The oldest server the service runs on (2026-11-25), as the server
# writes its version as a number: major * 10000 + minor.
OLDEST_SERVER = 190000


@dataclass(frozen=True, slots=True)
class Server:
    """Where the database is and who the service is there. ``schema``
    is named after ``role`` unless given."""

    host: str
    port: int
    database: str
    role: str
    password: str
    schema: str | None = None

    @property
    def schema_name(self) -> str:
        return self.role if self.schema is None else self.schema

    def __repr__(self) -> str:
        # Never the password, also not in a traceback.
        return (
            f"Server({self.host}:{self.port}/{self.database},"
            f" role {self.role}, schema {self.schema_name})"
        )


class ServerPlace:
    """The schema ``server`` names, on the server it names."""

    def __init__(self, server: Server) -> None:
        if not _PLAIN_NAME.fullmatch(server.schema_name):
            raise StorageError(
                "the schema of the database is not a plain name:"
                " lower case letters, digits and underscores"
            )
        self._server = server
        self._engine: sa.Engine | None = None
        self._connection: sa.Connection | None = None

    def open(self, schema: int, newest: int) -> tuple[sa.Connection, Migrated | None]:
        if schema < revisions.BASELINE:
            raise StorageError(
                f"a database on a server begins at schema {revisions.BASELINE},"
                f" not {schema}"
            )
        self._engine = self._engine_of()
        with translated():
            self._connection = self._engine.connect()
            version = self._connection.execute(
                sa.select(sa.func.current_setting("server_version_num"))
            ).scalar()
            self._connection.rollback()
        supported(int(str(version)))
        return self._connection, None

    def _engine_of(self) -> sa.Engine:
        server = self._server
        engine = server_engine(
            host=server.host,
            port=server.port,
            database=server.database,
            role=server.role,
            password=server.password,
            search_path=server.schema_name,
        )
        sa.event.listen(engine, "handle_error", _not_of_the_driver)
        return engine

    def undo(self) -> None:
        with suppress(Exception):
            if self._connection is not None:
                self._connection.connection.driver_connection.rollback()  # type: ignore[union-attr]

    def keep_copy(self, held: int, before: int) -> str | None:
        raise StorageError(
            f"the revision {before} asks for a copy of the database first,"
            " which a database on a server does not keep: back it up, then"
            " migrate it with a version that does"
        )

    def shrink(self) -> None:
        """The server gives back what deletions freed by itself."""

    def serving(self) -> AbstractContextManager[bool]:
        return nullcontext(True)

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        raise StorageError("a database on a server has no file")

    @contextmanager
    def fixed(self, lock: threading.RLock) -> Iterator[sa.Connection]:
        """A connection of its own, reading in one transaction of
        REPEATABLE READ."""
        if self._engine is None:
            raise StorageError("the database is not open")
        with translated():
            conn = reading_fixed(self._engine.connect())
        with conn, conn.begin():
            yield conn

    def translated(self) -> AbstractContextManager[None]:
        return translated()

    def close(self) -> None:
        with suppress(Exception):
            if self._connection is not None:
                self._connection.close()
        if self._engine is not None:
            self._engine.dispose()


def translated() -> AbstractContextManager[None]:
    """The failures of the database as this project's errors. The server's
    text of a violated key quotes the key and the first line of other
    failures can quote a value: of a conflict only the first line of the
    server, which names the constraint, of anything else only its kind."""
    return translated_by(_first_line, _kind)


def _first_line(exc: BaseException | None) -> str:
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None)
    return primary if isinstance(primary, str) else _kind(exc)


def _kind(exc: BaseException | None) -> str:
    """The class of the failure and the code of five characters the
    server gives it, which names what went wrong and nothing it read."""
    code = getattr(exc, "sqlstate", None)
    kind = type(exc).__name__
    return f"{kind} ({code})" if isinstance(code, str) else kind


def _not_of_the_driver(context: sa.engine.ExceptionContext) -> BaseException | None:
    """A failure while a statement runs that is no error of the driver,
    such as a value the driver cannot bind, named by its kind alone:
    its text can hold the value."""
    if context.sqlalchemy_exception is None and isinstance(
        context.original_exception, Exception
    ):
        return StorageError(
            f"the database failed: {type(context.original_exception).__name__}"
        )
    return None


def supported(version: int) -> None:
    """Refuse a server older than ``OLDEST_SERVER``, by the number it
    gives as ``server_version_num``."""
    if version < OLDEST_SERVER:
        raise StorageError(
            f"the database server is PostgreSQL {_shown(version)}:"
            f" this version needs PostgreSQL {_shown(OLDEST_SERVER)} or newer"
        )


def _shown(version: int) -> str:
    major, minor = divmod(version, 10000)
    return f"{major}.{minor}"
