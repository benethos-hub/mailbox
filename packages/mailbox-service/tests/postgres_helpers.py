"""The server of the suite against PostgreSQL: where it is, and a schema
of its own for each test, gone after it.

``MAILBOX_POSTGRES_TESTS`` names the file ``containers/test-database/
setup.sh`` writes, lines of ``key=value``: ``host``, ``port``, ``user``,
``database``, ``password_file``, the file of the administrator's
password, ``ca_file``, the test CA the server's certificate comes from,
and ``other_ca_file``, one it does not, each relative to the folder of
the first. Unset, the suite is not
collected. It lies outside ``MAILBOX_SERVICE_``, which the tests clear.
The driver is imported only when a test reaches the server: the default
run needs no extra of the service.
"""

from __future__ import annotations

import itertools
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from benethos_mailbox_service.data.storage import Database, Server, ServerPlace

if TYPE_CHECKING:
    import psycopg

SWITCH = "MAILBOX_POSTGRES_TESTS"
_numbers = itertools.count()


def wanted() -> bool:
    """Whether this run includes the suite against the server."""
    return bool(os.environ.get(SWITCH))


@dataclass(frozen=True, slots=True)
class Admin:
    """The administrator of the server of the tests."""

    host: str
    port: int
    user: str
    password: str
    database: str
    ca_file: Path
    other_ca_file: Path


def admin() -> Admin:
    """The administrator, as the file of ``MAILBOX_POSTGRES_TESTS`` says."""
    path = Path(os.environ[SWITCH])
    found = dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    password = (path.parent / found["password_file"]).read_text(encoding="utf-8")
    return Admin(
        host=found["host"],
        port=int(found["port"]),
        user=found["user"],
        password=password.strip(),
        database=found["database"],
        ca_file=path.parent / found["ca_file"],
        other_ca_file=path.parent / found["other_ca_file"],
    )


def connect() -> psycopg.Connection:
    """A connection of the administrator, outside any transaction."""
    import psycopg

    who = admin()
    return psycopg.connect(
        host=who.host,
        port=who.port,
        user=who.user,
        password=who.password,
        dbname=who.database,
        autocommit=True,
    )


def fresh_name() -> str:
    """A name no other test of this run takes, also on another process."""
    return f"t{os.getpid()}_{next(_numbers)}"


@contextmanager
def schema(name: str | None = None) -> Iterator[str]:
    """A schema of its own for the block, with all it holds gone after."""
    from psycopg import sql

    made = name or fresh_name()
    with connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(made)))
    try:
        yield made
    finally:
        with connect() as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(made))
            )


def schemas() -> set[str]:
    """The schemas of the server, without those of the server itself."""
    with connect() as conn:
        rows = conn.execute("SELECT nspname FROM pg_namespace").fetchall()
    return {
        name
        for (name,) in rows
        if not name.startswith("pg_") and name != "information_schema"
    }


def server(name: str) -> Server:
    """The schema ``name`` of the server, reached as the administrator."""
    who = admin()
    return Server(
        host=who.host,
        port=who.port,
        database=who.database,
        role=who.user,
        password=who.password,
        schema=name,
    )


def database(name: str, *, schema: int | None = None) -> Database:
    """The database in the schema ``name``, made by the revisions."""
    return Database(place=ServerPlace(server(name)), schema=schema)


@contextmanager
def role() -> Iterator[Server]:
    """A role as the service has one: it signs in, has no right beyond
    its own schema of its name, and is gone after the block with all its
    schema holds."""
    from psycopg import sql

    name = fresh_name()
    password = secrets.token_hex(16)
    made = sql.Identifier(name)
    with connect() as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB"
                " NOCREATEROLE NOINHERIT CONNECTION LIMIT 5"
            ).format(made, sql.Literal(password))
        )
        conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(made, made))
    who = admin()
    try:
        yield Server(
            host=who.host,
            port=who.port,
            database=who.database,
            role=name,
            password=password,
        )
    finally:
        with connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(made))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(made))


def in_transaction(db: Database) -> bool:
    """Whether the one connection of ``db`` is inside a transaction: the
    one place a test knows where it sits."""
    return bool(db._connection.in_transaction())
