"""The test database of our own (containers/test-database/, PostgreSQL
19) for the checks of the agents: its administrator, a connection of
it, the databases and roles a check made dropped at its end, and the
container stopped and started again."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql

from .settings import ROOT

# The file setup.sh writes, relative to the repository.
TESTS_ENV = ROOT / "containers" / "test-database" / "secrets" / "tests.env"
CONTAINER = "mailbox-test-postgres"


@dataclass(frozen=True)
class Administrator:
    host: str
    port: int
    user: str
    database: str
    password: str

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"


def administrator() -> Administrator:
    """The administrator of the test database, as setup.sh wrote it."""
    found = dict(
        line.split("=", 1)
        for line in TESTS_ENV.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    password = (TESTS_ENV.parent / found["password_file"]).read_text(encoding="utf-8")
    return Administrator(
        host=found["host"],
        port=int(found["port"]),
        user=found["user"],
        database=found["database"],
        password=password.strip(),
    )


def connected(admin: Administrator, database: str | None = None) -> psycopg.Connection:
    """A connection of the administrator, outside any transaction."""
    return psycopg.connect(
        host=admin.host,
        port=admin.port,
        user=admin.user,
        password=admin.password,
        dbname=database or admin.database,
        autocommit=True,
    )


def dropped(admin: Administrator, databases: list[str], roles: list[str]) -> None:
    """The databases and then the roles gone, those not there skipped."""
    with connected(admin) as conn:
        for name in databases:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
        for name in roles:
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


@contextmanager
def stopped(command: str) -> Iterator[None]:
    """The container stopped for the block, as a server that is gone, and
    started after it, also when the block fails. ``command`` is the one
    of Docker that reaches it, as ``LIVE_DOCKER`` names it."""
    docker = shlex.split(command)
    subprocess.run([*docker, "stop", CONTAINER], check=True, capture_output=True)
    try:
        yield
    finally:
        subprocess.run([*docker, "start", CONTAINER], check=True, capture_output=True)
