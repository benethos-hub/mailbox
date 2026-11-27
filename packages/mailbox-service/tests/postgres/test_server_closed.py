"""The database of the service on a server: closed to every other role
at each start when the role of the service owns it, said to be open in
the log when it does not."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from benethos_mailbox_service.data.storage import Server, open_repositories

from ..postgres_helpers import connect, role


@contextmanager
def _owned() -> Iterator[Server]:
    """A role as the service has one, owning a database of its own with
    its schema in it, both gone after the block."""
    from psycopg import sql

    with role() as server:
        made = sql.Identifier(server.role)
        with connect() as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(made, made))
        own = replace(server, database=server.role)
        try:
            with _signed_in(own) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA {}").format(made))
            yield own
        finally:
            with connect() as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(made)
                )


def _signed_in(who: Server):  # type: ignore[no-untyped-def]
    import psycopg

    return psycopg.connect(
        host=who.host,
        port=who.port,
        user=who.role,
        password=who.password,
        dbname=who.database,
        autocommit=True,
    )


def _connects(who: Server, database: str) -> bool:
    import psycopg

    try:
        with _signed_in(replace(who, database=database)):
            return True
    except psycopg.OperationalError:
        return False


def _closed(server: Server) -> bool | None:
    found = open_repositories("postgres", Path("unused.db"), server)
    try:
        return found.database_closed
    finally:
        found.close()


def test_the_owner_closes_its_database_at_each_start() -> None:
    with role() as stranger, _owned() as server:
        assert _connects(stranger, server.database)

        assert [_closed(server), _closed(server)] == [True, True]
        assert not _connects(stranger, server.database)
        assert _connects(server, server.database)


def test_a_role_that_does_not_own_its_database_finds_it_open() -> None:
    with role() as server:
        assert _closed(server) is False
