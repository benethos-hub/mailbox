"""The types of the columns, as SQLite and PostgreSQL write them: made
to SQL without a connection."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from benethos_mailbox_service.data.storage.sql.dialect import (
    BYTES,
    COUNTED,
    IN_CHUNK,
    NUMBER,
    TEXT,
    begin,
    counter,
    greater,
    in_chunks,
    insert_or_set,
    insert_or_skip,
    insert_or_update,
)

TABLE = sa.Table(
    "probe",
    sa.MetaData(),
    counter("seq"),
    sa.Column("text", TEXT, nullable=False),
    sa.Column("number", NUMBER),
    sa.Column("bytes", BYTES),
    **COUNTED,
)


def _lines(dialect: sa.Dialect) -> list[str]:
    made = str(CreateTable(TABLE).compile(dialect=dialect))
    return [line.strip().rstrip(",") for line in made.strip().splitlines()]


def test_sqlite_writes_the_types_as_the_migrations_did() -> None:
    assert _lines(sqlite.dialect()) == [
        "CREATE TABLE probe (",
        "seq INTEGER PRIMARY KEY AUTOINCREMENT",
        "text TEXT NOT NULL",
        "number INTEGER",
        "bytes BLOB",
        ")",
    ]


def test_postgresql_compares_text_byte_for_byte() -> None:
    assert _lines(postgresql.dialect()) == [
        "CREATE TABLE probe (",
        "seq BIGSERIAL",
        'text TEXT COLLATE "C" NOT NULL',
        "number BIGINT",
        "bytes BYTEA",
        "PRIMARY KEY (seq)",
        ")",
    ]


# --- where the databases write differently -------------------------------------

ROWS = sa.Table(
    "rows",
    sa.MetaData(),
    sa.Column("k", TEXT, primary_key=True),
    sa.Column("other", TEXT, unique=True),
    sa.Column("value", TEXT),
    sa.Column("count", NUMBER),
)
PG = postgresql.dialect()


@pytest.fixture
def engine() -> Iterator[sa.Engine]:
    """SQLite in memory with the table ROWS, closed after the test."""
    made = sa.create_engine("sqlite://")
    ROWS.metadata.create_all(made)
    yield made
    made.dispose()


def _rows(conn: sa.Connection) -> list[tuple[object, ...]]:
    return [tuple(r) for r in conn.execute(sa.select(ROWS).order_by(ROWS.c.k))]


def test_insert_or_update(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        some = insert_or_update(ROWS, ["k"], None, conn.dialect)
        conn.execute(some, {"k": "a", "other": "x", "value": "1", "count": 1})
        conn.execute(some, {"k": "a", "other": "y", "value": "2", "count": 2})
        only = insert_or_update(ROWS, ["k"], ["value"], conn.dialect)
        conn.execute(only, {"k": "a", "other": "z", "value": "3", "count": 3})
        assert _rows(conn) == [("a", "y", "3", 2)]
    made = str(insert_or_update(ROWS, ["k"], ["value"], PG).compile(dialect=PG))
    assert "ON CONFLICT (k) DO UPDATE SET value = excluded.value" in made


def test_insert_or_set_reads_the_row_it_would_have_added(engine: sa.Engine) -> None:
    def added(excluded: Any) -> dict[str, Any]:
        return {"count": ROWS.c.count + excluded.count}

    with engine.begin() as conn:
        summed = insert_or_set(ROWS, ["k"], added, conn.dialect)
        conn.execute(summed, {"k": "a", "other": "x", "value": "1", "count": 2})
        conn.execute(summed, {"k": "a", "other": "y", "value": "2", "count": 3})
        assert _rows(conn) == [("a", "x", "1", 5)]
    made = str(insert_or_set(ROWS, ["k"], added, PG).compile(dialect=PG))
    assert "DO UPDATE SET count = (rows.count + excluded.count)" in made


def test_insert_or_skip_minds_every_unique_condition(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        skip = insert_or_skip(ROWS, conn.dialect)
        conn.execute(skip, {"k": "a", "other": "x"})
        conn.execute(skip, {"k": "a", "other": "y"})
        conn.execute(skip, {"k": "b", "other": "x"})
        assert _rows(conn) == [("a", "x", None, None)]
    made = str(insert_or_skip(ROWS, PG).compile(dialect=PG))
    assert made.endswith("ON CONFLICT DO NOTHING")


def test_greater_of_two(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        found = conn.execute(
            sa.select(greater(sa.literal(3), sa.literal(5), conn.dialect))
        ).scalar()
    assert found == 5
    made = str(sa.select(greater(ROWS.c.count, sa.literal(5), PG)).compile(dialect=PG))
    assert "greatest(rows.count" in made


def test_in_chunks_keeps_each_value_once_in_its_order() -> None:
    values = [f"v{n}" for n in range(1200)] + ["v0"]
    chunks = list(in_chunks(values))
    assert [len(c) for c in chunks] == [IN_CHUNK, IN_CHUNK, 200]
    assert [v for c in chunks for v in c] == [f"v{n}" for n in range(1200)]


def test_a_transaction_begins_as_a_writer_on_sqlite(engine: sa.Engine) -> None:
    said: list[str] = []
    with engine.connect() as conn:
        conn.connection.driver_connection.set_trace_callback(said.append)  # type: ignore[union-attr]
        begin(conn)
        conn.exec_driver_sql("ROLLBACK")
    assert said[0] == "BEGIN IMMEDIATE"
