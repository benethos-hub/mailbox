"""What the checks of the agents do on the test database of our own
(``common.test_database``): the databases and roles a check made
dropped at its end."""

from __future__ import annotations

from common.test_database import Administrator, connected
from psycopg import sql


def dropped(admin: Administrator, databases: list[str], roles: list[str]) -> None:
    """The databases and then the roles gone, those not there skipped."""
    with connected(admin) as conn:
        for name in databases:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
        for name in roles:
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))
