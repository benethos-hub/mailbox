"""The database on an engine of SQLAlchemy: a read ends its transaction,
writers come one after another, a savepoint is undone alone, and no
value of a row reaches the text of an error."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.models import ApiToken, User
from benethos_mailbox_service.data.storage import Database, repositories_on
from benethos_mailbox_service.data.storage.sql.schema import roles
from benethos_mailbox_service.errors import ConflictError, StorageError

from ...schema_helpers import select
from .disk_helpers import traced


@pytest.fixture
def engine_db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "engine.db")
    yield database
    database.close()


def _role(name: str) -> sa.Insert:
    return sa.insert(roles).values(id=name, grants="[]", service="[]")


def test_a_read_ends_its_transaction(engine_db: Database) -> None:
    with engine_db.connected() as conn:
        assert conn.execute(sa.select(roles)).all() == []
    with engine_db.connected() as conn:
        conn.execute(_role("after"))
    assert [r[0] for r in select(engine_db, "SELECT id FROM roles")] == ["after"]


def test_a_transaction_begins_as_a_writer(engine_db: Database) -> None:
    said = traced(engine_db)
    with engine_db.connected() as conn:
        conn.execute(sa.select(roles))
    assert said[0] == "BEGIN IMMEDIATE"


def test_writers_come_one_after_another(engine_db: Database) -> None:
    seen: list[str] = []

    def write(name: str) -> None:
        with engine_db.connected() as conn:
            seen.append(f"{name} in")
            conn.execute(_role(name))
            time.sleep(0.05)
            seen.append(f"{name} out")

    threads = [threading.Thread(target=write, args=(n,)) for n in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    first, second = seen[0][0], seen[2][0]
    assert seen == [f"{first} in", f"{first} out", f"{second} in", f"{second} out"]
    assert sorted(r[0] for r in select(engine_db, "SELECT id FROM roles")) == ["a", "b"]


def _abort() -> None:
    raise RuntimeError("abort")


def test_a_savepoint_is_undone_alone(engine_db: Database) -> None:
    with engine_db.connected() as outer:
        outer.execute(_role("kept"))
        with pytest.raises(RuntimeError), engine_db.connected() as inner:
            inner.execute(_role("undone"))
            _abort()
        with engine_db.connected() as inner:
            inner.execute(_role("also"))
    assert sorted(r[0] for r in select(engine_db, "SELECT id FROM roles")) == [
        "also",
        "kept",
    ]


# What SQLAlchemy writes into the text of its errors: the statement and
# its values.
SQLALCHEMY_TEXT = ("[SQL:", "[parameters:", "INSERT", "SELECT")


def test_the_database_takes_no_sql_as_text() -> None:
    gone = (
        "query",
        "one",
        "one_as",
        "query_as",
        "scalar",
        "query_in",
        "must_find",
        "execute",
        "must_change",
    )
    assert [name for name in gone if hasattr(Database, name)] == []


def _plain(message: str, *values: str) -> None:
    for part in (*SQLALCHEMY_TEXT, *values):
        assert part not in message


def test_a_conflict_names_the_column_and_no_value(engine_db: Database) -> None:
    stores = repositories_on(engine_db)
    stores.users.save(User(id="usr_1", name="Someone"))
    with pytest.raises(ConflictError) as user:
        stores.users.save(User(id="usr_2", name="someone"))
    assert str(user.value) == (
        "conflicts with a stored record: UNIQUE constraint failed: users.name_lower"
    )
    _plain(str(user.value), "Someone", "someone")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    first = ApiToken(
        id="tok_1", user_id="usr_1", name="t", token_hash="hash-1", created_at=now
    )
    stores.tokens.save(first)
    with pytest.raises(ConflictError) as token:
        stores.tokens.save(first.model_copy(update={"id": "tok_2"}))
    assert str(token.value) == (
        "conflicts with a stored record: UNIQUE constraint failed: tokens.token_hash"
    )
    _plain(str(token.value), "hash-1")


def test_a_conflict_through_sqlalchemy_names_no_value(engine_db: Database) -> None:
    with pytest.raises(ConflictError) as caught, engine_db.connected() as conn:
        conn.execute(_role("role-value"))
        conn.execute(_role("role-value"))
    assert str(caught.value) == (
        "conflicts with a stored record: UNIQUE constraint failed: roles.id"
    )
    _plain(str(caught.value), "role-value")


def test_a_failure_of_the_database_names_no_statement(engine_db: Database) -> None:
    with pytest.raises(StorageError) as helper:
        select(engine_db, "SELECT id FROM nowhere WHERE id = ?", ("looked-for",))
    assert str(helper.value) == "the database failed: no such table: nowhere"
    nowhere = sa.table("nowhere", sa.column("id"))
    with pytest.raises(StorageError) as caught, engine_db.connected() as conn:
        conn.execute(sa.select(nowhere).where(nowhere.c.id == "looked-for"))
    assert str(caught.value) == "the database failed: no such table: nowhere"
    _plain(str(caught.value), "looked-for")
