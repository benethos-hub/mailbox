"""The repositories together: ``Repositories`` holds one of each on the
same store, and ``open_repositories`` is the one place that picks the
implementation: in memory for tests and ``storage = memory``, a file of
SQLite for ``sqlite``, a schema on a server for ``postgres``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from ...errors import StorageError, StorageUnavailableError
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
from .migrated import Migrated
from .outbox import InMemoryOutboxRepository, OutboxRepository
from .passkeys import InMemoryPasskeyRepository, PasskeyRepository
from .passwords import InMemoryPasswordRepository, PasswordRepository
from .recovery_codes import InMemoryRecoveryCodeRepository, RecoveryCodeRepository
from .sends import InMemorySendLogRepository, SendLogRepository
from .sql import (
    SqlAccountRepository,
    SqlAuditRepository,
    SqlChangeLogRepository,
    SqlCredentialRepository,
    SqlIdempotencyRepository,
    SqlKeyRepository,
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
from .sql.database import Database
from .sql.outage import Availability
from .sql.server_place import Server, ServerPlace
from .sql.tables import Table
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


class Records(Protocol):
    """The records of a store, table by table, for an export."""

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


class Store(Records, Protocol):
    """What holds the records of all repositories: a fixed view of them
    for a backup, the mark of a running service, and closing."""

    def unavailable(self) -> StorageUnavailableError | None:
        """The error a call meets now, without asking the database: None
        unless it is known to be away."""
        ...

    def watch(self, report: Callable[[Availability], None]) -> None:
        """``report`` hears of each change of whether the database can be
        reached."""
        ...

    def view(self) -> AbstractContextManager[Records]:
        """The records at one moment, taken while the store is in use,
        for the time of the block."""
        ...

    def snapshot_file(self) -> AbstractContextManager[Path]:
        """For a store that is a file: a consistent copy of it, taken
        while it is in use, readable by its owner alone, gone when the
        block ends. Another store has none and raises StorageError."""
        ...

    def transaction(self) -> AbstractContextManager[object]:
        """One transaction over every repository of the store. Inside
        another one, a part of it that is undone alone."""
        ...

    def serving(self) -> AbstractContextManager[bool]:
        """Mark the store as used by a running service while the block
        runs. A file yields False when another service marked it
        already, a server raises StorageInUseError."""
        ...

    def close(self) -> None: ...

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
    storage: Literal["memory", "sqlite", "postgres"],
    database_path: Path,
    server: Server | None = None,
) -> Repositories:
    """The repositories of ``storage``: in memory, the file of SQLite at
    ``database_path``, or the schema on the server ``server`` names. Any
    other storage opens nothing."""
    if storage == "sqlite":
        return repositories_on(Database(database_path))
    if storage == "postgres":
        if server is None:
            raise StorageError("storage postgres needs the server of its database")
        return repositories_on(Database(place=ServerPlace(server)))
    if storage != "memory":
        raise StorageError(f"there is no storage {storage}")
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
        keys=SqlKeyRepository(db),
        credentials=SqlCredentialRepository(db),
        index=SqlMessageIndexRepository(db),
        idempotency=SqlIdempotencyRepository(db),
        sends=SqlSendLogRepository(db),
        changes=SqlChangeLogRepository(db),
        webhooks=SqlWebhookRepository(db),
        audit=SqlAuditRepository(db),
        links=SqlLinkRepository(db),
        outbox=SqlOutboxRepository(db),
        store=db,
    )
