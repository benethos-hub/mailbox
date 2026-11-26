"""The steps of the schema from schema 26 on, as revisions of Alembic: one
module per step in ``versions/``, a class of ``Revision`` named and
numbered after the schema it reaches (``revision.py``), run inside the
process on the connection the database holds, each in a transaction of
its own. Only forward.

The steps up to schema 26 stay in ``sqlite/migrations/``, closed.
``meta.schema_version`` stays the one number of a schema: every revision
writes it after its step, and the mark Alembic keeps in
``alembic_version`` follows it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .revision import BASELINE, NOTES, Revision, name_of

HERE = Path(__file__).parent
# The revisions of the service.
VERSIONS = HERE / "versions"

# Alembic says at INFO what it does. A library speaks from WARNING on,
# also where nobody set up the log of the service: the service names a
# migration itself, at start.
logging.getLogger("alembic").setLevel(logging.WARNING)

# The schema the last revision makes: the schema of this version.
SCHEMA_VERSION = 26


def upgrade(
    conn: sa.Connection, version: int, *, versions: Path | None = None
) -> list[str]:
    """The revisions up to the one of schema ``version`` on ``conn``, which
    is in no transaction. Each runs in a transaction of its own, so one
    that fails leaves the schema where the one before left it. Answers
    what the revisions noted. ``versions``: the revisions of another
    folder, for a test."""
    return _run(
        conn, lambda config: command.upgrade(config, name_of(version)), versions
    )


def stamp(conn: sa.Connection, version: int, *, versions: Path | None = None) -> None:
    """Mark ``conn`` as at the revision of schema ``version``, without
    running it: for a database the old chain brought there."""
    _run(conn, lambda config: command.stamp(config, name_of(version)), versions)


def numbers(*, versions: Path | None = None) -> list[int]:
    """The schema of every revision, in order."""
    found = ScriptDirectory.from_config(_config(versions)).walk_revisions()
    return sorted(int(script.revision) for script in found)


def pending(
    after: int, upto: int, *, versions: Path | None = None
) -> list[type[Revision]]:
    """The revisions a database at schema ``after`` runs to reach
    ``upto``, in order."""
    found = ScriptDirectory.from_config(_config(versions)).walk_revisions()
    steps = [
        step
        for script in found
        if after < int(script.revision) <= upto
        for step in vars(script.module).values()
        if isinstance(step, type)
        and issubclass(step, Revision)
        and step is not Revision
    ]
    return sorted(steps, key=lambda step: step.version)


def mark(conn: sa.Connection) -> int | None:
    """The schema of the revision ``conn`` is marked at, None without a
    mark."""
    with conn.begin():
        current = MigrationContext.configure(conn).get_current_revision()
    return None if current is None else int(current)


def _config(versions: Path | None = None) -> Config:
    config = Config()
    config.set_main_option("path_separator", "os")
    config.set_main_option("script_location", str(HERE))
    config.set_main_option("version_locations", str(versions or VERSIONS))
    return config


def _run(
    conn: sa.Connection,
    step: Callable[[Config], None],
    versions: Path | None,
) -> list[str]:
    config = _config(versions)
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
    notes: list[str] = config.attributes.get(NOTES, [])
    return notes


__all__ = [
    "BASELINE",
    "HERE",
    "SCHEMA_VERSION",
    "VERSIONS",
    "Revision",
    "mark",
    "name_of",
    "numbers",
    "pending",
    "stamp",
    "upgrade",
]
