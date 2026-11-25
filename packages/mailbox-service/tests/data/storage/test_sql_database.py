"""The database on an engine of SQLAlchemy: a read ends its transaction,
writers come one after another, a savepoint is undone alone."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.storage import Database
from benethos_mailbox_service.data.storage.sql.schema import roles

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
