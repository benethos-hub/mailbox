"""The steps of the schema from schema 26 on, as revisions of Alembic: one
module per step in ``versions/``, named and numbered after the schema it
reaches, run inside the process on the connection the database holds,
each in a transaction of its own. Only forward.

The steps up to schema 26 stay in ``sqlite/migrations/``, closed.
``meta.schema_version`` stays the one number of a schema: every revision
ends by writing it (``written``), and the mark Alembic keeps in
``alembic_version`` follows it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa
from alembic import command, op
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from ..dialect import TEXT, insert_or_update

HERE = Path(__file__).parent

# The schema the first revision makes, the last step of the old chain.
BASELINE = 26
# The schema the last revision makes: the schema of this version.
SCHEMA_VERSION = 26

# The table meta as every revision writes it, apart from the definitions,
# which may change after a revision is frozen.
_META = sa.Table(
    "meta",
    sa.MetaData(),
    sa.Column("key", TEXT, primary_key=True),
    sa.Column("value", TEXT),
)


def name_of(version: int) -> str:
    """The name of the revision that makes schema ``version``."""
    return f"{version:04d}"


def upgrade(conn: sa.Connection, version: int, *, versions: Path | None = None) -> None:
    """The revisions up to the one of schema ``version`` on ``conn``, which
    is in no transaction. Each runs in a transaction of its own, so one
    that fails leaves the schema where the one before left it.
    ``versions``: the revisions of another folder, for a test."""
    _run(conn, lambda config: command.upgrade(config, name_of(version)), versions)


def stamp(conn: sa.Connection, version: int, *, versions: Path | None = None) -> None:
    """Mark ``conn`` as at the revision of schema ``version``, without
    running it: for a database the old chain brought there."""
    _run(conn, lambda config: command.stamp(config, name_of(version)), versions)


def mark(conn: sa.Connection) -> int | None:
    """The schema of the revision ``conn`` is marked at, None without a
    mark."""
    with conn.begin():
        current = MigrationContext.configure(conn).get_current_revision()
    return None if current is None else int(current)


def written(version: int) -> None:
    """``meta.schema_version`` at ``version``. Every revision ends with
    it, in its own transaction."""
    bind = op.get_bind()
    bind.execute(
        insert_or_update(_META, ["key"], ["value"], bind.dialect).values(
            key="schema_version", value=str(version)
        )
    )


def _run(
    conn: sa.Connection,
    step: Callable[[Config], None],
    versions: Path | None,
) -> None:
    config = Config()
    config.set_main_option("path_separator", "os")
    config.set_main_option("script_location", str(HERE))
    if versions is not None:
        config.set_main_option("version_locations", str(versions))
    config.attributes["connection"] = conn
    try:
        step(config)
    except BaseException:
        # Reading the mark began a transaction around the steps.
        if conn.in_transaction():
            conn.rollback()
        raise
    if conn.in_transaction():
        conn.commit()
