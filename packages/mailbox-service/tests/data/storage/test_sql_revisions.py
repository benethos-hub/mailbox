"""The revisions of Alembic, run inside the process on a connection of
the database: each in a transaction of its own, so one that fails
leaves nothing half done."""

from __future__ import annotations

import re
import sqlite3
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.storage import Database
from benethos_mailbox_service.data.storage.sql import revisions
from benethos_mailbox_service.data.storage.sql.dialect import sqlite_engine
from benethos_mailbox_service.data.storage.sqlite.migrations import MIGRATIONS
from benethos_mailbox_service.errors import StorageError

from ...schema_helpers import at_schema, run, select, value

# Two revisions of a folder of their own: the second fails after its
# first statement.
STEPS = {
    "r0001_first.py": '''
        """A table."""
        import sqlalchemy as sa
        from alembic import op
        revision = "0001"
        down_revision = None
        def upgrade():
            op.create_table("kept", sa.Column("id", sa.Text, primary_key=True))
    ''',
    "r0002_broken.py": '''
        """A table, then a statement that fails."""
        import sqlalchemy as sa
        from alembic import op
        revision = "0002"
        down_revision = "0001"
        def upgrade():
            op.create_table("half", sa.Column("id", sa.Text, primary_key=True))
            op.execute("INSERT INTO nowhere VALUES (1)")
    ''',
}


@pytest.fixture
def versions(tmp_path: Path) -> Path:
    folder = tmp_path / "versions"
    folder.mkdir()
    for name, body in STEPS.items():
        (folder / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return folder


@pytest.fixture
def conn() -> Iterator[sa.Connection]:
    driver = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    engine = sqlite_engine(lambda: driver)
    with engine.connect() as connection:
        yield connection
    engine.dispose()
    driver.close()


def _tables(conn: sa.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def test_a_revision_that_fails_leaves_nothing_half_done(
    conn: sa.Connection, versions: Path
) -> None:
    with pytest.raises(sa.exc.OperationalError, match="nowhere"):
        revisions.upgrade(conn, 2, versions=versions)
    assert not conn.in_transaction()
    assert revisions.mark(conn) == 1
    assert "half" not in _tables(conn)
    assert "kept" in _tables(conn)


def test_a_database_is_marked_without_a_step_run(
    conn: sa.Connection, versions: Path
) -> None:
    assert revisions.mark(conn) is None
    revisions.stamp(conn, 1, versions=versions)
    assert revisions.mark(conn) == 1
    assert "kept" not in _tables(conn)


def _numbers() -> list[int]:
    """The schema of every revision of the service, in order."""
    found = [
        int(m.group(1))
        for path in (revisions.HERE / "versions").glob("*.py")
        if (m := re.search(r'^revision = "(\d+)"', path.read_text("utf-8"), re.M))
    ]
    return sorted(found)


def test_the_revisions_go_on_where_the_old_steps_end() -> None:
    numbers = _numbers()
    assert numbers[0] == revisions.BASELINE == MIGRATIONS.schema_version
    assert numbers == list(range(numbers[0], numbers[-1] + 1))
    assert numbers[-1] == revisions.SCHEMA_VERSION


def test_every_revision_writes_its_number_into_meta(conn: sa.Connection) -> None:
    for number in _numbers():
        revisions.upgrade(conn, number)
        assert revisions.mark(conn) == number
        with conn.begin():
            held = conn.exec_driver_sql(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).scalar()
        assert held == str(number)


def test_a_database_the_old_steps_made_is_marked_and_kept(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    raw = at_schema(path, revisions.BASELINE)
    raw.execute(
        "INSERT INTO roles (id, grants, service, position) VALUES ('r', '[]', '[]', 1)"
    )
    raw.close()
    db = Database(path)
    # The file is rewritten once to shrink: the schema stays.
    assert db.migrated is not None
    assert (db.migrated.before, db.migrated.after) == (26, 26)
    assert value(db, "SELECT version_num FROM alembic_version") == "0026"
    assert [r[0] for r in select(db, "SELECT id FROM roles")] == ["r"]
    db.close()
    again = Database(path)
    assert again.migrated is None
    assert [r[0] for r in select(again, "SELECT id FROM roles")] == ["r"]
    again.close()


def test_a_new_database_is_made_by_the_revisions(tmp_path: Path) -> None:
    db = Database(tmp_path / "new.db")
    assert db.migrated is not None
    assert (db.migrated.before, db.migrated.after) == (0, revisions.SCHEMA_VERSION)
    assert db.schema_version() == revisions.SCHEMA_VERSION
    db.close()


def test_a_database_whose_two_numbers_disagree_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "torn.db"
    db = Database(path)
    run(db, "UPDATE alembic_version SET version_num = '0025'")
    db.close()
    with pytest.raises(StorageError, match="says schema 26 and its revisions 25"):
        Database(path)
