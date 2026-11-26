"""One service per schema: a second on the same schema is refused while
the first runs, and two schemas of one database do not meet. The lock
is keyed by a number the schema keeps, so a role that knows only the
name cannot take it ahead, and a restore or a move holds off a service
while the schema keeps none."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.storage import ServerPlace
from benethos_mailbox_service.data.storage.sql.server_lock import lock_key
from benethos_mailbox_service.errors import StorageError

from ..postgres_helpers import connect, database, schema, server


def test_a_second_service_on_the_schema_is_refused() -> None:
    with schema() as name:
        first, second = database(name), database(name)
        try:
            with first.serving() as held:
                assert held is True
                with pytest.raises(StorageError, match="another service runs"):
                    with second.serving():
                        pass
            with second.serving() as held:
                assert held is True
        finally:
            first.close()
            second.close()


def test_the_lock_goes_with_the_connection() -> None:
    with schema() as name:
        first = database(name)
        with first.serving():
            first.close()
            second = database(name)
            try:
                with second.serving() as held:
                    assert held is True
            finally:
                second.close()


def test_two_schemas_of_one_database_do_not_meet() -> None:
    with schema() as one, schema() as other:
        first, second = database(one), database(other)
        try:
            with first.serving(), second.serving() as held:
                assert held is True
        finally:
            first.close()
            second.close()


def test_a_database_serving_still_reads_and_writes() -> None:
    with schema() as name:
        db = database(name)
        try:
            with db.serving():
                assert db.schema_version() == 26
                with db.transaction():
                    pass
        finally:
            db.close()


def _kept(name: str) -> str | None:
    """The key of the lock the schema ``name`` keeps in meta."""
    from psycopg import sql

    with connect() as conn:
        row = conn.execute(
            sql.SQL("SELECT value FROM {}.meta WHERE key = 'service_lock'").format(
                sql.Identifier(name)
            )
        ).fetchone()
    return None if row is None else str(row[0])


def test_the_lock_is_keyed_by_a_number_the_schema_keeps() -> None:
    with schema() as name:
        db = database(name)
        try:
            with db.serving():
                kept = _kept(name)
            assert kept is not None
            assert int(kept) != lock_key(name)
            with db.serving():
                assert _kept(name) == kept
            assert "service_lock" not in {row[0] for row in db.rows("meta")}
        finally:
            db.close()


def test_a_lock_keyed_by_the_name_does_not_stop_a_service() -> None:
    with schema() as name:
        db = database(name)
        try:
            with db.serving():
                pass
            with connect() as other:
                # Another session, as any role of the server could.
                other.execute("SELECT pg_advisory_lock(%s)", (lock_key(name),))
                with db.serving() as held:
                    assert held is True
        finally:
            db.close()


def test_a_schema_claimed_by_a_restore_refuses_a_service() -> None:
    with schema() as name:
        claiming = ServerPlace(server(name))
        claiming.open(26, 26)
        try:
            with claiming.claimed():
                db = database(name)
                try:
                    with pytest.raises(StorageError, match="another service runs"):
                        with db.serving():
                            pass
                finally:
                    db.close()
            assert _kept(name) is None
        finally:
            claiming.close()


def test_a_running_service_refuses_a_claim() -> None:
    with schema() as name:
        db = database(name)
        claiming = ServerPlace(server(name))
        claiming.open(26, 26)
        try:
            with db.serving():
                with pytest.raises(StorageError, match="another service runs"):
                    with claiming.claimed():
                        pass
            with claiming.claimed():
                pass
        finally:
            claiming.close()
            db.close()
