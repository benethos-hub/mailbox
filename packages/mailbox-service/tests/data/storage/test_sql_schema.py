"""The tables as SQLAlchemy describes them: the same schema as the one the
old steps make and the one the baseline of the revisions makes, and right
for PostgreSQL from the start."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from benethos_mailbox_service.data.storage import Database
from benethos_mailbox_service.data.storage.sql import revisions
from benethos_mailbox_service.data.storage.sql.file_place import sqlite_engine
from benethos_mailbox_service.data.storage.sql.schema import METADATA
from benethos_mailbox_service.data.storage.sql.tables import BOOKKEEPING

from ...schema_helpers import at_schema, shape


def _shape(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(path)) as conn:
        found = shape(conn)
    return {name: table for name, table in found.items() if name not in BOOKKEEPING}


def _meta(path: Path) -> list[tuple[str, str]]:
    with closing(sqlite3.connect(path)) as conn:
        return sorted(conn.execute("SELECT key, value FROM meta"))


def _alike(made: dict[str, object], other: dict[str, object]) -> None:
    assert sorted(made) == sorted(other)
    for table in other:
        assert made[table] == other[table], table


def test_the_baseline_is_the_schema_the_old_steps_end_at(tmp_path: Path) -> None:
    driver = sqlite3.connect(tmp_path / "baseline.db", isolation_level=None)
    engine = sqlite_engine(lambda: driver)
    with engine.connect() as conn:
        revisions.upgrade(conn, revisions.BASELINE)
    engine.dispose()
    driver.close()
    at_schema(tmp_path / "old.db", revisions.BASELINE).close()
    _alike(_shape(tmp_path / "baseline.db"), _shape(tmp_path / "old.db"))
    assert _meta(tmp_path / "baseline.db") == _meta(tmp_path / "old.db")


def test_the_definitions_are_the_schema_of_the_last_revision(tmp_path: Path) -> None:
    Database(tmp_path / "revised.db").close()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'described.db'}")
    METADATA.create_all(engine)
    engine.dispose()
    _alike(_shape(tmp_path / "described.db"), _shape(tmp_path / "revised.db"))


def test_on_postgresql_text_compares_byte_for_byte() -> None:
    dialect = postgresql.dialect()
    for table in METADATA.sorted_tables:
        made = str(CreateTable(table).compile(dialect=dialect))
        assert "BLOB" not in made, table.name
        for column in table.columns:
            if isinstance(column.type, sa.Text):
                assert f'{column.name} TEXT COLLATE "C"' in made, column


def test_the_one_default_that_is_not_a_fixed_value() -> None:
    computed = [
        f"{table.name}.{column.name}"
        for table in METADATA.sorted_tables
        for column in table.columns
        if column.server_default is not None
        and isinstance(column.server_default.arg, sa.sql.functions.FunctionElement)
    ]
    assert computed == ["keys.created_at"]
