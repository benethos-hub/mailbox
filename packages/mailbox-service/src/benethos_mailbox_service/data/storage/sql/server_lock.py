"""The lock of a running service on a database server: the keys of
advisory locks of the session. A schema keeps a random key in ``meta``,
which only its role reads. The key drawn from the name of the schema
stands in while it keeps none."""

from __future__ import annotations

import hashlib
import secrets

import sqlalchemy as sa

from ....errors import StorageError
from .schema import meta
from .tables import SERVICE_LOCK


def lock_key(schema: str) -> int:
    """The key of the lock on ``schema`` while it keeps no key of its
    own: a number of 64 bits drawn from its name, the same in every
    process, and for every role that knows the name."""
    digest = hashlib.sha256(f"benethos-mailbox-service:{schema}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def kept_key(connection: sa.Connection) -> int | None:
    """The key of the lock of a running service the schema keeps, None
    while it keeps none. Ends the transaction it reads in."""
    if not sa.inspect(connection).has_table(meta.name):
        connection.rollback()
        return None
    value = connection.execute(
        sa.select(meta.c.value).where(meta.c.key == SERVICE_LOCK)
    ).scalar()
    connection.rollback()
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise StorageError(
            f"the value of {SERVICE_LOCK} in meta is no number: delete the row"
        ) from None


def new_key() -> int:
    """A key for the lock of a running service, a random number of 64 bits."""
    return int.from_bytes(secrets.token_bytes(8), "big", signed=True)


def unlock(connection: sa.Connection, key: int) -> None:
    connection.execute(sa.select(sa.func.pg_advisory_unlock(key)))
    connection.commit()
