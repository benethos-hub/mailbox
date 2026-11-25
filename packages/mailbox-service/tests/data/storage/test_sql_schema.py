"""The tables as SQLAlchemy describes them: the same schema as the one the
migrations make, and right for PostgreSQL from the start."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from benethos_mailbox_service.data.storage import Database
from benethos_mailbox_service.data.storage.sql.schema import METADATA

from ...schema_helpers import shape


def _shape(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(path)) as conn:
        return shape(conn)


def test_the_tables_are_those_the_migrations_make(tmp_path: Path) -> None:
    Database(tmp_path / "migrated.db").close()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'described.db'}")
    METADATA.create_all(engine)
    engine.dispose()
    migrated = _shape(tmp_path / "migrated.db")
    described = _shape(tmp_path / "described.db")
    assert sorted(described) == sorted(migrated)
    for table in migrated:
        assert described[table] == migrated[table], table


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
