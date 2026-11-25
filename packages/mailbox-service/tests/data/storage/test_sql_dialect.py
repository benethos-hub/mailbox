"""The types of the columns, as SQLite and PostgreSQL write them: made
to SQL without a connection."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from benethos_mailbox_service.data.storage.sql.dialect import (
    BYTES,
    COUNTED,
    NUMBER,
    TEXT,
    counter,
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
