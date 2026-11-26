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


def test_three_ways_make_one_schema(tmp_path: Path) -> None:
    """The baseline on a new database, the old steps up to 26 and the
    definitions."""
    Database(tmp_path / "baseline.db").close()
    at_schema(tmp_path / "old.db", 26).close()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'described.db'}")
    METADATA.create_all(engine)
    engine.dispose()
    old = _shape(tmp_path / "old.db")
    for other in ("baseline.db", "described.db"):
        made = _shape(tmp_path / other)
        assert sorted(made) == sorted(old), other
        for table in old:
            assert made[table] == old[table], (other, table)
    assert _meta(tmp_path / "baseline.db") == _meta(tmp_path / "old.db")


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
