"""A database of its own for one instance of a program on a server: the
role that signs in, the database it owns, closed to every other role,
and once per server the role that may read such databases, with the
role of a reading program that signs in as its member. The statements
are printed for an administrator to run, without a password, or run
here on a connection of one, the password of the role set with them.

Every name is a plain name, checked before, and goes into a statement
as an identifier the dialect quotes. The password goes in as a string
constant with its quotes doubled, under ``standard_conforming_strings``,
since a statement that makes a role takes no parameter, handed to the
driver as it is. No text of a
failure names a statement or a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from . import names
from .errors import Errors
from .server_engine import server_engine, tls_arguments
from .server_place import Server, translated_server
from .shape import Shape

_QUOTE = postgresql.dialect().identifier_preparer.quote


@dataclass(frozen=True, slots=True)
class Instance:
    """What one instance needs: ``role`` signs in and owns ``database``,
    ``reader`` may read it without signing in, and ``login`` signs in as a
    member of ``reader``, as a reading program does."""

    role: str
    database: str
    reader: str
    login: str


@dataclass(frozen=True, slots=True)
class Provided:
    """What a run made: the role and the database always, the reading
    roles only where they were missing."""

    made: tuple[str, ...]


def make_instance(
    admin: Server, instance: Instance, password: str, shape: Shape
) -> Provided:
    """Run the statements of ``instance`` as the administrator ``admin``
    names, signed in to its database, and set ``password`` for the role.
    A role or a database of the names that exists already stops it before
    anything is made. The reading roles are made where they are missing.
    The errors are those of ``shape``, a driver not installed said as its
    ``extra`` says."""
    errors = shape.errors
    if not password or "\0" in password:
        raise errors.failed("the password of the role is empty or holds NUL")
    made = [f"role {instance.role}", f"database {instance.database}"]
    try:
        engine = server_engine(
            host=admin.host,
            port=admin.port,
            database=admin.database,
            role=admin.role,
            password=admin.password,
            search_path=admin.schema_name,
            tls=tls_arguments(admin.host, admin.tls, admin.ca_file),
        )
    except ImportError:
        raise errors.failed(shape.extra) from None
    try:
        with translated_server(errors), engine.connect() as connection:
            conn = connection.execution_options(isolation_level="AUTOCOMMIT")
            taken = [
                name
                for name, found in (
                    (f"the role {instance.role}", _role_exists(conn, instance.role)),
                    (
                        f"the database {instance.database}",
                        _database_exists(conn, instance.database),
                    ),
                )
                if found
            ]
            if taken:
                raise errors.failed(
                    f"{' and '.join(taken)} exist already: provision makes new ones"
                )
            conn.exec_driver_sql("SET standard_conforming_strings = on")
            for line in instance_statements(instance, errors):
                conn.exec_driver_sql(line)
            _password_of_role(conn, instance.role, password, errors)
            for role, line in zip(
                (instance.reader, instance.login),
                reading_statements(instance),
                strict=True,
            ):
                if not _role_exists(conn, role):
                    conn.exec_driver_sql(line)
                    made.append(f"role {role}")
    finally:
        engine.dispose()
    return Provided(made=tuple(made))


def instance_statements(instance: Instance, errors: Errors) -> list[str]:
    """The statements an administrator runs once for ``instance``: its
    role, without the password, which is set apart, and its database."""
    for name in (instance.role, instance.database, instance.reader, instance.login):
        if not names.is_plain_name(name):
            raise errors.failed(
                f"{name!r} is no plain name: lower case letters, digits and"
                " underscores, at most 63"
            )
    role, database = _QUOTE(instance.role), _QUOTE(instance.database)
    return [
        f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
        f"CREATE DATABASE {database} OWNER {role}",
        f"REVOKE CONNECT, TEMPORARY ON DATABASE {database} FROM PUBLIC",
    ]


def reading_statements(instance: Instance) -> list[str]:
    """The statements of the reading roles, run once per server, where
    they are missing."""
    reader, login = _QUOTE(instance.reader), _QUOTE(instance.login)
    return [
        f"CREATE ROLE {reader} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE",
        f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
        f" IN ROLE {reader}",
    ]


def _role_exists(connection: sa.Connection, role: str) -> bool:
    return (
        connection.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": role}
        ).first()
        is not None
    )


def _database_exists(connection: sa.Connection, database: str) -> bool:
    return (
        connection.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": database},
        ).first()
        is not None
    )


def _password_of_role(
    connection: sa.Connection, role: str, password: str, errors: Errors
) -> None:
    """The password of ``role``, on the connection of the driver itself.
    The driver hashes it first, so the statement holds the verifier of
    SCRAM-SHA-256 and never the password: no log of the server, and no
    view of what runs, can show it. A statement handed on without
    parameters is read as it is, a percent sign included. A failure is
    named by its kind alone."""
    driver: Any = connection.connection.driver_connection
    try:
        verifier = driver.pgconn.encrypt_password(
            password.encode(), role.encode(), b"scram-sha-256"
        ).decode()
        statement = f"ALTER ROLE {_QUOTE(role)} PASSWORD {_constant(verifier)}"
        driver.execute(statement)
    except Exception as exc:
        raise errors.failed(
            f"the password of the role was not set: {type(exc).__name__}"
        ) from None


def _constant(text: str) -> str:
    """``text`` as a string constant of SQL, its quotes doubled."""
    return "'" + text.replace("'", "''") + "'"
