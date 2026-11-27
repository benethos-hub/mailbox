"""Who may reach a program's database on a server: its schema made where
it is missing, the database closed to every other role, and the read of
it given to the roles a program names, and taken back from those it no
longer names. Run by the role of the program, at each start, so a
change of its settings takes effect then: nothing of it needs a
superuser, only the role that owns the database.

Every name is a plain name, checked before, and goes into a statement as
an identifier SQLAlchemy quotes, never as text another source gave.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa

from . import names
from .errors import Errors


@dataclass(frozen=True, slots=True)
class Rights:
    """What a start did to the database: whether the role owns it and so
    closed it, and the roles that may read it."""

    owner: bool
    readers: tuple[str, ...]
    revoked: tuple[str, ...]


def own_schema(connection: sa.Connection, schema: str, errors: Errors) -> bool:
    """The schema ``schema`` made when it is missing and the role may make
    one in its database. Whether it is there now."""
    _plain(schema, errors)
    found = connection.execute(
        sa.select(sa.literal(1))
        .select_from(sa.table("pg_namespace", sa.column("nspname")))
        .where(sa.column("nspname") == schema)
    ).first()
    made = found is None and _may("CREATE", connection)
    if made:
        connection.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
    connection.commit()
    return found is not None or made


def secure(
    connection: sa.Connection,
    schema: str,
    readers: Sequence[str],
    errors: Errors,
    *,
    setting: str,
) -> Rights:
    """The database closed and given to ``readers`` alone, the default of
    its future tables too. A role that owns the database takes CONNECT and
    TEMPORARY from PUBLIC and CONNECT from every other role it did not
    name. One that does not own it gives the read alone. A reader that is
    no role of the server stops it, named by ``setting``."""
    for name in (schema, *readers):
        _plain(name, errors)
    missing = sorted(set(readers) - _roles(connection, readers))
    if missing:
        raise errors.failed(f"{setting} names a role the server does not have")
    preparer = connection.dialect.identifier_preparer
    database = preparer.quote(_current_database(connection))
    owner = _owns_database(connection)
    revoked: list[str] = []
    statements: list[str] = []
    if owner:
        statements.append(
            f"REVOKE CONNECT, TEMPORARY ON DATABASE {database} FROM PUBLIC"
        )
        for role in _connecting(connection):
            if role not in readers:
                revoked.append(role)
                statements.append(
                    f"REVOKE CONNECT ON DATABASE {database} FROM {preparer.quote(role)}"
                )
    where = preparer.quote(schema)
    for role in readers:
        reader = preparer.quote(role)
        statements += [
            f"GRANT CONNECT ON DATABASE {database} TO {reader}",
            f"GRANT USAGE ON SCHEMA {where} TO {reader}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {where} TO {reader}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {where} GRANT SELECT ON TABLES"
            f" TO {reader}",
        ]
    for statement in statements:
        connection.exec_driver_sql(statement)
    connection.commit()
    return Rights(owner, tuple(readers), tuple(revoked))


def close_database(connection: sa.Connection) -> bool:
    """CONNECT and TEMPORARY of the database taken from PUBLIC, where the
    role owns it and is no superuser. Whether the database is closed to
    other roles now, by this or by an administrator before."""
    if _owns_database(connection):
        database = connection.dialect.identifier_preparer.quote(
            _current_database(connection)
        )
        connection.exec_driver_sql(
            f"REVOKE CONNECT, TEMPORARY ON DATABASE {database} FROM PUBLIC"
        )
    open_to_all = connection.exec_driver_sql(
        "SELECT has_database_privilege('public', current_database(), 'CONNECT')"
    ).scalar()
    connection.commit()
    return not open_to_all


def _plain(name: str, errors: Errors) -> None:
    if not names.is_plain_name(name):
        raise errors.failed(
            "a role or a schema is not a plain name: lower case letters,"
            " digits and underscores"
        )


def _may(privilege: str, connection: sa.Connection) -> bool:
    return bool(
        connection.execute(
            sa.select(
                sa.func.has_database_privilege(
                    sa.func.current_database(), sa.literal(privilege)
                )
            )
        ).scalar()
    )


def _current_database(connection: sa.Connection) -> str:
    return str(connection.execute(sa.select(sa.func.current_database())).scalar())


def _owns_database(connection: sa.Connection) -> bool:
    """Whether the role that signed in owns its database, and is no
    superuser: a superuser owns what it administers, and closing that
    would shut out every other role of the server."""
    owned = connection.exec_driver_sql(
        "SELECT pg_get_userbyid(d.datdba) = current_user AND NOT r.rolsuper"
        " FROM pg_database d, pg_roles r"
        " WHERE d.datname = current_database() AND r.rolname = current_user"
    ).scalar()
    return bool(owned)


def _roles(connection: sa.Connection, wanted: Sequence[str]) -> set[str]:
    if not wanted:
        return set()
    rows: sa.CursorResult[tuple[str]] = connection.execute(
        sa.select(sa.column("rolname"))
        .select_from(sa.table("pg_roles", sa.column("rolname")))
        .where(sa.column("rolname").in_(list(wanted)))
    )
    return {str(row[0]) for row in rows}


def _connecting(connection: sa.Connection) -> list[str]:
    """The roles, but the owner and PUBLIC, that may connect to the
    database, as its rights say."""
    rows = connection.exec_driver_sql(
        "SELECT DISTINCT pg_get_userbyid(acl.grantee) FROM pg_database d,"
        " aclexplode(d.datacl) acl WHERE d.datname = current_database()"
        " AND acl.privilege_type = 'CONNECT' AND acl.grantee <> 0"
        " AND acl.grantee <> d.datdba"
    )
    return sorted(str(row[0]) for row in rows)
