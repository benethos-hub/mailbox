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
from .sqlite import (
    Database,
    SqliteAccountRepository,
    SqliteCredentialRepository,
    SqliteKeyRepository,
    SqliteRoleRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
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
    "CredentialRepository",
    "EncryptedCredential",
    "InMemoryCredentialRepository",
    "InMemoryKeyRepository",
    "KeyRepository",
    "SqliteCredentialRepository",
    "SqliteKeyRepository",
    "WrappedKey",
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
