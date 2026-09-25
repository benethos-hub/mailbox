"""Persistence, split by subject. Callers import from here, not the modules.

``open_repositories`` is the one place that picks the implementation:
in memory for tests and ``storage = memory``, else SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .accounts import AccountRepository, InMemoryAccountRepository
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
)
from .sends import InMemorySendLogRepository, SendLogRepository
from .sqlite import (
    Database,
    SqliteAccountRepository,
    SqliteChangeLogRepository,
    SqliteCredentialRepository,
    SqliteIdempotencyRepository,
    SqliteKeyRepository,
    SqliteMessageIndexRepository,
    SqliteRoleRepository,
    SqliteSendLogRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
    inspect_snapshot,
)
from .users import (
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
    RoleRepository,
    TokenRepository,
    UserRepository,
)


@dataclass(frozen=True)
class Repositories:
    """One of each, on the same store."""

    accounts: AccountRepository
    users: UserRepository
    roles: RoleRepository
    tokens: TokenRepository
    keys: KeyRepository
    credentials: CredentialRepository
    index: MessageIndexRepository
    idempotency: IdempotencyRepository
    sends: SendLogRepository
    changes: ChangeLogRepository
    # The database behind them, for backups and for closing. None in memory.
    database: Database | None = None

    def close(self) -> None:
        if self.database is not None:
            self.database.close()


def open_repositories(
    storage: Literal["memory", "sqlite"], database_path: Path
) -> Repositories:
    if storage == "memory":
        return Repositories(
            accounts=InMemoryAccountRepository(),
            users=InMemoryUserRepository(),
            roles=InMemoryRoleRepository(),
            tokens=InMemoryTokenRepository(),
            keys=InMemoryKeyRepository(),
            credentials=InMemoryCredentialRepository(),
            index=InMemoryMessageIndexRepository(),
            idempotency=InMemoryIdempotencyRepository(),
            sends=InMemorySendLogRepository(),
            changes=InMemoryChangeLogRepository(),
        )
    db = Database(database_path)
    return Repositories(
        accounts=SqliteAccountRepository(db),
        users=SqliteUserRepository(db),
        roles=SqliteRoleRepository(db),
        tokens=SqliteTokenRepository(db),
        keys=SqliteKeyRepository(db),
        credentials=SqliteCredentialRepository(db),
        index=SqliteMessageIndexRepository(db),
        idempotency=SqliteIdempotencyRepository(db),
        sends=SqliteSendLogRepository(db),
        changes=SqliteChangeLogRepository(db),
        database=db,
    )


__all__ = [
    "Repositories",
    "open_repositories",
    "ChangeLogRepository",
    "InMemoryChangeLogRepository",
    "LoggedChange",
    "SqliteChangeLogRepository",
    "IdempotencyRepository",
    "InMemoryIdempotencyRepository",
    "SqliteIdempotencyRepository",
    "StoredResult",
    "IndexChanges",
    "IndexEntry",
    "InMemoryMessageIndexRepository",
    "MessageIndexRepository",
    "SqliteMessageIndexRepository",
    "CredentialRepository",
    "EncryptedCredential",
    "InMemoryCredentialRepository",
    "InMemoryKeyRepository",
    "KeyRepository",
    "SqliteCredentialRepository",
    "SqliteKeyRepository",
    "WrappedKey",
    "inspect_snapshot",
    "AccountRepository",
    "Database",
    "SqliteAccountRepository",
    "SqliteRoleRepository",
    "SqliteSendLogRepository",
    "InMemorySendLogRepository",
    "SendLogRepository",
    "SqliteTokenRepository",
    "SqliteUserRepository",
    "InMemoryAccountRepository",
    "InMemoryRoleRepository",
    "InMemoryTokenRepository",
    "InMemoryUserRepository",
    "RoleRepository",
    "TokenRepository",
    "UserRepository",
]
