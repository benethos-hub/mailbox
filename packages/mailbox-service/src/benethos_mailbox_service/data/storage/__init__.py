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
    ThreadChain,
)
from .links import InMemoryLinkRepository, LinkRepository, StoredLink
from .outbox import InMemoryOutboxRepository, OutboxRepository
from .passkeys import InMemoryPasskeyRepository, PasskeyRepository, StoredPasskey
from .passwords import InMemoryPasswordRepository, PasswordRepository, StoredPassword
from .recovery_codes import InMemoryRecoveryCodeRepository, RecoveryCodeRepository
from .repositories import (
    Records,
    Repositories,
    Store,
    open_repositories,
    repositories_on,
)
from .sends import InMemorySendLogRepository, SendLogRepository
from .sql import (
    SqlAccountRepository,
    SqlAuditRepository,
    SqlChangeLogRepository,
    SqlIdempotencyRepository,
    SqlLinkRepository,
    SqlMessageIndexRepository,
    SqlOutboxRepository,
    SqlPasskeyRepository,
    SqlPasswordRepository,
    SqlRecoveryCodeRepository,
    SqlRoleRepository,
    SqlSendLogRepository,
    SqlTokenRepository,
    SqlTotpRepository,
    SqlUserRepository,
    SqlWebhookRepository,
)
from .sql.database import Database, migrate_file
from .sql.outage import Availability
from .sql.revisions import SCHEMA_VERSION
from .sql.server_place import Server, ServerPlace
from .sql.tables import Table
from .sqlite import (
    inspect_bytes,
    inspect_file,
    move_sidecars,
    remove_database_file,
    service_lock,
)
from .totp import InMemoryTotpRepository, StoredTotpDevice, TotpRepository
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
    "Availability",
    "AuditRepository",
    "InMemoryAuditRepository",
    "SqlAuditRepository",
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
    "InMemoryLinkRepository",
    "InMemoryMessageIndexRepository",
    "InMemoryOutboxRepository",
    "InMemoryPasswordRepository",
    "InMemoryRoleRepository",
    "InMemoryRecoveryCodeRepository",
    "InMemoryPasskeyRepository",
    "InMemoryTotpRepository",
    "InMemorySendLogRepository",
    "InMemoryTokenRepository",
    "InMemoryUserRepository",
    "InMemoryWebhookRepository",
    "IndexChanges",
    "IndexEntry",
    "KeyRepository",
    "LinkRepository",
    "LoggedChange",
    "MessageIndexRepository",
    "OutboxRepository",
    "ThreadChain",
    "PasswordRepository",
    "Records",
    "Repositories",
    "RoleRepository",
    "SCHEMA_VERSION",
    "Sealed",
    "Server",
    "ServerPlace",
    "RecoveryCodeRepository",
    "SendLogRepository",
    "SqlAccountRepository",
    "SqlChangeLogRepository",
    "SqlIdempotencyRepository",
    "SqlLinkRepository",
    "SqlMessageIndexRepository",
    "SqlOutboxRepository",
    "SqlPasswordRepository",
    "SqlRoleRepository",
    "SqlRecoveryCodeRepository",
    "SqlPasskeyRepository",
    "SqlTotpRepository",
    "SqlSendLogRepository",
    "SqlTokenRepository",
    "SqlUserRepository",
    "SqlWebhookRepository",
    "Table",
    "Store",
    "StoredPasskey",
    "StoredTotpDevice",
    "StoredPassword",
    "StoredLink",
    "StoredResult",
    "TokenRepository",
    "PasskeyRepository",
    "TotpRepository",
    "UserRepository",
    "WebhookRecord",
    "WebhookRepository",
    "WrappedKey",
    "inspect_bytes",
    "inspect_file",
    "migrate_file",
    "move_sidecars",
    "open_repositories",
    "repositories_on",
    "remove_database_file",
    "service_lock",
]
