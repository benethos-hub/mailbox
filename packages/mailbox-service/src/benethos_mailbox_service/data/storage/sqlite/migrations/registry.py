"""The registry of the migrations: every step in order, the schema
version they reach, and the table ``meta`` that says which version a
database has."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from .migration import Migration

_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"


class MigrationRegistry:
    """The steps from an empty database to the current schema, numbered
    from 1 without a gap. Each one is run in a transaction of its own,
    which the database opens, and recorded in ``meta`` as it commits."""

    def __init__(self, *steps: Migration) -> None:
        for number, step in enumerate(steps, 1):
            if step.version != number:
                raise ValueError(
                    f"{type(step).__name__} says version {step.version}"
                    f" but stands at {number}"
                )
        self._steps = steps

    def __iter__(self) -> Iterator[Migration]:
        return iter(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    @property
    def schema_version(self) -> int:
        """The version the last step reaches."""
        return len(self._steps)

    def step(self, version: int) -> Migration:
        """The step that reaches ``version``."""
        if not 1 <= version <= len(self._steps):
            raise ValueError(f"there is no migration to schema {version}")
        return self._steps[version - 1]

    def pending(self, current: int) -> tuple[Migration, ...]:
        """The steps a database at ``current`` has still to run."""
        return self._steps[current:]

    def prepare(self, db: sqlite3.Connection) -> None:
        """The table ``meta``, if the database has none yet."""
        db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def version_of(self, db: sqlite3.Connection) -> int:
        """The schema version ``db`` has, 0 before the first step."""
        row = db.execute(_VERSION).fetchone()
        return int(row[0]) if row else 0

    def apply(self, db: sqlite3.Connection, migration: Migration) -> list[str]:
        """Runs ``migration`` on ``db`` and records its version. What the
        step had to say, each note named with the version."""
        said = migration.apply(db)
        db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(migration.version),),
        )
        return [f"schema {migration.version}: {note}" for note in said]
