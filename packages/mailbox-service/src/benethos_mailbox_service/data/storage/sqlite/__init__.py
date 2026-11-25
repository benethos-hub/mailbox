"""SQLite persistence, one module per subject. The only package that imports
``sqlite3``."""

from __future__ import annotations

from .audit import SqliteAuditRepository
from .changes import SqliteChangeLogRepository
from .credentials import SqliteCredentialRepository, SqliteKeyRepository
from .file import (
    Migrated,
    inspect_file,
    migrate_file,
    move_sidecars,
    remove_database_file,
    service_lock,
)
from .idempotency import SqliteIdempotencyRepository
from .index import SqliteMessageIndexRepository
from .links import SqliteLinkRepository
from .migrations import SCHEMA_VERSION
from .outbox import SqliteOutboxRepository
from .passkeys import SqlitePasskeyRepository
from .recovery_codes import SqliteRecoveryCodeRepository
from .sends import SqliteSendLogRepository
from .tables import Table
from .totp import SqliteTotpRepository
from .webhooks import SqliteWebhookRepository

__all__ = [
    "SCHEMA_VERSION",
    "Migrated",
    "SqliteChangeLogRepository",
    "SqliteCredentialRepository",
    "SqliteIdempotencyRepository",
    "SqliteKeyRepository",
    "SqliteLinkRepository",
    "SqliteMessageIndexRepository",
    "SqliteOutboxRepository",
    "SqliteAuditRepository",
    "SqliteRecoveryCodeRepository",
    "SqlitePasskeyRepository",
    "SqliteTotpRepository",
    "SqliteSendLogRepository",
    "SqliteWebhookRepository",
    "Table",
    "inspect_file",
    "migrate_file",
    "move_sidecars",
    "remove_database_file",
    "service_lock",
]
