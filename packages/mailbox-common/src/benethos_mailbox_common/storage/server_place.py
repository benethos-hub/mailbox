"""A database server as the place of a database: one schema of it, owned
by the role the program signs in as, reached through SQLAlchemy alone.

The schema begins at the baseline of the shape, where the revisions
begin: the steps of a file of SQLite have no counterpart here. There is
no file, so no copy before a revision, no shrinking and no snapshot of
a file. A view of one moment is a second connection in one transaction
of REPEATABLE READ, which reads a fixed state and holds no writer up.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path

import sqlalchemy as sa

from . import dialect, names, server_lock, server_rights, tables
from .errors import Errors, StorageUnavailableError
from .outage import LOCK_GRACE, LONGEST_PAUSE, Availability, Outage
from .place import Opened, translated_by
from .server_engine import Server, engine_for
from .shape import Shape

# The oldest server the programs of Mailbox run on (2026-11-25), as the
# server writes its version as a number: major * 10000 + minor.
OLDEST_SERVER = 190000


# A call before the place was opened, or after it was closed.
NOT_OPEN = "the database is not open"


class ServerPlace:
    """The schema ``server`` names, on the server it names, for the
    database of ``shape``. A server that is away is kept so: every call
    fails at once until the next attempt is due, by ``clock`` in seconds
    (``outage``). With ``read_only`` every transaction only reads."""

    def __init__(
        self,
        server: Server,
        shape: Shape,
        clock: Callable[[], float] = time.monotonic,
        *,
        make_schema: bool = False,
        read_only: bool = False,
    ) -> None:
        if not names.is_plain_name(server.schema_name):
            raise shape.errors.failed(
                "the schema of the database is not a plain name:"
                " lower case letters, digits and underscores"
            )
        self._server = server
        self._shape = shape
        # The schema made at open where it is missing and the role may.
        self._make_schema = make_schema
        # Every transaction only reads: a reader beside a running program.
        self._read_only = read_only
        self._errors = shape.errors
        self._engine: sa.Engine | None = None
        self._connection: sa.Connection | None = None
        self._outage = Outage(clock, shape.errors)
        self._reports: list[Callable[[Availability], None]] = []
        # The keys of the locks this session holds, taken again on a
        # new session.
        self._held: tuple[int, ...] = ()
        # Set for good when another program took the lock while the
        # server was away: this one only ends from then on.
        self._taken = False

    def open(self, schema: int, newest: int) -> Opened:
        """The one connection, made at the first call. A later call, of a
        second database on the same place, hands it on as it is."""
        if self._connection is not None:
            return Opened(self._connection, None)
        if schema < self._shape.baseline:
            raise self._errors.failed(
                f"a database on a server begins at schema {self._shape.baseline},"
                f" not {schema}"
            )
        self._engine = self._engine_of()
        with self.translated():
            self._connection = self._engine.connect()
            version = self._connection.execute(
                sa.select(sa.func.current_setting("server_version_num"))
            ).scalar()
            self._connection.rollback()
        supported(int(str(version)), self._errors)
        if self._make_schema:
            with self.translated():
                server_rights.own_schema(
                    self._connection, self._server.schema_name, self._errors
                )
        return Opened(self._connection, None)

    def close_to_others(self) -> bool:
        """The database closed to every other role, where the role of the
        program owns it: whether it is closed now."""
        connection = self._open()
        with self.translated():
            return server_rights.close_database(connection)

    def secured(self, readers: Sequence[str], setting: str) -> server_rights.Rights:
        """The database closed to every other role and given to
        ``readers`` to read, as ``server_rights.secure`` says. ``setting``
        names the readers in an error."""
        connection = self._open()
        with self.translated():
            return server_rights.secure(
                connection,
                self._server.schema_name,
                readers,
                self._errors,
                setting=setting,
            )

    def _engine_of(self) -> sa.Engine:
        engine = engine_for(self._server, self._shape, read_only=self._read_only)
        sa.event.listen(
            engine,
            "handle_error",
            functools.partial(_not_of_the_driver, self._errors),
        )
        return engine

    def undo(self) -> None:
        """The transaction of the driver rolled back. A connection that
        is lost is left alone: asking it for its driver would connect
        again, outside ``ready``."""
        connection = self._connection
        if connection is None or connection.invalidated:
            return
        with suppress(Exception):
            driver = connection.connection.driver_connection
            if driver is not None:
                driver.rollback()

    def keep_copy(self, held: int, before: int) -> str | None:
        raise self._errors.failed(
            f"the revision {before} asks for a copy of the database first,"
            " which a database on a server does not keep: back it up, then"
            " migrate it with a version that does"
        )

    def shrink(self) -> None:
        """The server gives back what deletions freed by itself."""

    @contextmanager
    def serving(self) -> Iterator[bool]:
        """Two programs on one schema would lose changes, so the second
        is refused: the lock of the session on its one
        connection, held until the block ends or the connection closes.
        Its key is a random number the schema keeps in ``meta``, so a
        role that cannot connect to the database cannot take the lock
        ahead. One that can sees the key in ``pg_locks`` while it is
        held. A schema without a key gets one, made under the lock
        keyed by the names of the program and the schema, which a restore
        or a move into the empty schema holds (``claimed``)."""
        connection = self._open()
        with self.translated():
            key = self._program_key(connection)
        self._held = (key,)
        try:
            yield True
        finally:
            self._let_go(connection)

    def _program_key(self, connection: sa.Connection) -> int:
        """The key the schema keeps, its lock taken. Made first when
        there is none, under the lock keyed by the name."""
        key = server_lock.kept_key(connection, self._shape)
        if key is not None:
            self._take(connection, key)
            return key
        named = self._named_key()
        self._take(connection, named)
        try:
            key = server_lock.kept_key(connection, self._shape)
            if key is None:
                key = server_lock.drawn_key()
                connection.execute(
                    sa.insert(self._shape.meta).values(
                        key=tables.LOCK_ROW, value=str(key)
                    )
                )
                connection.commit()
            self._take(connection, key)
        finally:
            server_lock.unlocked(connection, named)
        return key

    def _named_key(self) -> int:
        return server_lock.lock_key(self._shape.program, self._server.schema_name)

    @contextmanager
    def claimed(self) -> Iterator[None]:
        """The schema for a restore or a move, which works on it alone:
        the lock keyed by its name, under which a program makes its key,
        and the lock of a running program where the schema keeps a key.
        Writes nothing. Refused while a program runs on the schema."""
        connection = self._open()
        named = self._named_key()
        with self.translated():
            self._take(connection, named)
            self._held = (named,)
            try:
                key = server_lock.kept_key(connection, self._shape)
                if key is not None:
                    self._take(connection, key)
                    self._held = (named, key)
            except BaseException:
                self._let_go(connection)
                raise
        try:
            yield
        finally:
            self._let_go(connection)

    def _open(self) -> sa.Connection:
        """The one connection, or the error of a place not opened."""
        if self._connection is None:
            raise self._errors.failed(NOT_OPEN)
        return self._connection

    def _engine_open(self) -> sa.Engine:
        """The engine, or the error of a place not opened."""
        if self._engine is None:
            raise self._errors.failed(NOT_OPEN)
        return self._engine

    def _take(self, connection: sa.Connection, key: int) -> None:
        if not self._locked(connection, key):
            noun = self._shape.noun
            raise self._errors.in_use(
                f"another {noun} runs on this database: one {noun} per"
                " schema of a database server"
            )

    def _let_go(self, connection: sa.Connection) -> None:
        held, self._held = self._held, ()
        with suppress(Exception), self.translated():
            for key in held:
                server_lock.unlocked(connection, key)

    @staticmethod
    def _locked(connection: sa.Connection, key: int) -> bool:
        """Whether the lock of the session ``key`` is taken now, by this
        session."""
        got = connection.execute(sa.select(sa.func.pg_try_advisory_lock(key))).scalar()
        connection.commit()
        return bool(got)

    def ready(self) -> None:
        """Before each call: at once a StorageUnavailableError while the
        server is away and the pause runs. When it is over, one attempt
        on a new session, as the first was: its search path from the
        connecting, the lock of a running program taken again. A lock
        held by another session counts as the server still away for a
        minute since it went, as the old session of this program may
        still hold it. Past that another program took it, and every
        call fails."""
        if self._taken:
            raise self._errors.failed(self._taken_text())
        if not self._outage.away:
            return
        if not self._outage.due():
            raise self._outage.unavailable()
        connection = self._open()
        try:
            with suppress(sa.exc.SQLAlchemyError):
                connection.rollback()
            connection.execute(sa.select(sa.literal(1)))
            connection.commit()
            got = all(self._locked(connection, key) for key in self._held)
        except sa.exc.DBAPIError as exc:
            self._failed(exc)
            raise self._outage.unavailable() from None
        if not got and self._outage.away_for() < LOCK_GRACE:
            # The new session lets go of what it took, so the next
            # attempt starts from nothing.
            with suppress(sa.exc.SQLAlchemyError):
                connection.invalidate()
            self._outage.failed("lock held")
            raise self._outage.unavailable()
        seconds = self._outage.mended() or 0.0
        self._taken = not got
        self._said(Availability(away=False, seconds=seconds, lock_lost=not got))
        if not got:
            raise self._errors.failed(self._taken_text())

    def _taken_text(self) -> str:
        return f"another {self._shape.noun} took this database while it was away"

    def watch(self, report: Callable[[Availability], None]) -> None:
        self._reports.append(report)

    def unavailable(self) -> StorageUnavailableError | None:
        if self._taken:
            return self._errors.unavailable(int(LONGEST_PAUSE), "lock taken")
        return self._outage.unavailable() if self._outage.away else None

    def _failed(self, exc: sa.exc.DBAPIError) -> None:
        cause = _failure_of(exc.orig)
        if self._outage.failed(cause):
            self._said(Availability(away=True, cause=cause))

    def _said(self, change: Availability) -> None:
        for report in self._reports:
            report(change)

    def snapshot_file(self, lock: threading.RLock) -> AbstractContextManager[Path]:
        raise self._errors.failed("a database on a server has no file")

    def tables(self) -> list[str]:
        """The tables of the schema, before a database on it is opened."""
        connection = self._open()
        with self.translated():
            names = sa.inspect(connection).get_table_names()
            connection.rollback()
        return sorted(names)

    def held_schema(self) -> int:
        """The schema the database on the server says it is in, 0 without
        one, read before a database on it is opened."""
        connection = self._open()
        with self.translated():
            held = tables.stored_schema(connection, self._shape)
            connection.rollback()
        return held

    def drop_tables(self) -> None:
        """Every table of the schema dropped, the schema itself kept: what
        a restore made, when it fails. No code drops a schema. A
        connection closed by the failure is replaced by a new one."""
        engine = self._engine_open()
        with self.translated():
            connection = self._connection
            if connection is None or connection.closed:
                with engine.connect() as fresh:
                    _drop_all(fresh)
                return
            connection.rollback()
            _drop_all(connection)

    @contextmanager
    def fixed(self, lock: threading.RLock) -> Iterator[sa.Connection]:
        """A connection of its own, reading in one transaction of
        REPEATABLE READ."""
        engine = self._engine_open()
        self.ready()
        with self.translated():
            conn = dialect.reading_fixed(engine.connect())
        with conn, conn.begin():
            yield conn

    @contextmanager
    def translated(self) -> Iterator[None]:
        """The failures of the database as the errors of the shape, and a
        lost connection as the server going away."""
        with translated_server(self._errors):
            try:
                yield
            except sa.exc.DBAPIError as exc:
                if not _connection_lost(exc):
                    raise
                self._failed(exc)
                raise self._outage.unavailable() from None

    def close(self) -> None:
        with suppress(Exception):
            if self._connection is not None:
                self._connection.close()
        if self._engine is not None:
            self._engine.dispose()


def translated_server(errors: Errors) -> AbstractContextManager[None]:
    """The failures of the database as ``errors`` names them. The server's
    text of a violated key quotes the key and the first line of other
    failures can quote a value: of a conflict only the first line of the
    server, which names the constraint, of anything else only its kind."""
    return translated_by(_first_line, _failure_of, errors)


def _first_line(exc: BaseException | None) -> str:
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None)
    return primary if isinstance(primary, str) else _failure_of(exc)


def _failure_of(exc: BaseException | None) -> str:
    """The class of the failure and the code of five characters the
    server gives it, which names what went wrong and nothing it read."""
    code = getattr(exc, "sqlstate", None)
    kind = type(exc).__name__
    return f"{kind} ({code})" if isinstance(code, str) else kind


def _not_of_the_driver(
    errors: Errors, context: sa.engine.ExceptionContext
) -> BaseException | None:
    """A failure while a statement runs that is no error of the driver,
    such as a value the driver cannot bind, named by its kind alone:
    its text can hold the value."""
    if context.sqlalchemy_exception is None and isinstance(
        context.original_exception, Exception
    ):
        return errors.failed(
            f"the database failed: {type(context.original_exception).__name__}"
        )
    return None


def supported(version: int, errors: Errors) -> None:
    """Refuse a server older than ``OLDEST_SERVER``, by the number it
    gives as ``server_version_num``."""
    if version < OLDEST_SERVER:
        raise errors.failed(
            f"the database server is PostgreSQL {_version_shown(version)}:"
            " this version needs PostgreSQL"
            f" {_version_shown(OLDEST_SERVER)} or newer"
        )


def _version_shown(version: int) -> str:
    major, minor = divmod(version, 10000)
    return f"{major}.{minor}"


def _drop_all(connection: sa.Connection) -> None:
    made = sa.MetaData()
    made.reflect(connection)
    made.drop_all(connection)
    connection.commit()


def _connection_lost(exc: sa.exc.DBAPIError) -> bool:
    """Whether ``exc`` is the connection lost or not made: SQLAlchemy saw
    a disconnect, or the server gave a code of class 08 (connection) or
    57P (the server going down), or none, as a failure of the client to
    connect has."""
    if exc.connection_invalidated:
        return True
    if not isinstance(exc, sa.exc.OperationalError):
        return False
    code = getattr(exc.orig, "sqlstate", None)
    return code is None or code.startswith(("08", "57P"))
