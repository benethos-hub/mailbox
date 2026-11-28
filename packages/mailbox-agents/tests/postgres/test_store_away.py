"""The database of the state on a server that ends the session of the
agent: the next call fails at once as the database away, one after the
pause runs on a new session with the lock of the writer taken again,
and a lock another agent took in the meantime ends the work."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benethos_mailbox_agents.errors import (
    StateFileError,
    StateInUseError,
    StateUnavailableError,
    UnavailableError,
)
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.store import Store
from benethos_mailbox_common.storage.outage import LOCK_GRACE
from benethos_mailbox_common.storage.server_engine import server_engine, tls_arguments

from ..postgres_helpers import connect, instance

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
REF = MessageRef(account_id="acc", message_id="m1")


class _Seconds:
    """A clock in seconds the test moves."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _end(role: str) -> None:
    """End every session of ``role``, as a server that restarts does."""
    with connect() as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s",
            (role,),
        )


def test_the_database_away_and_back() -> None:
    clock = _Seconds()
    with instance() as server, Store.open_server(server, clock=clock) as store:
        store.enqueue(REF, NOW)
        _end(server.role)

        with pytest.raises(StateUnavailableError) as away:
            store.due(NOW, 10)
        assert isinstance(away.value, UnavailableError)
        assert away.value.retry_after == 1
        # While the pause runs, nothing goes to the server.
        with pytest.raises(StateUnavailableError):
            store.due(NOW, 10)
        clock.now += 1.5

        assert [row.ref for row in store.due(NOW, 10)] == [REF]
        with pytest.raises(StateInUseError):
            Store.open_server(server)


def test_a_lock_taken_while_away_ends_the_work() -> None:
    clock = _Seconds()
    with instance() as server, Store.open_server(server, clock=clock) as store:
        _end(server.role)
        with pytest.raises(StateUnavailableError):
            store.due(NOW, 10)

        with Store.open_server(server):
            clock.now += 1.5
            # For a minute the lock may still be the old session's.
            with pytest.raises(StateUnavailableError):
                store.due(NOW, 10)
            clock.now += LOCK_GRACE
            with pytest.raises(StateFileError, match="took this database"):
                store.due(NOW, 10)


def test_a_lock_let_go_within_the_minute_is_taken_again() -> None:
    clock = _Seconds()
    with instance() as server, Store.open_server(server, clock=clock) as store:
        store.enqueue(REF, NOW)
        _end(server.role)
        with pytest.raises(StateUnavailableError):
            store.due(NOW, 10)

        with Store.open_server(server):
            clock.now += 1.5
            with pytest.raises(StateUnavailableError):
                store.due(NOW, 10)
        clock.now += 2.5

        assert [row.ref for row in store.due(NOW, 10)] == [REF]


def test_the_server_ends_a_session_whose_client_went_silent() -> None:

    with instance() as server:
        engine = server_engine(
            host=server.host,
            port=server.port,
            database=server.database,
            role=server.role,
            password=server.password,
            search_path=server.schema_name,
            tls=tls_arguments(server.host, server.tls, server.ca_file),
        )
        try:
            with engine.connect() as conn:
                shown = {
                    name: conn.exec_driver_sql(f"SHOW {name}").scalar()
                    for name in ("tcp_keepalives_idle", "tcp_user_timeout")
                }
        finally:
            engine.dispose()

    assert shown == {"tcp_keepalives_idle": "10", "tcp_user_timeout": "15000"}
