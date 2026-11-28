"""The test database of our own (containers/test-database/, PostgreSQL
19), as the checks of the service and of the agents reach it: its
administrator, a connection of it, the command of Docker, and its
container stopped and started again."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg

from .accounts import ENV_FILE

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

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"


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


def docker_command(env: dict[str, str]) -> str:
    """The command of Docker that reaches the container: ``LIVE_DOCKER`` of
    ``env``, else of this process, else ``docker``."""
    return env.get("LIVE_DOCKER") or os.environ.get("LIVE_DOCKER") or "docker"


@contextmanager
def stopped(command: str) -> Iterator[None]:
    """The container stopped for the block, as a server that is gone, and
    started after it, also when the block fails. Not paused: a paused
    container still takes the packets of a connection, and a call on it
    waits without an end. ``command`` is the one of Docker that reaches
    it (``docker_command``)."""
    docker = shlex.split(command)
    subprocess.run([*docker, "stop", CONTAINER], check=True, capture_output=True)
    try:
        yield
    finally:
        subprocess.run([*docker, "start", CONTAINER], check=True, capture_output=True)
