"""The lock of a running program on a database server: the keys of
advisory locks of the session. A schema keeps a random key in ``meta``,
which only its role reads. The key drawn from the names of the program
and the schema stands in while it keeps none."""

from __future__ import annotations

import hashlib
import secrets

import sqlalchemy as sa

from .shape import Shape
from .tables import LOCK_ROW


def lock_key(program: str, schema: str) -> int:
    """The key of the lock on ``schema`` while it keeps no key of its
    own: a number of 64 bits drawn from the name of the program and of
    the schema, the same in every process, and for every role that knows
    the names."""
    digest = hashlib.sha256(f"{program}:{schema}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def kept_key(connection: sa.Connection, shape: Shape) -> int | None:
    """The key of the lock of a running program the schema keeps, None
    while it keeps none. Ends the transaction it reads in."""
    meta = shape.meta
    if not sa.inspect(connection).has_table(meta.name):
        connection.rollback()
        return None
    value = connection.execute(
        sa.select(meta.c.value).where(meta.c.key == LOCK_ROW)
    ).scalar()
    connection.rollback()
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise shape.errors.failed(
            f"the value of {LOCK_ROW} in meta is no number: delete the row"
        ) from None


def drawn_key() -> int:
    """A key for the lock of a running program, a random number of 64 bits."""
    return int.from_bytes(secrets.token_bytes(8), "big", signed=True)


def unlocked(connection: sa.Connection, key: int) -> None:
    """The lock of the session ``key`` let go."""
    connection.execute(sa.select(sa.func.pg_advisory_unlock(key)))
    connection.commit()
