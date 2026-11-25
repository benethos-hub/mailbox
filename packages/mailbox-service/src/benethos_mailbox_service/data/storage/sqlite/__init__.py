"""SQLite persistence, one module per subject. The only package that imports
``sqlite3``."""

from __future__ import annotations

from .file import (
    Migrated,
    inspect_file,
    migrate_file,
    move_sidecars,
    remove_database_file,
    service_lock,
)
from .index import SqliteMessageIndexRepository
from .migrations import SCHEMA_VERSION
from .tables import Table

__all__ = [
    "SCHEMA_VERSION",
    "Migrated",
    "SqliteMessageIndexRepository",
    "Table",
    "inspect_file",
    "migrate_file",
    "move_sidecars",
    "remove_database_file",
    "service_lock",
]
