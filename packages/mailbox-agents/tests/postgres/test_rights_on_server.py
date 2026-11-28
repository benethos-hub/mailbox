"""Who reaches the database of an agent on a server, as each start sets
it: no other role, but the readers its settings name, who read every
table, also one a later revision makes, and write nothing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benethos_mailbox_agents.errors import StateFileError
from benethos_mailbox_agents.store import Store
from benethos_mailbox_common.storage.server_place import Server

from ..postgres_helpers import connect, instance, role

NOW = datetime(2026, 11, 27, tzinfo=UTC)


def _connects(who: Server, database: str) -> bool:
    import psycopg

    try:
        with psycopg.connect(
            host=who.host,
            port=who.port,
            user=who.role,
            password=who.password,
            dbname=database,
        ):
            return True
    except psycopg.OperationalError:
        return False


def test_another_role_cannot_connect_and_a_reader_reads_alone() -> None:
    import psycopg

    with role() as stranger, role() as reader, instance() as server:
        assert _connects(stranger, server.database)
        with Store.open_server(server, readers=(reader.role,)) as store:
            assert store.rights is not None
            assert store.rights.owner
            store.set_cursor("token-1", NOW)
            with connect(server.database) as admin:
                admin.execute(f'CREATE TABLE "{server.role}".later (x INTEGER)')
                admin.execute(
                    f'ALTER TABLE "{server.role}".later OWNER TO "{server.role}"'
                )

        assert not _connects(stranger, server.database)
        with Store.open_server(server, readers=(reader.role,)):
            pass
        with psycopg.connect(
            host=reader.host,
            port=reader.port,
            user=reader.role,
            password=reader.password,
            dbname=server.database,
        ) as conn:
            schema = server.role
            assert conn.execute(f'SELECT state FROM "{schema}".cursor').fetchone() == (
                "token-1",
            )
            conn.execute(f'SELECT * FROM "{schema}".later').fetchall()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f'DELETE FROM "{schema}".cursor')


def test_a_reader_left_out_is_taken_out_at_the_next_start() -> None:
    with role() as reader, instance() as server:
        Store.open_server(server, readers=(reader.role,)).close()
        assert _connects(reader, server.database)

        with Store.open_server(server) as store:
            assert store.rights is not None
            assert store.rights.revoked == (reader.role,)
        assert not _connects(reader, server.database)


def test_two_starts_change_nothing() -> None:
    with role() as reader, instance() as server:
        for _ in range(2):
            with Store.open_server(server, readers=(reader.role,)) as store:
                assert store.rights is not None
                assert store.rights.revoked == ()
        assert _connects(reader, server.database)


def test_a_reader_the_server_does_not_know_stops_the_start() -> None:
    with instance() as server:
        with pytest.raises(StateFileError, match="DATABASE_READERS"):
            Store.open_server(
                server,
                readers=("nobody_here",),
                setting="MAILBOX_AGENTS_DATABASE_READERS",
            )


def test_a_role_that_does_not_own_its_database_says_no_reader_was_given() -> None:
    from psycopg import sql

    with role() as reader, role() as agent:
        made = sql.Identifier(agent.role)
        with connect() as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(made))
            admin.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(made)
            )
            admin.execute(
                sql.SQL("GRANT CONNECT, CREATE ON DATABASE {} TO {}").format(made, made)
            )
        try:
            server = Server(
                host=agent.host,
                port=agent.port,
                database=agent.role,
                role=agent.role,
                password=agent.password,
            )
            with Store.open_server(server, readers=(reader.role,)) as store:
                assert store.rights is not None
                assert (store.rights.owner, store.rights.readers) == (False, ())
            assert not _connects(reader, server.database)
        finally:
            with connect() as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(made)
                )
