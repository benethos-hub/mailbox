"""The steps of the schema of the service from schema 26 on, as revisions
of Alembic: one module per step in ``versions/``, a class of the base
``Revision`` (``revision.py``) named and numbered after the schema it
reaches, run inside the process by the storage of mailbox-common.

The steps up to schema 26 stay in ``sqlite/migrations/``, closed.
"""

from __future__ import annotations

from pathlib import Path

from benethos_mailbox_common.storage import dialect, revisions

from .revision import BASELINE, Revision

# The revisions of the service.
VERSIONS = Path(__file__).parent / "versions"
# The schema the last revision makes: the schema of this version.
SCHEMA_VERSION = 26
# Them, to run.
REVISIONS = revisions.Revisions(VERSIONS)

# The types a revision writes its tables with, from where a revision
# takes them.
BYTES, COUNTED, NUMBER, TEXT = (
    dialect.BYTES,
    dialect.COUNTED,
    dialect.NUMBER,
    dialect.TEXT,
)
counter = dialect.counter

__all__ = [
    "BASELINE",
    "BYTES",
    "COUNTED",
    "NUMBER",
    "REVISIONS",
    "SCHEMA_VERSION",
    "TEXT",
    "VERSIONS",
    "Revision",
    "counter",
]
