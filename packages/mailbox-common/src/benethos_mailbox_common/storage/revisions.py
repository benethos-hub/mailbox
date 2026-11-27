"""The steps of a schema as revisions of Alembic, driven inside the
process: one module per step in the folder of a program's revisions,
run on the connection the database holds, each in a transaction of its
own. Only forward.

``meta.schema_version`` stays the one number of a schema: every revision
writes it after its step, and the mark Alembic keeps in
``alembic_version`` follows it. There is no ``alembic.ini``: what
Alembic runs a command with is ``_alembic/env.py`` beside this module.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .revision import NOTES, Revision, name_of

# Where Alembic finds what it runs a command with.
ENVIRONMENT = Path(__file__).parent / "_alembic"

# Alembic says at INFO what it does. A library speaks from WARNING on,
# also where nobody set up the log of the program: the program names a
# migration itself, at start.
logging.getLogger("alembic").setLevel(logging.WARNING)


class Revisions:
    """The revisions in the folder ``versions``."""

    def __init__(self, versions: Path) -> None:
        self._versions = versions

    def upgrade(self, conn: sa.Connection, version: int) -> list[str]:
        """The revisions up to the one of schema ``version`` on ``conn``,
        which is in no transaction. Each runs in a transaction of its
        own, so one that fails leaves the schema where the one before
        left it. Answers what the revisions noted."""
        return self._run(conn, lambda config: command.upgrade(config, name_of(version)))

    def stamp(self, conn: sa.Connection, version: int) -> None:
        """Mark ``conn`` as at the revision of schema ``version``, without
        running it: for a database the steps of its file brought there."""
        self._run(conn, lambda config: command.stamp(config, name_of(version)))

    def numbers(self) -> list[int]:
        """The schema of every revision, in order."""
        found = ScriptDirectory.from_config(self._config()).walk_revisions()
        return sorted(int(script.revision) for script in found)

    def pending(self, after: int, upto: int) -> list[type[Revision]]:
        """The revisions a database at schema ``after`` runs to reach
        ``upto``, in order. A base of the program's own, abstract, is no
        revision."""
        found = ScriptDirectory.from_config(self._config()).walk_revisions()
        steps = [
            step
            for script in found
            if after < int(script.revision) <= upto
            for step in vars(script.module).values()
            if isinstance(step, type)
            and issubclass(step, Revision)
            and not inspect.isabstract(step)
        ]
        return sorted(steps, key=lambda step: step.version)

    @staticmethod
    def mark(conn: sa.Connection) -> int | None:
        """The schema of the revision ``conn`` is marked at, None without
        a mark."""
        with conn.begin():
            current = MigrationContext.configure(conn).get_current_revision()
        return None if current is None else int(current)

    def _config(self) -> Config:
        config = Config()
        config.set_main_option("path_separator", "os")
        config.set_main_option("script_location", str(ENVIRONMENT))
        config.set_main_option("version_locations", str(self._versions))
        return config

    def _run(self, conn: sa.Connection, step: Callable[[Config], None]) -> list[str]:
        config = self._config()
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
