"""The schema a database says it is in: a number in ``meta``, and a value
that is none is a failure of the storage, never a bare ValueError."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import sqlalchemy as sa

from benethos_mailbox_common.storage import sqlite_file, tables
from benethos_mailbox_common.storage.errors import OWN, StorageError
from benethos_mailbox_common.storage.shape import Shape

METADATA = sa.MetaData()
sa.Table(
    "meta",
    METADATA,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
SHAPE = Shape(
    program="benethos-mailbox-test",
    noun="test",
    metadata=METADATA,
    versions=Path("versions"),
    newest=1,
    baseline=1,
)


def _file(path: Path, value: str) -> Path:
    with closing(sqlite3.connect(path)) as raw, raw:
        raw.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raw.execute("INSERT INTO meta VALUES ('schema_version', ?)", (value,))
    return path


@pytest.mark.parametrize(("value", "schema"), [("3", 3), ("12", 12)])
def test_the_schema_is_the_number_in_meta(
    tmp_path: Path, value: str, schema: int
) -> None:
    path = _file(tmp_path / "state.db", value)
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn:
            assert tables.stored_schema(conn, SHAPE) == schema
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as raw:
        assert sqlite_file.schema_version(raw, OWN) == schema


def test_a_schema_that_is_no_number_is_a_failure_of_the_storage(
    tmp_path: Path,
) -> None:
    path = _file(tmp_path / "state.db", "x")
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn, pytest.raises(StorageError, match="no number"):
            tables.stored_schema(conn, SHAPE)
    finally:
        engine.dispose()
    with (
        closing(sqlite3.connect(path)) as raw,
        pytest.raises(StorageError, match="no number"),
    ):
        sqlite_file.schema_version(raw, OWN)
