"""The PostgreSQL server of the tests: ``containers/test-database``, named
by the file ``MAILBOX_POSTGRES_TESTS`` names, which lies outside
``MAILBOX_AGENTS_``, which the tests clear. Without it the tests in
``postgres/`` are not collected. The driver is imported only here,
inside the functions, so the default run needs no extra.

Each test takes a database of its own, owned by a role of its own, as
an instance of an agent has them, and both are gone after it."""

from __future__ import annotations

import itertools
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from benethos_mailbox_agents.settings import PREFIX
from benethos_mailbox_common.storage.server_place import Server

if TYPE_CHECKING:
    import psycopg
    import pytest

SWITCH = "MAILBOX_POSTGRES_TESTS"
_numbers = itertools.count()


def wanted() -> bool:
    """Whether this run includes the tests against the server."""
    return bool(os.environ.get(SWITCH))


def _admin() -> dict[str, str]:
    path = Path(os.environ[SWITCH])
    found = dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    found["password"] = (
        (path.parent / found["password_file"]).read_text(encoding="utf-8").strip()
    )
    return found


def connect(database: str | None = None) -> psycopg.Connection:
    """A connection of the administrator, outside any transaction."""
    import psycopg

    who = _admin()
    return psycopg.connect(
        host=who["host"],
        port=int(who["port"]),
        user=who["user"],
        password=who["password"],
        dbname=database or who["database"],
        autocommit=True,
    )


def fresh_name() -> str:
    """A name no other test of this run takes, also on another process."""
    return f"ta{os.getpid()}_{next(_numbers)}"


@contextmanager
def role(*, login: bool = True) -> Iterator[Server]:
    """A role of its own, without a right beyond what is given to it, gone
    after the block. Its server names the database of the administrator."""
    from psycopg import sql

    name = fresh_name()
    password = secrets.token_hex(16)
    made = sql.Identifier(name)
    with connect() as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} {} PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
            ).format(
                made, sql.SQL("LOGIN" if login else "NOLOGIN"), sql.Literal(password)
            )
        )
    who = _admin()
    try:
        yield Server(
            host=who["host"],
            port=int(who["port"]),
            database=who["database"],
            role=name,
            password=password,
        )
    finally:
        with connect() as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(made))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(made))


@contextmanager
def instance() -> Iterator[Server]:
    """A role of its own and a database of its own it owns, as an instance
    of an agent has them, gone after the block."""
    from psycopg import sql

    with role() as server:
        made = sql.Identifier(server.role)
        with connect() as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(made, made))
        try:
            yield Server(
                host=server.host,
                port=server.port,
                database=server.role,
                role=server.role,
                password=server.password,
            )
        finally:
            with connect() as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(made)
                )


def url_of(server: Server) -> str:
    """The address of the database and the role of ``server``, without
    the password."""
    return f"postgresql://{server.role}@{server.host}:{server.port}/{server.database}"


def settings_at(monkeypatch: pytest.MonkeyPatch, server: Server, folder: Path) -> None:
    """The settings of a state in the database of ``server``, its
    password in a file in ``folder``."""
    password = folder / "database_password"
    password.write_text(server.password, encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}DATABASE_URL", url_of(server))
    monkeypatch.setenv(f"{PREFIX}DATABASE_PASSWORD_FILE", str(password))


def admin_url() -> str:
    """The address of the administrator, without the password."""
    who = _admin()
    return f"postgresql://{who['user']}@{who['host']}:{who['port']}/{who['database']}"


def admin_password_file(folder: Path) -> Path:
    """A file in ``folder`` that holds the password of the administrator."""
    path = folder / "admin_password"
    path.write_text(_admin()["password"], encoding="utf-8")
    return path
