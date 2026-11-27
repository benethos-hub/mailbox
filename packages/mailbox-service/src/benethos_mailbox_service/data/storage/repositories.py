"""The repositories together: ``Repositories`` holds one of each on the
same store, and ``open_repositories`` is the one place that picks the
implementation: in memory for tests and ``storage = memory``, a file of
SQLite for ``sqlite``, a schema on a server for ``postgres``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from benethos_mailbox_common.storage import stored

from ...errors import StorageError
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
    Database,
    Server,
    ServerPlace,
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

# What holds the records of a store, as the storage of mailbox-common
# says it.
Records = stored.Records
Store = stored.Store


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
    # On a server: whether its database is closed to every other role.
    # None for another storage.
    database_closed: bool | None = None

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
        place = ServerPlace(server)
        db = Database(place=place)
        try:
            closed = place.close_to_others()
        except BaseException:
            db.close()
            raise
        return dataclasses.replace(repositories_on(db), database_closed=closed)
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
