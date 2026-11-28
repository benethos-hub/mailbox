"""What a role finds on a server it reads: the databases it may connect
to, and in one of them the schemas where it may read a table of a name,
given to a role it holds and not to PUBLIC alone.
A program that reads the databases of others, such as a cockpit, finds
them so, signed in with its own role, without a right beyond reading.

Each call takes a short connection of its own, in transactions that
only read. A failure is named by its kind, never by a value.
"""

from __future__ import annotations

import sqlalchemy as sa

from .server_engine import Server, engine_for
from .server_place import translated_server
from .shape import Shape

_DATABASES = sa.text(
    "SELECT datname FROM pg_database"
    " WHERE NOT datistemplate AND datallowconn"
    " AND has_database_privilege(datname, 'CONNECT')"
    " ORDER BY datname"
)
_SCHEMAS = sa.text(
    "SELECT n.nspname FROM pg_class c"
    " JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE c.relname = :table AND c.relkind IN ('r', 'p')"
    " AND has_schema_privilege(n.oid, 'USAGE')"
    " AND has_table_privilege(c.oid, 'SELECT')"
    # Given to a role it holds, not to PUBLIC alone: a table open to
    # everyone is no state given to this reader.
    " AND EXISTS (SELECT 1 FROM aclexplode(c.relacl) a"
    " WHERE a.privilege_type = 'SELECT' AND a.grantee <> 0"
    " AND pg_has_role(a.grantee, 'USAGE'))"
    " ORDER BY n.nspname"
)


def readable_databases(server: Server, shape: Shape) -> list[str]:
    """The databases on ``server`` its role may connect to, by name,
    templates left out. The errors are those of ``shape``."""
    return [str(name) for name in _rows(server, shape, _DATABASES, {})]


def schemas_holding(server: Server, table: str, shape: Shape) -> list[str]:
    """The schemas of the database of ``server`` where its role may read
    a table named ``table``, by name."""
    return [str(name) for name in _rows(server, shape, _SCHEMAS, {"table": table})]


def _rows(
    server: Server, shape: Shape, query: sa.TextClause, values: dict[str, str]
) -> list[object]:
    errors = shape.errors
    engine = engine_for(server, shape, read_only=True)
    try:
        with translated_server(errors), engine.connect() as connection:
            return list(connection.execute(query, values).scalars())
    finally:
        engine.dispose()
