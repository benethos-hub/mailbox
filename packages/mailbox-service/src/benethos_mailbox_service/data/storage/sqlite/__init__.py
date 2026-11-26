"""The file of SQLite: its connection, the steps of its schema up to 26
and the files SQLite keeps beside it. The only package that imports
``sqlite3``."""

from __future__ import annotations

from . import file
from .file import (
    inspect_bytes,
    inspect_file,
    move_sidecars,
    remove_database_file,
    service_lock,
)
from .migrations import SCHEMA_VERSION

__all__ = [
    "SCHEMA_VERSION",
    "file",
    "inspect_bytes",
    "inspect_file",
    "move_sidecars",
    "remove_database_file",
    "service_lock",
]
