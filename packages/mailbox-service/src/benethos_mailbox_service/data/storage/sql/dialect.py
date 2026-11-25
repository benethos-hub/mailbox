"""The one module under ``sql/`` that names a database: the types of the
columns, and where SQLite and PostgreSQL write differently. Everything
else under ``sql/`` speaks SQLAlchemy Core alone.

Text is compared byte for byte on both: SQLite does so, and PostgreSQL
is told so by the collation ``C``. The service compares times as ISO
text and sorts by ids, which must come out the same on both.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

POSTGRESQL = "postgresql"
SQLITE = "sqlite"

# TEXT, on PostgreSQL TEXT COLLATE "C".
TEXT = sa.Text().with_variant(sa.Text(collation="C"), POSTGRESQL)
# INTEGER, on PostgreSQL BIGINT.
NUMBER = sa.Integer().with_variant(sa.BigInteger(), POSTGRESQL)
# BLOB, on PostgreSQL BYTEA.
BYTES = sa.LargeBinary()
# The key that counts up: INTEGER PRIMARY KEY AUTOINCREMENT on SQLite,
# which needs the table to say COUNTED, a column that counts itself on
# PostgreSQL.
_COUNTER = sa.BigInteger().with_variant(sa.Integer(), SQLITE)
COUNTED: dict[str, Any] = {"sqlite_autoincrement": True}


def counter(name: str) -> sa.Column[int]:
    """The key ``name`` that counts up and never hands out a number twice.
    Its table says ``**COUNTED``."""
    # SQLite keeps an INTEGER PRIMARY KEY without NOT NULL, as it is in
    # the schema the migrations made.
    return sa.Column(
        name, _COUNTER, primary_key=True, autoincrement=True, nullable=True
    )
