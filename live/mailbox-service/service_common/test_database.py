"""The test database of our own (containers/test-database/, PostgreSQL
19): its administrator, a role with a schema of its own for a check that
is gone at the end, and the container stopped and started again."""

from __future__ import annotations

import os
import secrets
import shlex
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from common.accounts import ENV_FILE
from psycopg import sql

# The file setup.sh writes, relative to the repository.
TESTS_ENV = "containers/test-database/secrets/tests.env"
CONTAINER = "mailbox-test-postgres"


@dataclass(frozen=True)
class Administrator:
    host: str
    port: int
    user: str
    database: str
    password: str


@dataclass(frozen=True)
class Role:
    """A role as the service has one, with the schema of its name."""

    name: str
    password: str
    url: str


def administrator(env: dict[str, str]) -> Administrator:
    """The administrator of the test database, from the file
    ``LIVE_TEST_DATABASE`` names, else the one setup.sh writes."""
    path = Path(env.get("LIVE_TEST_DATABASE") or TESTS_ENV)
    if not path.is_absolute():
        path = ENV_FILE.parent.parent / path
    found = dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    password = (path.parent / found["password_file"]).read_text(encoding="utf-8")
    return Administrator(
        host=found["host"],
        port=int(found["port"]),
        user=found["user"],
        database=found["database"],
        password=password.strip(),
    )


def connected(admin: Administrator) -> psycopg.Connection:
    """A connection of the administrator, outside any transaction."""
    return psycopg.connect(
        host=admin.host,
        port=admin.port,
        user=admin.user,
        password=admin.password,
        dbname=admin.database,
        autocommit=True,
    )


@contextmanager
def role(admin: Administrator) -> Iterator[Role]:
    """A role that signs in, with no right beyond its own schema, gone
    with all its schema holds after the block."""
    name = f"live_{secrets.token_hex(4)}"
    password = secrets.token_hex(16)
    made = sql.Identifier(name)
    with connected(admin) as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB"
                " NOCREATEROLE NOINHERIT CONNECTION LIMIT 5"
            ).format(made, sql.Literal(password))
        )
        conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(made, made))
    try:
        yield Role(
            name,
            password,
            f"postgresql://{name}@{admin.host}:{admin.port}/{admin.database}",
        )
    finally:
        with connected(admin) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(made))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(made))


def rows_in(admin: Administrator, schema: str, table: str) -> int:
    """How many rows ``table`` of ``schema`` holds."""
    with connected(admin) as conn:
        found = conn.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        ).fetchone()
    return int(found[0]) if found else 0


@contextmanager
def stopped(env: dict[str, str]) -> Iterator[None]:
    """The container stopped for the block, as a server that is gone, and
    started after it, also when the block fails. Not paused: a paused
    container still takes the packets of a connection, and a call on it
    waits without an end. The command of Docker comes from
    ``LIVE_DOCKER``, else ``docker``."""
    docker = shlex.split(
        env.get("LIVE_DOCKER") or os.environ.get("LIVE_DOCKER") or "docker"
    )
    subprocess.run([*docker, "stop", CONTAINER], check=True, capture_output=True)
    try:
        yield
    finally:
        subprocess.run([*docker, "start", CONTAINER], check=True, capture_output=True)
