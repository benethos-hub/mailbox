"""The revisions of Alembic, run inside the process on a connection of
the database: each in a transaction of its own, so one that fails
leaves nothing half done."""

from __future__ import annotations

import sqlite3
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.storage.sql import revisions
from benethos_mailbox_service.data.storage.sql.dialect import sqlite_engine

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
