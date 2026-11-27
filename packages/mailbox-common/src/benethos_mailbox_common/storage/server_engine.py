"""How a database server is reached: the engine of SQLAlchemy on
PostgreSQL through psycopg, what libpq is told of TLS, and how long a
connection may wait. Part of the place of a server (``server_place``)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from . import dialect, names

# Seconds an attempt to connect to a database server may take.
CONNECT_SECONDS = 5
# A connection whose server vanished from the network fails instead of
# waiting for ever: keepalives after 10 seconds of quiet, and data not
# acknowledged within 15 seconds. Measured on Linux (2026-11-26): a call
# on a server whose network went away failed after 10.6 seconds with
# such limits and waited on without them. A server that hangs while
# its system still answers, such as one paused, holds the call still.
SILENCE = {
    "keepalives": 1,
    "keepalives_idle": 10,
    "keepalives_interval": 5,
    "keepalives_count": 3,
    "tcp_user_timeout": 15000,
}


def server_engine(
    *,
    host: str,
    port: int,
    database: str,
    role: str,
    password: str,
    search_path: str,
    tls: Mapping[str, str] | None = None,
    read_only: bool = False,
) -> sa.Engine:
    """An engine on PostgreSQL through psycopg, signed in as ``role``, its
    connections in the schema ``search_path``, a plain name, with what
    libpq is told of TLS in ``tls``. Each
    connection is its own and closes when it is closed: a program keeps
    one for its life, and a view of one moment takes a second. With
    ``read_only`` every transaction of a connection only reads. No value
    of a statement reaches the text of an error."""
    options = f"-csearch_path={search_path}"
    if read_only:
        options += " -cdefault_transaction_read_only=on"
    url = sa.URL.create(
        f"{dialect.POSTGRESQL}+psycopg",
        username=role,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    return sa.create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "options": options,
            "connect_timeout": CONNECT_SECONDS,
            **SILENCE,
            **(tls or {}),
        },
    )


def tls_arguments(
    host: str, tls: Literal["verify", "off"], ca_file: Path | None
) -> dict[str, str]:
    """What libpq is told of TLS. With "verify" a host other than this
    one is reached only over TLS whose certificate and name are checked
    (verify-full), against ``ca_file`` or the authorities of the system.
    This host itself is reached over TLS where the server offers it,
    without the demand. With "off" never over TLS."""
    if tls == "off":
        return {"sslmode": "disable"}
    if names.is_loopback_host(host):
        return {"sslmode": "prefer"}
    return {
        "sslmode": "verify-full",
        "sslrootcert": "system" if ca_file is None else str(ca_file),
    }
