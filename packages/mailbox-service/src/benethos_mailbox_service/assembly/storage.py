"""The records: the repositories the settings name, the audit of
administration, and the activity log, which keeps an audited change in
the transaction of the store."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from benethos_mailbox_common.log import redact

from ..config import Settings, database_url_parts
from ..data.storage import Repositories, Server
from ..domain.activity import SERVICE, ActivityLog, Audit
from ..domain.activity import system as said


@dataclass(frozen=True)
class Storage:
    repositories: Repositories
    audit: Audit
    activity: ActivityLog


def storage(
    repositories: Repositories, settings: Settings, clock: Callable[[], datetime]
) -> Storage:
    """The audit and the activity log on ``repositories``. A migration at
    the start is the first line of the log."""
    audit = Audit(repositories.audit, clock=clock, days=settings.audit_days)
    store = repositories.store
    activity = ActivityLog(
        clock, audit, transaction=store.transaction if store is not None else None
    )
    migrated = store.migrated if store is not None else None
    if migrated is not None:
        activity.record(
            said.SchemaMigrated(
                by=SERVICE,
                before=migrated.before,
                after=migrated.after,
                notes=migrated.notes,
            )
        )
    return Storage(repositories, audit, activity)


def server_of(settings: Settings) -> Server | None:
    """The database server the settings name, for storage = postgres,
    with the password of its role read now and kept from every log
    line. None for another storage."""
    if settings.storage != "postgres" or settings.database_url is None:
        return None
    parts = database_url_parts(settings.database_url)
    password = settings.database_password().get_secret_value()
    redact.note(password)
    return Server(
        host=parts.hostname or "",
        port=parts.port or 5432,
        database=parts.path.removeprefix("/"),
        role=parts.username or "",
        password=password,
    )
