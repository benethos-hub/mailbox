"""The records: the repositories the settings name, the audit of
administration, and the activity log, which keeps an audited change in
the transaction of the store."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from benethos_mailbox_common.log import redact

from ..config import Settings, database_url_parts
from ..data.storage import Availability, Repositories, Server
from ..domain.activity import SERVICE, ActivityLog, Audit
from ..domain.activity import system as said


class Outages:
    """The times the database went away since the service started."""

    def __init__(self) -> None:
        self.count = 0

    def heard(self, change: Availability) -> None:
        if change.away:
            self.count += 1


@dataclass(frozen=True)
class Storage:
    repositories: Repositories
    audit: Audit
    activity: ActivityLog
    outages: Outages


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
    if settings.storage == "postgres" and settings.database_tls == "off":
        activity.record(said.DatabaseUnencrypted(by=SERVICE))
    outages = Outages()
    if store is not None:
        store.watch(partial(_heard, activity))
        store.watch(outages.heard)
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
    return Storage(repositories, audit, activity, outages)


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
        tls=settings.database_tls,
        ca_file=settings.database_ca_file,
    )


def _heard(activity: ActivityLog, change: Availability) -> None:
    """A change of whether the database can be reached, as the log says
    it: once when it goes, with the kind of the failure, once when it is
    back. The cause stands here, and nowhere a caller sees."""
    if change.away:
        activity.record(said.DatabaseAway(by=SERVICE, cause=change.cause))
    elif not change.lock_lost:
        activity.record(said.DatabaseBack(by=SERVICE, seconds=change.seconds))
