"""The revisions on PostgreSQL: a refused step leaves nothing, a step
outside a transaction runs what a transaction refuses, and a revision
that asks for a copy of the database is refused, since a server keeps
none. A database of a schema newer than this version is refused."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_service.data.storage.sql import database as database_module
from benethos_mailbox_service.data.storage.sql import revisions
from benethos_mailbox_service.data.storage.sql.server_engine import server_engine
from benethos_mailbox_service.errors import StorageError

from ..postgres_helpers import admin, connect, database, schema
from ..revision_helpers import second, steps_in


@pytest.fixture
def bare() -> Iterator[sa.Connection]:
    """A connection in a schema of its own, which holds nothing yet."""
    who = admin()
    with schema() as name:
        engine = server_engine(
            host=who.host,
            port=who.port,
            database=who.database,
            role=who.user,
            password=who.password,
            search_path=name,
        )
        with engine.connect() as connection:
            yield connection
        engine.dispose()


def _held(conn: sa.Connection) -> str | None:
    meta = sa.table("meta", sa.column("key"), sa.column("value"))
    with conn.begin():
        held: str | None = conn.execute(
            sa.select(meta.c.value).where(meta.c.key == "schema_version")
        ).scalar()
    return held


def _tables(conn: sa.Connection) -> set[str]:
    with conn.begin():
        return set(sa.inspect(conn).get_table_names())


def test_a_refused_step_leaves_nothing(bare: sa.Connection, tmp_path: Path) -> None:
    folder = steps_in(
        tmp_path / "versions",
        """
        def steps(self):
            op.create_table("half", sa.Column("id", sa.Text, primary_key=True))
            self.refuse("the items do not fit")
        """,
    )
    revisions.upgrade(bare, 26, versions=folder)
    with pytest.raises(StorageError, match="the items do not fit"):
        revisions.upgrade(bare, 27, versions=folder)
    assert revisions.mark(bare) == 26
    assert _held(bare) == "26"
    assert _tables(bare) == {"meta", "items", "alembic_version"}


def test_a_concurrent_index_is_refused_inside_a_transaction(
    bare: sa.Connection, tmp_path: Path
) -> None:
    folder = steps_in(
        tmp_path / "versions",
        """
        def steps(self):
            op.create_index("items_name", "items", ["name"],
                            postgresql_concurrently=True)
        """,
    )
    revisions.upgrade(bare, 26, versions=folder)
    with pytest.raises(sa.exc.DBAPIError, match="inside a transaction block"):
        revisions.upgrade(bare, 27, versions=folder)
    bare.rollback()
    assert revisions.mark(bare) == 26


def test_a_concurrent_index_runs_outside_a_transaction(
    bare: sa.Connection, tmp_path: Path
) -> None:
    folder = steps_in(
        tmp_path / "versions",
        """
        in_transaction = False

        def steps(self):
            op.create_index("items_name", "items", ["name"],
                            postgresql_concurrently=True)
        """,
    )
    revisions.upgrade(bare, 26, versions=folder)
    revisions.upgrade(bare, 27, versions=folder)
    assert revisions.mark(bare) == 27
    assert _held(bare) == "27"


def test_outside_a_transaction_the_index_stays_when_the_check_fails(
    bare: sa.Connection, tmp_path: Path
) -> None:
    folder = steps_in(
        tmp_path / "versions",
        """
        in_transaction = False

        def steps(self):
            op.create_index("items_name", "items", ["name"],
                            postgresql_concurrently=True)

        def check(self):
            self.refuse("checked")
        """,
    )
    revisions.upgrade(bare, 26, versions=folder)
    with pytest.raises(StorageError, match="checked"):
        revisions.upgrade(bare, 27, versions=folder)
    assert revisions.mark(bare) == 26
    assert _held(bare) == "26"
    with bare.begin():
        indexes = [i["name"] for i in sa.inspect(bare).get_indexes("items")]
    assert "items_name" in indexes


def test_a_revision_that_asks_for_a_copy_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server keeps no copy: the first such revision cannot pass
    unnoticed."""
    folder = tmp_path / "versions"
    folder.mkdir()
    for baseline in revisions.VERSIONS.glob("r0026_*.py"):
        shutil.copy(baseline, folder / baseline.name)
    (folder / "r0027_copied.py").write_text(
        second("""
            keeps_copy = True

            def steps(self):
                op.add_column("roles", sa.Column("note", sa.Text))
        """),
        encoding="utf-8",
    )
    with schema() as name:
        database(name).close()
        monkeypatch.setattr(revisions, "VERSIONS", folder)
        monkeypatch.setattr(database_module, "SCHEMA_VERSION", 27)
        with pytest.raises(StorageError, match="asks for a copy"):
            database(name)
        monkeypatch.setattr(database_module, "SCHEMA_VERSION", 26)
        again = database(name)
        try:
            assert again.schema_version() == 26
        finally:
            again.close()


def test_a_database_of_a_newer_schema_is_refused() -> None:
    from psycopg import sql

    with schema() as name:
        database(name).close()
        with connect() as conn:
            conn.execute(
                sql.SQL(
                    "UPDATE {}.meta SET value = '27' WHERE key = 'schema_version'"
                ).format(sql.Identifier(name))
            )
            conn.execute(
                sql.SQL("UPDATE {}.alembic_version SET version_num = '0027'").format(
                    sql.Identifier(name)
                )
            )
        with pytest.raises(StorageError, match="schema 27 is newer") as refused:
            database(name)
        assert f"({revisions.SCHEMA_VERSION})" in str(refused.value)
