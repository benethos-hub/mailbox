"""The storage of a program on SQLAlchemy Core, for a file of SQLite and a
schema on a PostgreSQL server, and the steps of its schema as revisions
of Alembic. A group with libraries, SQLAlchemy and Alembic, in the extra
``storage``. The driver of PostgreSQL comes with the extra ``postgres``.
Callers import the modules from here,
``from benethos_mailbox_common.storage import dialect``."""

from __future__ import annotations

try:
    import alembic
    import sqlalchemy
except ModuleNotFoundError as missing:
    raise ModuleNotFoundError(
        "benethos_mailbox_common.storage needs the extra storage: "
        "pip install 'benethos-mailbox-common[storage]'",
        name=missing.name,
    ) from missing

from . import clock, dialect, files, migrated, names

del alembic, sqlalchemy

__all__ = ["clock", "dialect", "files", "migrated", "names"]
