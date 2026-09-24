"""SQLite persistence, one module per subject. The only package that imports
``sqlite3``."""

from __future__ import annotations

from .accounts import SqliteAccountRepository
from .credentials import SqliteCredentialRepository, SqliteKeyRepository
from .database import SCHEMA_VERSION, Database, inspect_snapshot
from .idempotency import SqliteIdempotencyRepository
from .index import SqliteMessageIndexRepository
from .users import SqliteRoleRepository, SqliteTokenRepository, SqliteUserRepository

__all__ = [
    "SCHEMA_VERSION",
    "Database",
    "SqliteAccountRepository",
    "SqliteCredentialRepository",
    "SqliteIdempotencyRepository",
    "SqliteKeyRepository",
    "SqliteMessageIndexRepository",
    "SqliteRoleRepository",
    "SqliteTokenRepository",
    "SqliteUserRepository",
    "inspect_snapshot",
]
