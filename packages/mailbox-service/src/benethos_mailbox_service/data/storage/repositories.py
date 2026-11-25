"""The repositories together: ``Repositories`` holds one of each on the
same store, and ``open_repositories`` is the one place that picks the
implementation: in memory for tests and ``storage = memory``, else SQLite.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

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
from .links import InMemoryLinkRepository, LinkRepository
from .outbox import InMemoryOutboxRepository, OutboxRepository
from .passkeys import InMemoryPasskeyRepository, PasskeyRepository
from .passwords import InMemoryPasswordRepository, PasswordRepository
from .recovery_codes import InMemoryRecoveryCodeRepository, RecoveryCodeRepository
from .sends import InMemorySendLogRepository, SendLogRepository
from .sql import (
    SqlAccountRepository,
    SqlAuditRepository,
    SqlIdempotencyRepository,
    SqlLinkRepository,
    SqlPasskeyRepository,
    SqlPasswordRepository,
    SqlRecoveryCodeRepository,
    SqlRoleRepository,
    SqlTokenRepository,
    SqlTotpRepository,
    SqlUserRepository,
)
from .sql.database import Database
from .sqlite import (
    Migrated,
    SqliteChangeLogRepository,
    SqliteCredentialRepository,
    SqliteKeyRepository,
    SqliteMessageIndexRepository,
    SqliteOutboxRepository,
    SqliteSendLogRepository,
    SqliteWebhookRepository,
    Table,
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

    def tables(self) -> list[Table]:
        """Every table of the schema with its columns and key, each after
        the tables it refers to."""
        ...

    def rows(self, table: str) -> Iterator[tuple[Any, ...]]:
        """The rows of a table of ``tables`` in the order of its key, read
        in chunks."""
        ...

    def fill(
        self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
    ) -> int:
        """Write ``rows`` into ``table``, which holds none yet. How many."""
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
    passkeys: PasskeyRepository
    recovery_codes: RecoveryCodeRepository
    keys: KeyRepository
    credentials: CredentialRepository
    index: MessageIndexRepository
    idempotency: IdempotencyRepository
    sends: SendLogRepository
    changes: ChangeLogRepository
    webhooks: WebhookRepository
    audit: AuditRepository
    links: LinkRepository
    outbox: OutboxRepository
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
            passkeys=InMemoryPasskeyRepository(),
            recovery_codes=InMemoryRecoveryCodeRepository(),
            keys=InMemoryKeyRepository(),
            credentials=InMemoryCredentialRepository(),
            index=InMemoryMessageIndexRepository(),
            idempotency=InMemoryIdempotencyRepository(),
            sends=InMemorySendLogRepository(),
            changes=InMemoryChangeLogRepository(),
            webhooks=InMemoryWebhookRepository(),
            audit=InMemoryAuditRepository(),
            links=InMemoryLinkRepository(),
            outbox=InMemoryOutboxRepository(),
        )
    return repositories_on(Database(database_path))


def repositories_on(db: Database) -> Repositories:
    """The repositories on a database already open, each on that one.
    The one place that names the classes of the database."""
    return Repositories(
        accounts=SqlAccountRepository(db),
        users=SqlUserRepository(db),
        roles=SqlRoleRepository(db),
        tokens=SqlTokenRepository(db),
        passwords=SqlPasswordRepository(db),
        totp=SqlTotpRepository(db),
        passkeys=SqlPasskeyRepository(db),
        recovery_codes=SqlRecoveryCodeRepository(db),
        keys=SqliteKeyRepository(db),
        credentials=SqliteCredentialRepository(db),
        index=SqliteMessageIndexRepository(db),
        idempotency=SqlIdempotencyRepository(db),
        sends=SqliteSendLogRepository(db),
        changes=SqliteChangeLogRepository(db),
        webhooks=SqliteWebhookRepository(db),
        audit=SqlAuditRepository(db),
        links=SqlLinkRepository(db),
        outbox=SqliteOutboxRepository(db),
        store=db,
    )
