"""Persistence, split by subject. Callers import from here, not the modules."""

from __future__ import annotations

from .accounts import AccountRepository, InMemoryAccountRepository
from .credentials import (
    CredentialRepository,
    EncryptedCredential,
    InMemoryCredentialRepository,
    InMemoryKeyRepository,
    KeyRepository,
    WrappedKey,
)
from .index import (
    IndexChanges,
    IndexEntry,
    InMemoryMessageIndexRepository,
    MessageIndexRepository,
)
from .sqlite import (
    Database,
    SqliteAccountRepository,
    SqliteCredentialRepository,
    SqliteKeyRepository,
    SqliteMessageIndexRepository,
    SqliteRoleRepository,
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

__all__ = [
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
