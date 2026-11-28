"""How a database server is reached: where it is and who the program
is there, the engine of SQLAlchemy on PostgreSQL through psycopg, what
libpq is told of TLS, and how long a connection may wait. Part of the
place of a server (``server_place``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from . import dialect, names
from .shape import Shape

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
# The same limits for the server's side of the session, so that a session
# whose client vanished ends within half a minute and lets go of its
# advisory lock. Without them the server waits on its own keepalives,
# two hours by default (measured on PostgreSQL 19, 2026-11-27).
SERVER_SILENCE = " ".join(
    f"-c{name}={value}"
    for name, value in (
        ("tcp_keepalives_idle", SILENCE["keepalives_idle"]),
        ("tcp_keepalives_interval", SILENCE["keepalives_interval"]),
        ("tcp_keepalives_count", SILENCE["keepalives_count"]),
        ("tcp_user_timeout", SILENCE["tcp_user_timeout"]),
    )
)


@dataclass(frozen=True, slots=True)
class Server:
    """Where the database is and who the program is there. ``schema``
    is named after ``role`` unless given. ``tls``: "verify" talks to a
    host other than this one only over TLS with a checked certificate
    and name, against the authorities of ``ca_file`` or else those of
    the system. "off" goes without TLS."""

    host: str
    port: int
    database: str
    role: str
    password: str
    schema: str | None = None
    tls: Literal["verify", "off"] = "verify"
    ca_file: Path | None = None

    @property
    def schema_name(self) -> str:
        return self.role if self.schema is None else self.schema

    def __repr__(self) -> str:
        # Never the password, also not in a traceback.
        return (
            f"Server({self.host}:{self.port}/{self.database},"
            f" role {self.role}, schema {self.schema_name})"
        )


def engine_for(server: Server, shape: Shape, *, read_only: bool = False) -> sa.Engine:
    """The engine on ``server``, which loads the driver: one not installed
    is the failure of ``shape`` its ``extra`` says. With ``read_only``
    every transaction only reads."""
    try:
        return server_engine(
            host=server.host,
            port=server.port,
            database=server.database,
            role=server.role,
            password=server.password,
            search_path=server.schema_name,
            tls=tls_arguments(server.host, server.tls, server.ca_file),
            read_only=read_only,
        )
    except ImportError:
        raise shape.errors.failed(shape.extra) from None


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
    options = server_options(search_path, read_only=read_only)
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


def server_options(search_path: str, *, read_only: bool = False) -> str:
    """What the server is told at the start of a session: the schema, the
    limits of a silent network on its side, and with ``read_only`` that
    every transaction only reads."""
    options = f"-csearch_path={search_path} {SERVER_SILENCE}"
    if read_only:
        options += " -cdefault_transaction_read_only=on"
    return options


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
