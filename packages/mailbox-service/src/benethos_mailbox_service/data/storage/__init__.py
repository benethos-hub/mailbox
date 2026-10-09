"""Persistence, split by subject. Callers import from here, not the modules.

``repositories`` holds them together and picks the implementation, a
protocol and an in-memory implementation per subject sit in a module of
their own, SQLite in ``sqlite/``, the in-memory base in ``table``.
"""

from __future__ import annotations

from .accounts import AccountRepository, InMemoryAccountRepository
from .audit import AuditRepository, InMemoryAuditRepository
from .changes import ChangeLogRepository, InMemoryChangeLogRepository, LoggedChange
from .credentials import (
    CredentialRepository,
    EncryptedCredential,
    InMemoryCredentialRepository,
    InMemoryKeyRepository,
    KeyRepository,
    WrappedKey,
)
from .factors import (
    InMemorySecondFactorRepository,
    SecondFactorRepository,
    StoredDevice,
)
from .idempotency import (
    IdempotencyRepository,
    InMemoryIdempotencyRepository,
    StoredResult,
)
from .index import (
    IndexChanges,
    IndexEntry,
    InMemoryMessageIndexRepository,
    MessageIndexRepository,
)
from .passwords import InMemoryPasswordRepository, PasswordRepository, StoredPassword
from .repositories import Repositories, Store, open_repositories
from .sends import InMemorySendLogRepository, SendLogRepository
from .sqlite import (
    SCHEMA_VERSION,
    Database,
    SqliteAccountRepository,
    SqliteAuditRepository,
    SqliteChangeLogRepository,
    SqliteIdempotencyRepository,
    SqliteMessageIndexRepository,
    SqlitePasswordRepository,
    SqliteRoleRepository,
    SqliteSecondFactorRepository,
    SqliteSendLogRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
    SqliteWebhookRepository,
    inspect_file,
    migrate_file,
    service_lock,
)
from .users import (
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
    RoleRepository,
    TokenRepository,
    UserRepository,
)
from .webhooks import (
    Attempt,
    Delivery,
    InMemoryWebhookRepository,
    Sealed,
    WebhookRecord,
    WebhookRepository,
)

__all__ = [
    "AuditRepository",
    "InMemoryAuditRepository",
    "SqliteAuditRepository",
    "AccountRepository",
    "Attempt",
    "ChangeLogRepository",
    "CredentialRepository",
    "Database",
    "Delivery",
    "EncryptedCredential",
    "IdempotencyRepository",
    "InMemoryAccountRepository",
    "InMemoryChangeLogRepository",
    "InMemoryCredentialRepository",
    "InMemoryIdempotencyRepository",
    "InMemoryKeyRepository",
    "InMemoryMessageIndexRepository",
    "InMemoryPasswordRepository",
    "InMemoryRoleRepository",
    "InMemorySecondFactorRepository",
    "InMemorySendLogRepository",
    "InMemoryTokenRepository",
    "InMemoryUserRepository",
    "InMemoryWebhookRepository",
    "IndexChanges",
    "IndexEntry",
    "KeyRepository",
    "LoggedChange",
    "MessageIndexRepository",
    "PasswordRepository",
    "Repositories",
    "RoleRepository",
    "SCHEMA_VERSION",
    "Sealed",
    "SecondFactorRepository",
    "SendLogRepository",
    "SqliteAccountRepository",
    "SqliteChangeLogRepository",
    "SqliteIdempotencyRepository",
    "SqliteMessageIndexRepository",
    "SqlitePasswordRepository",
    "SqliteRoleRepository",
    "SqliteSecondFactorRepository",
    "SqliteSendLogRepository",
    "SqliteTokenRepository",
    "SqliteUserRepository",
    "SqliteWebhookRepository",
    "Store",
    "StoredDevice",
    "StoredPassword",
    "StoredResult",
    "TokenRepository",
    "UserRepository",
    "WebhookRecord",
    "WebhookRepository",
    "WrappedKey",
    "inspect_file",
    "migrate_file",
    "open_repositories",
    "service_lock",
]
