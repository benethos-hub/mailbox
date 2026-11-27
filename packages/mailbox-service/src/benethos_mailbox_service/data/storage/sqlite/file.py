"""The old steps of the schema of the service's database file, up to
schema 26, closed: a file of an older schema is brought there by them
when it opens, with a copy kept before schema ``COPY_BEFORE``. A new
database is left to the revisions. The file itself, its connection and
what SQLite keeps beside it are the storage of mailbox-common
(``sqlite_file``), which runs these steps as the ``file_steps`` of the
service's shape.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from benethos_mailbox_common.storage import migrated, sqlite_file

from ....errors import STORAGE_ERRORS
from .migrations import MIGRATIONS, SCHEMA_VERSION

# Opening a database of an older schema keeps a copy of it first: the
# step to this schema rebuilds tables (docs/mailbox-service/concept/security.md 7.8).
COPY_BEFORE = 26


class OldSteps:
    """The steps of a file of the service up to schema 26."""

    last = SCHEMA_VERSION

    def run(
        self,
        connection: sqlite3.Connection,
        path: Path | None,
        upto: int,
        newest: int,
        keep: bool,
        rewritten: bool,
    ) -> migrated.Migrated | None:
        """``rewritten``: the file was rewritten to shrink from now on,
        said with the notes of the schema."""
        errors = STORAGE_ERRORS
        if upto >= SCHEMA_VERSION and not sqlite_file.has_meta(connection, errors):
            # A new database: the revisions make it, from their baseline on.
            if upto > newest:
                raise errors.failed(f"there is no way from schema 0 to {upto}")
            return None
        with sqlite_file.in_step(connection, errors) as db:
            MIGRATIONS.prepare(db)
        with sqlite_file.translated_sqlite(errors):
            current = MIGRATIONS.version_of(connection)
        if current > newest:
            raise errors.failed(
                f"database schema {current} is newer than this version supports "
                f"({newest}): run a newer version of the service"
            )
        if not current <= upto <= newest:
            raise errors.failed(f"there is no way from schema {current} to {upto}")
        upto = min(upto, SCHEMA_VERSION)
        kept = None
        if keep and path is not None and 0 < current < COPY_BEFORE:
            kept = sqlite_file.keep_copy(connection, path, current, COPY_BEFORE, errors)
        notes: list[str] = []
        for step in MIGRATIONS.pending(current)[: max(upto - current, 0)]:
            with sqlite_file.in_step(connection, errors) as db:
                notes += MIGRATIONS.apply(db, step)
        if kept is not None:
            notes.append(f"a copy of the database at schema {current} is kept: {kept}")
        if rewritten:
            notes.append(
                "the file was rewritten once: from now on it shrinks after deletions"
            )
        if current < upto or rewritten:
            return migrated.Migrated(current, upto, tuple(notes))
        return None


# The steps of every file of the service.
OLD_STEPS = OldSteps()
