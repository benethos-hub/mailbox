"""The server of the suite against PostgreSQL: where it is, and a schema
of its own for each test, gone after it.

``MAILBOX_POSTGRES_TESTS`` names the file ``containers/test-database/
setup.sh`` writes, lines of ``key=value``: ``host``, ``port``, ``user``,
``database`` and ``password_file``, the file of the administrator's
password, relative to the folder of the first. Unset, the suite is not
collected. It lies outside ``MAILBOX_SERVICE_``, which the tests clear.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

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
    )


def connect() -> psycopg.Connection:
    """A connection of the administrator, outside any transaction."""
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
