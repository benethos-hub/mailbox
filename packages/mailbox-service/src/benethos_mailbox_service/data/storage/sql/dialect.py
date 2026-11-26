"""The one module under ``sql/`` that names a database: the types of the
columns, and where SQLite and PostgreSQL write differently. Everything
else under ``sql/`` speaks SQLAlchemy Core alone.

Text is compared byte for byte on both: SQLite does so, and PostgreSQL
is told so by the collation ``C``. The service compares times as ISO
text and sorts by ids, which must come out the same on both.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, TypeVar

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.pool import NullPool, StaticPool

T = TypeVar("T")
# An INSERT that knows what to do about a row already there.
Insert = sqlite.Insert | postgresql.Insert

POSTGRESQL = "postgresql"
SQLITE = "sqlite"

# TEXT, on PostgreSQL TEXT COLLATE "C".
TEXT = sa.Text().with_variant(sa.Text(collation="C"), POSTGRESQL)
# INTEGER, on PostgreSQL BIGINT.
NUMBER = sa.Integer().with_variant(sa.BigInteger(), POSTGRESQL)
# BLOB, on PostgreSQL BYTEA.
BYTES = sa.LargeBinary()
# The key that counts up: INTEGER PRIMARY KEY AUTOINCREMENT on SQLite,
# which needs the table to say COUNTED, a column that counts itself on
# PostgreSQL.
_COUNTER = sa.BigInteger().with_variant(sa.Integer(), SQLITE)
COUNTED: dict[str, Any] = {"sqlite_autoincrement": True}


def counter(name: str) -> sa.Column[int]:
    """The key ``name`` that counts up and never hands out a number twice.
    Its table says ``**COUNTED``."""
    # SQLite keeps an INTEGER PRIMARY KEY without NOT NULL, as it is in
    # the schema the migrations made.
    return sa.Column(
        name, _COUNTER, primary_key=True, autoincrement=True, nullable=True
    )


# Stays below the parameters one statement of SQLite takes: 32,766 in
# this one, 999 in older ones.
IN_CHUNK = 500


def insert_or_update(
    table: sa.Table,
    key: Sequence[str],
    update: Sequence[str] | None,
    dialect: sa.Dialect,
) -> Insert:
    """INSERT that, where a row of the same ``key`` is there, sets its
    columns ``update`` to the new values instead. ``None``: every column
    outside the key."""
    columns = (
        [c.name for c in table.columns if c.name not in key]
        if update is None
        else list(update)
    )
    return insert_or_set(
        table,
        key,
        lambda excluded: {name: excluded[name] for name in columns},
        dialect,
    )


def insert_or_set(
    table: sa.Table,
    key: Sequence[str],
    values: Callable[[Any], Mapping[str, Any]],
    dialect: sa.Dialect,
) -> Insert:
    """INSERT that, where a row of the same ``key`` is there, sets what
    ``values`` makes of the row the INSERT would have added instead: its
    columns are those of the argument, ``excluded`` in both databases."""
    statement = _insert(table, dialect)
    return statement.on_conflict_do_update(
        index_elements=list(key), set_=dict(values(statement.excluded))
    )


def insert_or_skip(table: sa.Table, dialect: sa.Dialect) -> Insert:
    """INSERT that leaves out a row that would break any condition of
    being unique, and goes on."""
    return _insert(table, dialect).on_conflict_do_nothing()


def greater(
    first: sa.ColumnElement[Any], second: sa.ColumnElement[Any], dialect: sa.Dialect
) -> sa.ColumnElement[Any]:
    """The greater of two values: MAX(a, b) on SQLite, GREATEST(a, b) on
    PostgreSQL."""
    if dialect.name == SQLITE:
        return sa.func.max(first, second)
    return sa.func.greatest(first, second)


def in_chunks(values: Iterable[T]) -> Iterator[list[T]]:
    """The distinct ``values`` in their order, in chunks small enough for
    one ``IN``."""
    unique = list(dict.fromkeys(values))
    for start in range(0, len(unique), IN_CHUNK):
        yield unique[start : start + IN_CHUNK]


def begin(connection: sa.Connection) -> None:
    """How a transaction begins. On SQLite at once as a writer, so two
    transactions never meet halfway: the one place under ``sql/`` that
    hands the driver a statement as text."""
    if connection.dialect.name == SQLITE:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


# Where SQLite keeps the last number a counting key handed out.
_SEQUENCE = sa.table("sqlite_sequence", sa.column("name"), sa.column("seq"))


def count_on_from(connection: sa.Connection, table: sa.Table, last: int) -> None:
    """The counting key of ``table`` hands out numbers after ``last`` at
    least, also when the rows that had them are gone. Never lowered. On
    SQLite in ``sqlite_sequence``, on PostgreSQL in the sequence of the
    column."""
    if connection.dialect.name == POSTGRESQL:
        _sequence_on_from(connection, table, last)
        return
    name = _SEQUENCE.c.name == table.name
    raised = connection.execute(
        sa.update(_SEQUENCE).where(name).values(seq=sa.func.max(_SEQUENCE.c.seq, last))
    ).rowcount
    if not raised:
        connection.execute(sa.insert(_SEQUENCE).values(name=table.name, seq=last))


def _sequence_on_from(connection: sa.Connection, table: sa.Table, last: int) -> None:
    """The sequence behind the counting key of ``table``, set to ``last``
    when it would hand out that number or a lower one."""
    [key] = table.primary_key.columns
    found = connection.execute(
        sa.select(sa.func.pg_get_serial_sequence(table.name, key.name))
    ).scalar()
    if found is None:
        raise ValueError(f"the key of {table.name} counts with no sequence")
    schema, _, name = str(found).partition(".")
    sequence = sa.table(
        name, sa.column("last_value"), sa.column("is_called"), schema=schema
    )
    held = connection.execute(
        sa.select(sequence.c.last_value, sequence.c.is_called)
    ).one()
    current = held.last_value if held.is_called else 0
    if last > current:
        connection.execute(sa.select(sa.func.setval(str(found), last)))


def _insert(table: sa.Table, dialect: sa.Dialect) -> Insert:
    if dialect.name == POSTGRESQL:
        return postgresql.insert(table)
    return sqlite.insert(table)


def sqlite_engine(connect: Callable[[], Any]) -> sa.Engine:
    """An engine on the one SQLite connection ``connect`` gives, for the
    whole process. A transaction begins as ``begin`` says. No value of a
    statement reaches the text of an error."""
    engine = sa.create_engine(
        f"{SQLITE}://",
        creator=connect,
        poolclass=StaticPool,
        hide_parameters=True,
    )
    sa.event.listen(engine, "begin", begin)
    return engine


# Seconds an attempt to connect to a database server may take.
CONNECT_SECONDS = 10


def server_engine(
    *,
    host: str,
    port: int,
    database: str,
    role: str,
    password: str,
    search_path: str,
    tls: Mapping[str, str] | None = None,
) -> sa.Engine:
    """An engine on PostgreSQL through psycopg, signed in as ``role``, its
    connections in the schema ``search_path``, a plain name, with what
    libpq is told of TLS in ``tls``. Each
    connection is its own and closes when it is closed: the service keeps
    one for its life, and a view of one moment takes a second. No value
    of a statement reaches the text of an error."""
    url = sa.URL.create(
        f"{POSTGRESQL}+psycopg",
        username=role,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    return sa.create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "options": f"-csearch_path={search_path}",
            "connect_timeout": CONNECT_SECONDS,
            **(tls or {}),
        },
    )


def reading_fixed(connection: sa.Connection) -> sa.Connection:
    """``connection`` reading one state in each transaction, writing
    nothing: REPEATABLE READ, on PostgreSQL read only as well."""
    options: dict[str, Any] = {"isolation_level": "REPEATABLE READ"}
    if connection.dialect.name == POSTGRESQL:
        options["postgresql_readonly"] = True
    return connection.execution_options(**options)
