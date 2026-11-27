"""The area system: the service itself, its start, schema and stop, its
background loops, the recovery key, the log page, the keys and backups
of the host. What the assembly records is here as well (docs/mailbox-service/LOGGING.md
5.1, 5.8)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

# Named apart from a text of its own.
from ..base import Activity, Failure, Purged


@dataclass(frozen=True, kw_only=True)
class ServiceStarted(Activity):
    name: ClassVar[str] = "started"

    settings: str | None
    database: str | None
    schema: int | None

    def says(self) -> str:
        settings = self.settings or "the environment alone"
        if self.database is None:
            return f"started: settings from {settings}, storage in memory"
        return (
            f"started: settings from {settings}, database {self.database}, "
            f"schema {self.schema}"
        )


@dataclass(frozen=True, kw_only=True)
class SchemaMigrated(Activity):
    name: ClassVar[str] = "migrated"

    before: int
    after: int
    notes: tuple[str, ...] = ()

    def says(self) -> str:
        if self.before == 0:
            text = f"created the database with schema {self.after}"
        elif self.before == self.after:
            text = f"opened the database with schema {self.after}"
        else:
            text = f"migrated the database schema from {self.before} to {self.after}"
        return "; ".join([text, *self.notes])


@dataclass(frozen=True, kw_only=True)
class ServiceStopped(Activity):
    name: ClassVar[str] = "stopped"

    def says(self) -> str:
        return "stopped"


@dataclass(frozen=True, kw_only=True)
class LoopEnded(Failure):
    """A background loop that should run until the service stops."""

    name: ClassVar[str] = "loop_ended"
    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return "ended"


@dataclass(frozen=True, kw_only=True)
class RoundFailed(Failure):
    """A round of a background loop, which goes on with the next."""

    name: ClassVar[str] = "round_failed"
    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return "could not finish a round"


@dataclass(frozen=True, kw_only=True)
class MasterKeyFromEnvironment(Activity):
    name: ClassVar[str] = "key_from_env"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "takes the master key from MAILBOX_SERVICE_MASTER_KEY. The "
            "environment shows up in process listings and container inspection"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseShared(Activity):
    name: ClassVar[str] = "shared_db"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "found another service using this database: a restore cannot tell "
            "that this one runs"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseOpen(Activity):
    """The database on a server is open to every role of the server:
    the role of the service does not own it, so it cannot close it."""

    name: ClassVar[str] = "db_open"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "found its database open to every role of the server: the role"
            " of the service does not own it, so an administrator closes it"
            " (containers/production/mailbox-service/README.md)"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseAway(Activity):
    """The database server cannot be reached: once, when it goes."""

    name: ClassVar[str] = "db_away"
    level: ClassVar[int] = logging.WARNING

    cause: str

    def says(self) -> str:
        return (
            f"cannot reach the database ({self.cause}): every request answers"
            " 503 until it is back"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseBack(Activity):
    """The database server answers again, after so many seconds."""

    name: ClassVar[str] = "db_back"

    seconds: float

    def says(self) -> str:
        return f"reaches the database again, after {self.seconds:.0f} seconds"


@dataclass(frozen=True, kw_only=True)
class DatabaseTaken(Activity):
    """Another service took the database while it was away: this one
    stops, as two would lose changes."""

    name: ClassVar[str] = "db_taken"
    level: ClassVar[int] = logging.ERROR

    def says(self) -> str:
        return (
            "found another service on the database when it was back, and"
            " stops: one service per database"
        )


@dataclass(frozen=True, kw_only=True)
class DatabaseUnencrypted(Activity):
    """The settings switched TLS to the database server off."""

    name: ClassVar[str] = "db_unencrypted"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return (
            "talks to the database server without TLS, as"
            " MAILBOX_SERVICE_DATABASE_TLS=off says: only on a private network"
        )


@dataclass(frozen=True, kw_only=True)
class RecoveryKeyShown(Activity):
    """The master key written out went to a person's screen."""

    name: ClassVar[str] = "recovery_shown"
    audited: ClassVar[bool] = True

    def says(self) -> str:
        return "was shown the recovery key in the UI"


@dataclass(frozen=True, kw_only=True)
class LogRead(Activity):
    """The log names users, addresses and accounts: who read it is
    logged, once per visit, not per page of it."""

    name: ClassVar[str] = "log_read"
    audited: ClassVar[bool] = True

    def says(self) -> str:
        return "read the service log"


@dataclass(frozen=True, kw_only=True)
class KeysCreated(Activity):
    name: ClassVar[str] = "keys_created"

    def says(self) -> str:
        return "created the master key and the data key"


@dataclass(frozen=True, kw_only=True)
class MasterKeyStored(Activity):
    name: ClassVar[str] = "key_imported"

    def says(self) -> str:
        return "stored the master key from a recovery key"


@dataclass(frozen=True, kw_only=True)
class BackupWritten(Activity):
    name: ClassVar[str] = "backup_written"

    file: str
    schema: int
    format: int

    def says(self) -> str:
        return (
            f"wrote a backup to {self.file}, schema {self.schema}, format {self.format}"
        )


@dataclass(frozen=True, kw_only=True)
class BackupRestored(Activity):
    name: ClassVar[str] = "backup_restored"

    file: str
    schema: int
    # When the backup was made, as its manifest says.
    made: str
    format: int

    def says(self) -> str:
        return (
            f"restored the backup {self.file} of {self.made}, schema"
            f" {self.schema}, format {self.format}"
        )


@dataclass(frozen=True, kw_only=True)
class AuditPurged(Purged):
    """Records older than the audit keeps are gone. The normal course,
    once an hour at most."""

    name: ClassVar[str] = "audit_purged"
    purged_from: ClassVar[str] = "the audit"


@dataclass(frozen=True, kw_only=True)
class NotAudited(Failure):
    """An activity the audit could not keep. Its line is in the log."""

    name: ClassVar[str] = "not_audited"
    level: ClassVar[int] = logging.ERROR

    # The activity's <area>.<name>.
    activity: str

    def says(self) -> str:
        return f"could not keep {self.activity} in the audit"
