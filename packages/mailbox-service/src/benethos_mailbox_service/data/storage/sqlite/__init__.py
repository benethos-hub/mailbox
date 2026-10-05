"""SQLite persistence, one module per subject. The only package that imports
``sqlite3``."""

from __future__ import annotations

from .accounts import SqliteAccountRepository
from .audit import SqliteAuditRepository
from .changes import SqliteChangeLogRepository
from .credentials import SqliteCredentialRepository, SqliteKeyRepository
from .database import (
    SCHEMA_VERSION,
    Database,
    Migrated,
    inspect_snapshot,
    migrate_file,
    service_lock,
)
from .idempotency import SqliteIdempotencyRepository
from .index import SqliteMessageIndexRepository
from .passwords import SqlitePasswordRepository
from .sends import SqliteSendLogRepository
from .users import SqliteRoleRepository, SqliteTokenRepository, SqliteUserRepository
from .webhooks import SqliteWebhookRepository

__all__ = [
    "SCHEMA_VERSION",
    "Database",
    "Migrated",
    "SqliteAccountRepository",
    "SqliteChangeLogRepository",
    "SqliteCredentialRepository",
    "SqliteIdempotencyRepository",
    "SqliteKeyRepository",
    "SqliteMessageIndexRepository",
    "SqlitePasswordRepository",
    "SqliteRoleRepository",
    "SqliteAuditRepository",
    "SqliteSendLogRepository",
    "SqliteTokenRepository",
    "SqliteUserRepository",
    "SqliteWebhookRepository",
    "inspect_snapshot",
    "migrate_file",
    "service_lock",
]
