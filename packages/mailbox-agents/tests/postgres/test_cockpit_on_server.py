"""The cockpit reading the states on a server with a role of its own: it
finds the instances whose owner gave it the read and no other, cannot
write, and shows a server that is away as an instance with its reason."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from benethos_mailbox_agents.cockpit import sources, views
from benethos_mailbox_agents.errors import StateFileError
from benethos_mailbox_agents.store import Store
from benethos_mailbox_common.storage.server_place import Server

from ..agents_helpers import profile
from ..postgres_helpers import connect, fresh_name, instance, role

NOW = datetime.now(UTC)


@contextmanager
def _cockpit() -> Iterator[tuple[str, Server]]:
    """A read role without sign-in and the role of the cockpit as its
    member, signing in to the database of the administrator, both gone
    after the block."""
    from psycopg import sql

    name = fresh_name()
    reader = sql.Identifier(name)
    with role() as login:
        with connect() as conn:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(reader))
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(reader, sql.Identifier(login.role))
            )
        try:
            yield name, login
        finally:
            with connect() as conn:
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(reader))


def _started(server: Server, readers: tuple[str, ...]) -> None:
    with Store.open_server(server, readers=readers) as store:
        store.set_profile(profile(NOW))
        store.set_progress(NOW)


def test_the_cockpit_finds_what_it_was_given_and_writes_nothing() -> None:
    with ExitStack() as held:
        reader, cockpit = held.enter_context(_cockpit())
        given = [held.enter_context(instance()) for _ in range(2)]
        kept = held.enter_context(instance())
        for server in given:
            _started(server, (reader,))
        _started(kept, ())

        found = sources.Servers((cockpit,)).found()
        names = {item.name for item in found}

        assert {server.database for server in given} <= names
        assert kept.database not in names
        first = next(item for item in found if item.name == given[0].database)
        row = views.row(first, NOW)
        assert (row.agent, row.state, row.problem) == ("counting", "healthy", None)
        with first.open() as store, pytest.raises(StateFileError):
            store.set_progress(NOW)
        # A reader only reads, even with the role that owns the state.
        owned = Store.read_server(given[0])
        assert owned is not None
        with owned as store, pytest.raises(StateFileError):
            store.set_progress(NOW)


def test_a_table_open_to_everyone_is_no_instance() -> None:
    # A table of the name that PUBLIC alone may read, as another
    # application might leave it, was given to no reader.
    with ExitStack() as held:
        reader, cockpit = held.enter_context(_cockpit())
        server = held.enter_context(instance())
        _started(server, (reader,))
        with connect(server.database) as conn:
            conn.execute("CREATE SCHEMA open_to_all")
            conn.execute("CREATE TABLE open_to_all.profile (id integer)")
            conn.execute("GRANT USAGE ON SCHEMA open_to_all TO PUBLIC")
            conn.execute("GRANT SELECT ON open_to_all.profile TO PUBLIC")

        names = {item.name for item in sources.Servers((cockpit,)).found()}

    assert not [name for name in names if name.endswith("open_to_all")]
    assert server.database in names


def test_a_server_that_is_away_is_an_instance_with_its_reason() -> None:
    with _cockpit() as (_, cockpit):
        away = replace(cockpit, port=1)

        found = sources.Servers((away,)).found()

    assert [item.name for item in found] == [f"{away.host}-1"]
    row = views.row(found[0], NOW)
    assert row.state == "unreadable"
    assert row.problem is not None and "the database failed" in row.problem
