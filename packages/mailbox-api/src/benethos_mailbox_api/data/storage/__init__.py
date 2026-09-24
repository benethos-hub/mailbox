"""Persistence, split by subject. Callers import from here, not the modules."""

from __future__ import annotations

from .accounts import AccountRepository, InMemoryAccountRepository
from .sqlite import (
    Database,
    SqliteAccountRepository,
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
