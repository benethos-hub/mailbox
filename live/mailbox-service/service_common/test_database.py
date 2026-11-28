"""What the checks of the service make on the test database of our own
(``common.test_database``): a role with a schema of its own for a check
that is gone at the end, and the rows of a table."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from common.test_database import Administrator, connected
from psycopg import sql


@dataclass(frozen=True)
class Role:
    """A role as the service has one, with the schema of its name."""

    name: str
    password: str
    url: str


@contextmanager
def role(admin: Administrator) -> Iterator[Role]:
    """A role that signs in, with no right beyond its own schema, gone
    with all its schema holds after the block."""
    name = f"live_{secrets.token_hex(4)}"
    password = secrets.token_hex(16)
    made = sql.Identifier(name)
    with connected(admin) as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB"
                " NOCREATEROLE NOINHERIT CONNECTION LIMIT 5"
            ).format(made, sql.Literal(password))
        )
        conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(made, made))
    try:
        yield Role(
            name,
            password,
            f"postgresql://{name}@{admin.host}:{admin.port}/{admin.database}",
        )
    finally:
        with connected(admin) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(made))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(made))


def rows_in(admin: Administrator, schema: str, table: str) -> int:
    """How many rows ``table`` of ``schema`` holds."""
    with connected(admin) as conn:
        found = conn.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        ).fetchone()
    return int(found[0]) if found else 0
