"""A database server that ends the session of the service: the next
call fails at once as the server away, and once the pause is over the
call after it runs on a new session, in the schema, with the lock of a
running service taken again."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.storage import (
    Availability,
    Database,
    ServerPlace,
    repositories_on,
)
from benethos_mailbox_service.errors import StorageError, StorageUnavailableError

from ..clocks import Seconds
from ..postgres_helpers import connect, schema, server


def _session(db: Database) -> int:
    with db.connected() as conn:
        pid = conn.execute(sa.select(sa.func.pg_backend_pid())).scalar()
    return int(str(pid))


def _end(pid: int) -> None:
    with connect() as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))


def _holds_the_lock(pid: int) -> bool:
    """Whether the session ``pid`` holds a lock of the session: the
    service takes no other."""
    with connect() as admin:
        row = admin.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
            " AND granted AND pid = %s",
            (pid,),
        ).fetchone()
    return bool(row and row[0])


def test_the_server_away_and_back() -> None:
    clock = Seconds()
    heard: list[Availability] = []
    with schema() as name:
        db = Database(place=ServerPlace(server(name), clock=clock))
        db.watch(heard.append)
        users = repositories_on(db).users
        try:
            with db.serving():
                users.save(User(id="usr_1", name="one"))
                first = _session(db)
                assert _holds_the_lock(first)
                _end(first)
                with pytest.raises(StorageUnavailableError) as away:
                    users.list()
                assert away.value.retry_after == 1
                assert db.unavailable() is not None
                # While the pause runs, nothing goes to the server.
                with pytest.raises(StorageUnavailableError):
                    users.list()
                clock.now += 1.5
                assert [u.id for u in users.list()] == ["usr_1"]
                second = _session(db)
                assert second != first
                assert db.unavailable() is None
                assert _holds_the_lock(second)
        finally:
            db.close()
    assert [(h.away, h.cause, h.lock_lost) for h in heard] == [
        (True, "AdminShutdown (57P01)", False),
        (False, "", False),
    ]
    assert heard[1].seconds == 1.5


def test_a_lock_taken_meanwhile_is_reported() -> None:
    clock = Seconds()
    heard: list[Availability] = []
    with schema() as name:
        db = Database(place=ServerPlace(server(name), clock=clock))
        other = Database(place=ServerPlace(server(name)))
        db.watch(heard.append)
        users = repositories_on(db).users
        try:
            with db.serving():
                _end(_session(db))
                with pytest.raises(StorageUnavailableError):
                    users.list()
                with other.serving():
                    clock.now += 1
                    with pytest.raises(StorageError, match="another service took"):
                        users.list()
        finally:
            db.close()
            other.close()
    assert [h.lock_lost for h in heard] == [False, True]
