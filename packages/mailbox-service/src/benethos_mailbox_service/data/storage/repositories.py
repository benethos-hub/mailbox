"""The repositories together: ``Repositories`` holds one of each on the
same store, and ``open_repositories`` is the one place that picks the
implementation: in memory for tests and ``storage = memory``, else SQLite.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .accounts import AccountRepository, InMemoryAccountRepository
from .audit import AuditRepository, InMemoryAuditRepository
from .changes import ChangeLogRepository, InMemoryChangeLogRepository
from .credentials import (
    CredentialRepository,
    InMemoryCredentialRepository,
    InMemoryKeyRepository,
    KeyRepository,
)
from .idempotency import IdempotencyRepository, InMemoryIdempotencyRepository
from .index import InMemoryMessageIndexRepository, MessageIndexRepository
from .passwords import InMemoryPasswordRepository, PasswordRepository
from .recovery_codes import InMemoryRecoveryCodeRepository, RecoveryCodeRepository
from .sends import InMemorySendLogRepository, SendLogRepository
from .sqlite import (
    Database,
    Migrated,
    SqliteAccountRepository,
    SqliteAuditRepository,
    SqliteChangeLogRepository,
    SqliteCredentialRepository,
    SqliteIdempotencyRepository,
    SqliteKeyRepository,
    SqliteMessageIndexRepository,
    SqlitePasswordRepository,
    SqliteRecoveryCodeRepository,
    SqliteRoleRepository,
    SqliteSendLogRepository,
    SqliteTokenRepository,
    SqliteTotpRepository,
    SqliteUserRepository,
    SqliteWebhookRepository,
)
from .totp import InMemoryTotpRepository, TotpRepository
from .users import (
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
    RoleRepository,
    TokenRepository,
    UserRepository,
)
from .webhooks import InMemoryWebhookRepository, WebhookRepository


class Store(Protocol):
    """What holds the records of all repositories: an image of it for a
    backup, the mark of a running service, and closing."""

    def snapshot_file(self) -> AbstractContextManager[Path]:
        """A consistent image of every record, taken while it is in use,
        as a file readable by its owner alone, gone when the block ends."""
        ...

    def transaction(self) -> AbstractContextManager[object]:
        """One transaction over every repository of the store. Inside
        another one, a part of it that is undone alone."""
        ...

    def serving(self) -> AbstractContextManager[bool]:
        """Mark the store as used by a running service while the block
        runs. False when another service marked it already."""
        ...

    def close(self) -> None: ...

    def schema_version(self) -> int:
        """The version of the schema the records are in."""
        ...

    @property
    def migrated(self) -> Migrated | None:
        """What opening the store did to its schema, None when nothing."""
        ...


@dataclass(frozen=True, slots=True)
class Repositories:
    """One of each, on the same store."""

    accounts: AccountRepository
    users: UserRepository
    roles: RoleRepository
    tokens: TokenRepository
    passwords: PasswordRepository
    totp: TotpRepository
    recovery_codes: RecoveryCodeRepository
    keys: KeyRepository
    credentials: CredentialRepository
    index: MessageIndexRepository
    idempotency: IdempotencyRepository
    sends: SendLogRepository
    changes: ChangeLogRepository
    webhooks: WebhookRepository
    audit: AuditRepository
    # The store behind them, for backups and for closing. None in memory.
    store: Store | None = None

    def close(self) -> None:
        if self.store is not None:
            self.store.close()


def open_repositories(
    storage: Literal["memory", "sqlite"], database_path: Path
) -> Repositories:
    if storage == "memory":
        return Repositories(
            accounts=InMemoryAccountRepository(),
            users=InMemoryUserRepository(),
            roles=InMemoryRoleRepository(),
            tokens=InMemoryTokenRepository(),
            passwords=InMemoryPasswordRepository(),
            totp=InMemoryTotpRepository(),
            recovery_codes=InMemoryRecoveryCodeRepository(),
            keys=InMemoryKeyRepository(),
            credentials=InMemoryCredentialRepository(),
            index=InMemoryMessageIndexRepository(),
            idempotency=InMemoryIdempotencyRepository(),
            sends=InMemorySendLogRepository(),
            changes=InMemoryChangeLogRepository(),
            webhooks=InMemoryWebhookRepository(),
            audit=InMemoryAuditRepository(),
        )
    db = Database(database_path)
    return Repositories(
        accounts=SqliteAccountRepository(db),
        users=SqliteUserRepository(db),
        roles=SqliteRoleRepository(db),
        tokens=SqliteTokenRepository(db),
        passwords=SqlitePasswordRepository(db),
        totp=SqliteTotpRepository(db),
        recovery_codes=SqliteRecoveryCodeRepository(db),
        keys=SqliteKeyRepository(db),
        credentials=SqliteCredentialRepository(db),
        index=SqliteMessageIndexRepository(db),
        idempotency=SqliteIdempotencyRepository(db),
        sends=SqliteSendLogRepository(db),
        changes=SqliteChangeLogRepository(db),
        webhooks=SqliteWebhookRepository(db),
        audit=SqliteAuditRepository(db),
        store=db,
    )
