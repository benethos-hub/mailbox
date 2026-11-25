"""The storage spoken through SQLAlchemy Core: the types and what differs
between databases (``dialect``), the tables of the schema (``schema``),
the database the repositories use (``database``), the rows of a table
keyed by ``id`` (``rows``) and the repositories, one module per subject.
The only package that imports ``sqlalchemy``."""

from __future__ import annotations

from .accounts import SqlAccountRepository
from .audit import SqlAuditRepository
from .credentials import SqlCredentialRepository, SqlKeyRepository
from .idempotency import SqlIdempotencyRepository
from .links import SqlLinkRepository
from .outbox import SqlOutboxRepository
from .passkeys import SqlPasskeyRepository
from .passwords import SqlPasswordRepository
from .recovery_codes import SqlRecoveryCodeRepository
from .sends import SqlSendLogRepository
from .totp import SqlTotpRepository
from .users import SqlRoleRepository, SqlTokenRepository, SqlUserRepository

__all__ = [
    "SqlAccountRepository",
    "SqlAuditRepository",
    "SqlCredentialRepository",
    "SqlIdempotencyRepository",
    "SqlKeyRepository",
    "SqlLinkRepository",
    "SqlOutboxRepository",
    "SqlPasskeyRepository",
    "SqlPasswordRepository",
    "SqlRecoveryCodeRepository",
    "SqlRoleRepository",
    "SqlSendLogRepository",
    "SqlTokenRepository",
    "SqlTotpRepository",
    "SqlUserRepository",
]
