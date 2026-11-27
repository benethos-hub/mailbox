"""The state file before the revisions: its PRAGMAs, and the old steps
of its schema up to 5, on ``sqlite3``, as the ``file_steps`` of the
shape of the state file.

Every time the file opens, it is put in WAL mode, so readers such as
``report`` and the cockpit read beside the writer. A file of an older
schema is brought to 5 by the old steps, each in a transaction of its
own with its ``user_version``, a copy kept before the last of them. A
new file is left to the revisions, which make it at 5.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from benethos_mailbox_common.storage import migrated, sqlite_file

from ..errors import STATE_ERRORS, ConfigError
from .migrations import MIGRATIONS

# A copy of the file before the step that hands it to the revisions.
COPY_BEFORE = MIGRATIONS.schema_version


def newer(found: int, known: int) -> ConfigError:
    """The error of a state file of a schema this program does not know."""
    return ConfigError(
        f"the state file is at schema version {found}, this program knows {known}"
    )


class OldSteps:
    """The PRAGMAs of the state file, and its steps up to schema 5."""

    last = MIGRATIONS.schema_version

    def run(
        self,
        connection: sqlite3.Connection,
        path: Path | None,
        upto: int,
        newest: int,
        keep: bool,
        rewritten: bool,
    ) -> migrated.Migrated | None:
        errors = STATE_ERRORS
        with sqlite_file.translated_sqlite(errors):
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            current: int = connection.execute("PRAGMA user_version").fetchone()[0]
        notes = (
            ["the file was rewritten once: from now on it shrinks after deletions"]
            if rewritten
            else []
        )
        if sqlite_file.has_meta(connection, errors):
            held = sqlite_file.schema_version(connection, errors)
            if held > newest:
                raise newer(held, newest)
            return migrated.Migrated(held, held, tuple(notes)) if notes else None
        if current == 0:
            # A new file: the revisions make it, from their baseline on.
            return None
        if current > self.last:
            raise newer(current, newest)
        kept = None
        if keep and path is not None and current < COPY_BEFORE:
            kept = sqlite_file.keep_copy(connection, path, current, COPY_BEFORE, errors)
        for step in MIGRATIONS.pending(current):
            with sqlite_file.in_step(connection, errors) as db:
                notes += [f"schema {step.version}: {n}" for n in step.apply(db)]
                db.execute(f"PRAGMA user_version = {step.version}")
        if kept is not None:
            notes.append(
                f"a copy of the state file at schema {current} is kept: {kept}"
            )
        return migrated.Migrated(current, self.last, tuple(notes))


# The steps of every state file.
OLD_STEPS = OldSteps()
