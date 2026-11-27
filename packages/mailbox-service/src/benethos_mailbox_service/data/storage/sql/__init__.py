"""The storage spoken through SQLAlchemy Core: the tables of the schema
(``schema``), the database the repositories use, the storage of
mailbox-common with the shape of the service (``database``), the
revisions of the schema (``revisions/``), what of the export is the
service's own (``tables``) and the repositories, one module per
subject. The only package of the service that imports ``sqlalchemy``.
What the storage above takes of it comes from here."""

from __future__ import annotations

from benethos_mailbox_common.storage import outage, server_place
from benethos_mailbox_common.storage import tables as stored_tables

from .accounts import SqlAccountRepository
from .audit import SqlAuditRepository
from .changes import SqlChangeLogRepository
from .credentials import SqlCredentialRepository, SqlKeyRepository
from .database import SHAPE, Database, ServerPlace
from .idempotency import SqlIdempotencyRepository
from .index import SqlMessageIndexRepository
from .links import SqlLinkRepository
from .outbox import SqlOutboxRepository
from .passkeys import SqlPasskeyRepository
from .passwords import SqlPasswordRepository
from .recovery_codes import SqlRecoveryCodeRepository
from .revisions import SCHEMA_VERSION
from .sends import SqlSendLogRepository
from .totp import SqlTotpRepository
from .users import SqlRoleRepository, SqlTokenRepository, SqlUserRepository
from .webhooks import SqlWebhookRepository

Availability = outage.Availability
Server = server_place.Server
Table = stored_tables.Table

__all__ = [
    "SCHEMA_VERSION",
    "SHAPE",
    "Availability",
    "Database",
    "Server",
    "ServerPlace",
    "SqlAccountRepository",
    "SqlAuditRepository",
    "SqlChangeLogRepository",
    "SqlCredentialRepository",
    "SqlIdempotencyRepository",
    "SqlKeyRepository",
    "SqlLinkRepository",
    "SqlMessageIndexRepository",
    "SqlOutboxRepository",
    "SqlPasskeyRepository",
    "SqlPasswordRepository",
    "SqlRecoveryCodeRepository",
    "SqlRoleRepository",
    "SqlSendLogRepository",
    "SqlTokenRepository",
    "SqlTotpRepository",
    "SqlUserRepository",
    "SqlWebhookRepository",
    "Table",
]
