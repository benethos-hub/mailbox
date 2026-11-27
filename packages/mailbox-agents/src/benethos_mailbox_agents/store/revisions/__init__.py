"""The steps of the schema of the state file from schema 5 on, as
revisions of Alembic: one module per step in ``versions/``, a class of
the base ``Revision`` (``revision.py``) named and numbered after the
schema it reaches, run inside the process by the storage of
mailbox-common, on a file as on a server.

The steps up to schema 5 stay in ``migrations/``, on ``sqlite3``,
closed.
"""

from __future__ import annotations

from pathlib import Path

from benethos_mailbox_common.storage import dialect, revisions

from .revision import BASELINE, Revision

# The revisions of the state file.
VERSIONS = Path(__file__).parent / "versions"
# The schema the last revision makes: the schema of this version.
SCHEMA_VERSION = 5
# Them, to run.
REVISIONS = revisions.Revisions(VERSIONS)

# The types a revision writes its tables with, from where a revision
# takes them.
NUMBER, TEXT = dialect.NUMBER, dialect.TEXT

__all__ = [
    "BASELINE",
    "NUMBER",
    "REVISIONS",
    "SCHEMA_VERSION",
    "TEXT",
    "VERSIONS",
    "Revision",
]
